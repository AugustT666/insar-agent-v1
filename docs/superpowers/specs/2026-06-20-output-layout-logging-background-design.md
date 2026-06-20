# Design — Unified output layout + two-layer logging + conditional background dispatch

- Date: 2026-06-20
- Status: APPROVED (brainstorming) → pending implementation plan (writing-plans)
- Scope: insar-agent plugin (`/home/august/insar-agent`) + integration harness (`/mnt/HDD2T/August/IntegrationTest2/scripts`)
- Supersedes: the **layout** portion of `docs/superpowers/specs/2026-06-01-unified-output-and-interaction*` (the `<ws>/<task_id>/outputs/<run_id>/` model). Logging/dispatch parts here are new.

## 1. Motivation (problems observed in the DeepSeek E1 integration run)

1. **600s timeout on long synchronous tools.** `insar_prepare_sentinel_data` ran 31-scene SAFE synthesis + DEM + orbit downloads synchronously and repeatedly hit the MCP client's ~600s per-tool-call timeout, forcing the data agent into a 30-min churn of retries/splits. (The heavy compute — stackSentinel/topsApp/MintPy/run_batch — already runs detached; only prep was synchronous.)
2. **No progress visibility.** Background jobs are polled via `insar_get_job`, which returns only status + the *entire raw log*. There is no concise progress channel, so neither the user nor the data agent can tell "what step / how far".
3. **Logging is raw + noisy.** Each tool dumps child-process stdout/stderr into one `.log`; GDAL `FutureWarning` from child processes (topsApp/stackSentinel/smallbaselineApp) floods the log (124 KB of warnings in the observed run). No human-readable step layer that's queryable.
4. **Output layout sprawl + a violation.** The current `<workspace_root>/<task_id>/outputs/<run_id>/` with 13 run-subdirs is deep and threads `workspace_root`+`task_id`+`run_id` independently through ~18 tools. A workspace-path injection led the agent to pass `project_root=<workspace>` and dump `dem/orbits/safe/logs` flat at the workspace top level.

## 2. Goals / Non-goals

**Goals**
- One output path, specified **once** (by the launch script OR the user prompt), under which everything lands.
- A flat, predictable per-run layout with shared "standard inputs" reused across runs.
- A two-layer logging model: Layer-1 concise step progress (user/agent), Layer-2 raw tool logs (debug only).
- Conditional background dispatch: long ops run detached + pollable with **compact** progress; short ops stay synchronous.

**Non-goals**
- No migration of existing on-disk runs (clean break; old `workspace/`, `workspace3` cleaned up out-of-band). Code must only tolerate old job JSON without crashing.
- No change to the *scientific* behavior of ISCE2/ISCE3/MintPy.
- Not removing background for heavy compute — it is inherent (hours-long) and unavoidable.

## 3. Design

### Part A — Output layout

```
<output_root>/                          # the ONE path, specified once
├── prepare/                            # data-prep products = "standard inputs", reused across runs
│   ├── dem/                            # AOI DEM (+ isce2 dem sidecars) — shared
│   ├── orbits/                         # precise orbits — shared
│   └── safe/   (rslc/ for NISAR)       # grouped SAFE per track, e.g. safe/s1a_asc_rel142/
└── <task>_<timestamp>/                 # ONE InSAR run, e.g. stack-insar-isce2_20260620T081553Z
    ├── .insar_agent/                   # run state + agent/user-facing artifacts
    │   ├── project.json                # run metadata (the run-root marker, see recovery)
    │   ├── jobs/                        # job JSONs (status/pid/log_path/progress_path)
    │   ├── progress.log                # Layer-1 progress (NEW)
    │   └── transcript/                 # harness session.json / terminal.txt / session-transcript.jsonl
    └── insar_product/                  # ALL processing products, one subdir per producing step
        ├── stack/ | network/           # coreg stack / interferogram network
        ├── products/  (merged/)        # GUNW (ISCE3) / merged ifg, unwrap, coherence (ISCE2)
        ├── mintpy/                     # velocity, timeseries, temporal coherence, baseline plots
        ├── param_advisor/  param_tuned/  # advice records + tuned runconfig
        ├── exports/                    # GeoTIFF / browse PNG  (was browse/)
        ├── troposphere/                # tropo correction (optional)
        ├── configs/                    # runconfig snapshots
        └── logs/                       # Layer-2 raw tool logs
```

Decisions:
- **`prepare/` is shared across runs** (per `output_root`), holding the standard inputs (dem, orbits, safe/rslc). data-prep tools write here and **reuse if present** (a fresh run re-uses an existing DEM/orbits/SAFE instead of re-downloading — fixes the "re-download every run" cost). This replaces the earlier `_shared/` name.
- **`<task>_<timestamp>/`** collapses the old three identity levels (`task_id` + the `outputs` segment + `run_id`) into one directory name. `<task>` is engine+workflow (e.g. `stack-insar-isce2`); `<timestamp>` is the run start (UTC, e.g. `20260620T081553Z`).
- **Single `output_root`, passed once.** `insar_create_project(output_root, engine, workflow)` creates `<output_root>/<task>_<ts>/` + `project.json` and returns `project_id`. Every other tool takes `project_id` (which carries output_root + the run dir) — tools no longer take `workspace_root`/`task_id`/`run_id` separately. The launch script and the prompt-injection pass `output_root` once.
- **Run-context recovery = marker-file walk-up.** Replace `infer_run_root` (which scans for the literal `outputs` path segment — incompatible with the new shape) with: walk up from any path until a directory containing `.insar_agent/project.json` is found; that directory is the run root. Robust, no depth math, no reserved segment name. This deletes the brittle `.parent.parent[.parent]` arithmetic in `mcp/_helpers.py`.
- **Per-step product subdirs live under `insar_product/`.** Only ~5–6 steps produce products (data-prep→prepare/, processing→stack+products, mintpy, export, troposphere, param-advisor); the existing per-step subdir set is about right, just renamed/re-parented.
- **Harness transcript → `.insar_agent/transcript/`** (was the peer `sessions/<run_id>/`).
- **Clean break.** No reader for old `<ws>/<task>/outputs/<run>` runs. `Job.load`/`Project.load` already drop unknown keys, so old job JSON won't crash; nothing else is guaranteed.

### Part B — Two-layer logging

- **Layer-1 (progress).** New `core/progress.py: append_progress(run_root, message, *, step=None, total=None)` appends a timestamped line (plain + optional JSON) to `<run>/.insar_agent/progress.log`. Resolve `run_root` via the marker-file walk-up so emitters only need a path they already hold.
  - Surfaced by **`insar_get_job`**: add a compact `progress` field = the tail of `progress.log` (last N lines / latest `step/total`). The agent's poll reads this instead of `include_logs` → keeps poll-token cost low (this is the answer to the token-economics question: background poll stays cheap because it reads compact progress, not raw logs).
  - User-facing `monitor` command in every background-launch return = `tail -f <run>/.insar_agent/progress.log`.
- **Layer-2 (raw).** Raw child stdout/stderr stays in `<run>/insar_product/logs/<job>.log` (mechanism unchanged — just relocated under `insar_product/`). Debug/post-mortem only.
- **Emitters (lowest-churn first):**
  - Reuse existing `echo "[insar-agent] Step: ..."` in `engines/isce2/stack.py` and the `run_mintpy_isce2_stack.sh` asset by passing a `PROGRESS_FILE` env var into the inner shell and teeing those echoes to it (near-free "进入 stackSentinel / run_file N / mintpy 阶段").
  - `engines/isce2/sentinel/prepare.py` already emits `LINK/SYNTHESIZE/DEM/ORBIT/VALIDATION` step lines — repoint them at `append_progress`.
  - Background runners (`_launch_dem_download_background`, `_launch_sentinel_prepare_background`) and the RSLC runner: change the injected `on_progress`/`print` to `append_progress` (download.py already produces rich `chunk %/Phase/[i/N]`).
  - Workflow launchers (`_run_workflow_isce2`, `insar_run_workflow`): coarse state markers ("正在 data-prep", "进入 stackSentinel", "launched").
  - Per-pair `第 N/total 对`: the run_parallel per-pair wrapper appends one `append_progress("pair", step=i, total=N)` as each pair finishes (`num_pairs` known at launch).
- **GDAL FutureWarning suppression.** The warning leaks from *child* processes. Inject `PYTHONWARNINGS=ignore::FutureWarning` (and GDAL exception env) into `_conda_safe_env` (both copies: `mcp/_helpers.py`, `engines/isce2/sentinel/_common.py`) so every spawned ISCE/MintPy child inherits it.
- **Consolidate** the 3 duplicate `_append_log` definitions into `runtime/logging.py` next to `append_progress` to make the Layer-1/Layer-2 split explicit.

### Part C — Conditional background dispatch

- **Rule:** inherently-long ops default to background; quick ops stay synchronous.
  - Always background (already, keep): `insar_run_workflow`, `insar_run_batch`, `insar_run_mintpy(_isce2)`.
  - Background when long: `insar_prepare_sentinel_data` / data-prep when synthesizing/downloading for a multi-scene stack (heuristic: scene_count > 1, or DEM/orbit download requested). Single-pair / organize-only prep may stay sync.
  - Sync: small/quick tools (describe, get_runconfig, set_param, list_outputs, record_advice).
- Every background return includes: `job_id`, `poll` (agent: `insar_get_job(...)`), `monitor` (user: `tail -f .../progress.log`), `log_path` (Layer-2).
- The data agent supervises via the self-paced sleep→wake→poll discipline already added to the workflow skills (long intervals, no tight loop), reading the compact Layer-1 `progress` field.

## 4. Change surface (from the survey; grounds the plan)

- **Core (hot files):** `core/layout.py` (RunLayout shape + delete/replace `infer_run_root` + rewrite `validate_workspace_root`), `core/output_resolver.py` (the one resolver + all 3-level assertions), `core/project.py` + `core/jobs.py` (move `.insar_agent` inside the run dir; add `progress_path`), `mcp/_helpers.py` (delete depth math; marker walk-up; bg runners), `mcp/_app.py` (`_TASK_ROOT_MANAGEMENT_DIRS`).
- **Tools (~18):** signature collapse to `output_root`/`project_id`; re-point write dirs. `mcp/server.py`, `mcp/tools/{prepare_tools,param_tools,product_tools,project_tools,job_tools}.py`.
- **Logging:** new `core/progress.py`; `insar_get_job` `progress` field (4 branches); emitters in `stack.py`, `sentinel/prepare.py`, `_helpers.py` runners, the mintpy/stack shell assets, `_conda_safe_env` (×2).
- **Tests:** ~8 path-asserting tests rewritten (`test_core_layout`, `test_output_containment`, `test_job_layout_compat`, `test_param_advice_record`, `test_isce3_data_prep`, `test_m4_stack_network`, `test_raster_export`, `test_collect_experiment_metrics`); new tests for marker recovery, prepare/-reuse, `progress` surfacing, conditional background.
- **Harness (4):** `launch-insar-claude-tmux.sh` (single `output_root`; transcript dir), `finalize-tmux-transcript.sh` (transcript under `.insar_agent/transcript`; run discovery), `behavior-monitoring/model-run-metrics.py` + `product-quality-stats.py` (globs relative to `insar_product/`).
- **Skills/docs (8 + prompts):** path templates in 8 `SKILL.md` + `mcp/prompts.py`; docs updated.

## 5. Testing strategy

- TDD per change: rewrite the path-asserting tests to the new shape FIRST (red), then change `RunLayout`/resolver (green).
- New unit tests: marker-file run-root recovery; `prepare/` reuse (DEM present → skip download); `append_progress` + `insar_get_job.progress`; conditional-background returns `job_id` for a multi-scene prep and a sync result for a small one; GDAL-warning env present in `_conda_safe_env`.
- Small-scale local verification (per insar-integration-tdd) before any isolated-agent run.

## 6. Implementation sequencing (phases)

1. **Layout core:** RunLayout new shape + marker recovery + `output_resolver` rewrite + `prepare/` shared area. (rewrite layout tests first)
2. **State re-parent:** `.insar_agent` inside run dir; Project/Job path methods; `progress_path` field.
3. **Tool signatures:** collapse to `output_root`/`project_id`; re-point all write dirs; `prepare/` reuse logic.
4. **Logging:** `core/progress.py`; emitters; `insar_get_job.progress`; `monitor` returns; GDAL env; consolidate `_append_log`.
5. **Conditional background:** apply the long/short rule across tools.
6. **Harness + skills + prompts + docs.**
7. **Integration verify:** DeepSeek E1 isolated run; finalize transcript-only.

## 7. Risks & watch-outs

- **Cross-run reuse** is solved by `prepare/` (shared inputs) — but data-prep tools must look there first and only download what's missing.
- **`sessions/` vs `.insar_agent/transcript/`** — harness and plugin must agree on the new transcript location (`_TASK_ROOT_MANAGEMENT_DIRS` updated; harness scripts updated in the same phase).
- **MintPy divergent logs** — `engines/{isce2,isce3}/mintpy.py` self-root logs under `<work_dir>/logs` + `.jobs`; rebase onto the run layout in the same pass (or keep, since `progress.log` is keyed off the marker not the per-tool logs dir).
- **`materialize_dem_for_tops`** writes to `<workspace_root>/isce2_dem` (escapes the run dir) — re-point into `prepare/dem/`.
- **Old job JSON** on disk: tolerate (drop unknown keys); do not attempt to read old run trees.
- **Blast radius is large (~24 src + ~31 tests + harness + skills, ~3–5 days).** Phase 1–2 land the shape; do not start phase 3 until layout tests are green.
