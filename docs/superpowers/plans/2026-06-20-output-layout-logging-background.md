# Unified output layout + two-layer logging + conditional background — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor insar-agent so a single `output_root` (specified once) yields a flat, predictable layout (`prepare/` shared inputs + `<task>_<ts>/{.insar_agent, insar_product}`), with two-layer logging (concise Layer-1 progress + raw Layer-2 logs) and conditional background dispatch for long ops.

**Architecture:** Layout centralized in `core/layout.py` (`RunLayout`) + `core/output_resolver.py` (one resolver) + a new marker-file run-root recovery (replacing `infer_run_root`'s literal-`outputs` scan). Logging adds `core/progress.py` writing `<run>/.insar_agent/progress.log`, surfaced by `insar_get_job`. Dispatch keeps the already-detached heavy compute and adds conditional background to long data-prep.

**Tech Stack:** Python 3.13, FastMCP, pytest (pythonpath=[src], `-m 'not real_data'`), ISCE2/ISCE3/MintPy via `conda run`, bash harness.

**Spec:** `docs/superpowers/specs/2026-06-20-output-layout-logging-background-design.md`

## Global Constraints

- Tests: `cd /home/august/insar-agent && python -m pytest` (pythonpath=[src] auto; `-m 'not real_data'` default). One test: `python -m pytest tests/unit/<f>.py::<t> -q`.
- TDD: failing test first → watch fail → minimal impl → watch pass → commit. No production code without a failing test first.
- Run-dir name = `<task>_<timestamp>`; `<task>` = engine+workflow id (e.g. `stack-insar-isce2`); `<timestamp>` = run-start UTC `YYYYMMDDTHHMMSSZ`.
- `prepare/` is a sibling of run dirs under `output_root` (shared across runs); per-run products under `<run>/insar_product/`; run state + Layer-1 progress + transcript under `<run>/.insar_agent/`.
- Run-root recovery = walk up to the dir containing `.insar_agent/project.json`; never scan for a literal segment.
- Clean break: do NOT migrate old `<ws>/<task>/outputs/<run>` trees; only ensure `Job.load`/`Project.load` tolerate unknown JSON keys (already do).
- Commit per task. Branch first; do NOT push unless asked.

---

## Phase 0 — Branch + baseline

### Task 0.1: Branch and green baseline
**Files:** none (git + test run)
- [ ] **Step 1: Branch** — `cd /home/august/insar-agent && git checkout -b refactor/output-layout-logging-bg`
- [ ] **Step 2: Baseline** — `python -m pytest tests/unit/ -q 2>&1 | tail -3`; record N passed (survey saw ~535). Note any pre-existing failures (not yours to fix).

---

## Phase 1 — Layout core (land + green before Phase 3)

### Task 1.1: New `RunLayout` shape
**Files:** Modify `src/insar_agent/core/layout.py` (`__init__` ~88-93; subdir props 96-146; `validate_workspace_root` 47-63; `to_dict` 182; `make_run_id`). Test: `tests/unit/test_core_layout.py` (rewrite 51-172).
**Interfaces — Produces:** `RunLayout(output_root, task, run_id=None)` with `.run_root == <output_root>/<task>_<run_id>`; `.insar_product_dir`, `.agent_state_dir` (=run_root/.insar_agent), `.prepare_dir` (=output_root/prepare), `.progress_path` (=agent_state_dir/progress.log), `.jobs_dir` (=agent_state_dir/jobs); product subdirs re-parented under insar_product/ (`products_dir, scratch_dir, configs_dir, logs_dir, stack_dir, network_dir, mintpy_dir, exports_dir, param_advisor_dir, param_tuned_dir, troposphere_dir`); `prepare_dir/'dem'|'orbits'|'safe'`.

- [ ] **Step 1: Failing test** (replace old shape asserts in test_core_layout.py)
```python
def test_run_root_flat_under_output_root():
    rl = RunLayout("/out", "stack-insar-isce2", "20260620T010203Z")
    assert rl.run_root == Path("/out/stack-insar-isce2_20260620T010203Z")
    assert rl.insar_product_dir == rl.run_root / "insar_product"
    assert rl.agent_state_dir == rl.run_root / ".insar_agent"
    assert rl.progress_path == rl.run_root / ".insar_agent" / "progress.log"
    assert rl.jobs_dir == rl.run_root / ".insar_agent" / "jobs"
    assert rl.prepare_dir == Path("/out/prepare")
    for n in ("products","scratch","configs","logs","stack","network","mintpy","exports","param_advisor"):
        assert getattr(rl, f"{n}_dir") == rl.insar_product_dir / n
```
- [ ] **Step 2: Verify fail** — `python -m pytest tests/unit/test_core_layout.py -q`
- [ ] **Step 3: Implement** — `__init__(self, output_root, task, run_id=None)`: `self.output_root=Path(output_root); self.task=sanitize_identifier(task); self.run_id=sanitize_identifier(run_id) if run_id else make_run_id(); self.run_root=self.output_root/f"{self.task}_{self.run_id}"`. Add the new properties; re-parent product subdirs under `insar_product_dir`; rename `browse_dir`→`exports_dir` (keep `browse_dir` alias→exports_dir); add `troposphere_dir`. Make `make_run_id()` return just the timestamp. Replace `validate_workspace_root` → `validate_output_root` (drop the "reject 'outputs'" rule; reject paths inside an existing run dir). Update `to_dict` keys.
- [ ] **Step 4: Verify pass.**
- [ ] **Step 5: Commit** — `git add -A && git commit -m "refactor(layout): flat run_root under output_root + prepare/ sibling"`

### Task 1.2: Marker-file run-root recovery
**Files:** Modify `core/layout.py` (replace `infer_run_root` 34-40). Test: `test_core_layout.py`.
**Interfaces — Produces:** `find_run_root(path)->Path|None` walks up to dir with `.insar_agent/project.json`; `infer_run_root = find_run_root` (transitional alias).
- [ ] **Step 1: Failing test**
```python
def test_find_run_root_walks_to_marker(tmp_path):
    run = tmp_path/"stack-insar-isce2_r1"; (run/".insar_agent").mkdir(parents=True)
    (run/".insar_agent"/"project.json").write_text("{}")
    deep = run/"insar_product"/"stack"/"scratch"; deep.mkdir(parents=True)
    assert find_run_root(deep) == run
    assert find_run_root(tmp_path) is None
```
- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement**
```python
def find_run_root(path):
    p = Path(path).resolve()
    for cand in (p, *p.parents):
        if (cand/".insar_agent"/"project.json").exists():
            return cand
    return None
infer_run_root = find_run_root
```
- [ ] **Step 4: Verify pass.** **Step 5: Commit** — `git commit -am "refactor(layout): marker-file run-root recovery"`

### Task 1.3: Rewrite `output_resolver.py`
**Files:** Modify `core/output_resolver.py` (`resolve_output` 144; `_layout_from_run_root` 91; `resolve_run_layout` 215; `check_output_dir_depth` 267; `param_advice_output_dir` 305; `apply_run_layout_to_runconfig` 287; `run_logs_dir` 358). Test: `tests/unit/test_output_containment.py` (rewrite 6-186), `test_output_resolver.py`.
**Interfaces — Consumes:** RunLayout, find_run_root. **Produces:** `resolve_output(run_root, subdir)` → `run_root/insar_product/<subdir>`, contained under run_root; `_layout_from_run_root` rebuilds RunLayout by reading `.insar_agent/project.json`.
- [ ] **Step 1: Failing test**
```python
def test_resolve_output_in_insar_product(tmp_path):
    run = tmp_path/"stack-insar-isce2_r1"; (run/".insar_agent").mkdir(parents=True)
    (run/".insar_agent"/"project.json").write_text(
        '{"output_root":"%s","task":"stack-insar-isce2","run_id":"r1"}' % tmp_path)
    out = resolve_output(run, "stack")
    assert out == run/"insar_product"/"stack"
```
- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement** — rewrite the 4 three-level assertions to use `find_run_root` + read `.insar_agent/project.json`; `resolve_output` joins under `run_root/insar_product`; `apply_run_layout_to_runconfig` stamps product/scratch/sas/logging paths under insar_product/; `run_logs_dir`→insar_product/logs; `param_advice_output_dir`→insar_product/param_advisor.
- [ ] **Step 4: Verify pass.** **Step 5: Commit** — `git commit -am "refactor(resolver): insar_product/ subdirs + marker-based recovery"`

### Task 1.4: `prepare/` shared-input resolver
**Files:** Modify `core/output_resolver.py` (add `prepare_input_dir`). Test: `test_output_resolver.py`.
**Interfaces — Produces:** `prepare_input_dir(output_root, kind)` (`kind in {"dem","orbits","safe","rslc"}`) → `output_root/prepare/<kind>`.
- [ ] **Step 1: Failing test**
```python
def test_prepare_input_dir(tmp_path):
    assert prepare_input_dir(tmp_path, "dem") == tmp_path/"prepare"/"dem"
    assert prepare_input_dir(tmp_path, "safe") == tmp_path/"prepare"/"safe"
```
- [ ] **Step 2-4:** verify fail → implement → verify pass. **Step 5: Commit** — `git commit -am "feat(layout): prepare/ shared-input resolver"`

---

## Phase 2 — Run state re-parent

### Task 2.1: `Project` paths → new layout
**Files:** Modify `core/project.py` (33-146). Test: new `tests/unit/test_create_project_layout.py` + update fixtures in `test_param_advice_record.py`, `test_set_processing_param.py`.
**Interfaces — Produces:** `Project(output_root, task, run_id, ...)`; `Project.run_root()`==`<output_root>/<task>_<run_id>`; `insar_dir()`==`run_root/.insar_agent`; `jobs_dir()`==`run_root/.insar_agent/jobs`; product dirs via RunLayout; `Project.load(project_id)` reads `<run_root>/.insar_agent/project.json`; `new_project(name, engine, workflow, output_root, conda_env=None)`.
- [ ] **Step 1: Failing test**
```python
def test_project_state_inside_run_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path/"reg")); (tmp_path/"reg").mkdir()
    from insar_agent.core.project import new_project
    p = new_project(name="t", engine="isce2", workflow="stack", output_root=str(tmp_path/"out"))
    p.save()
    assert p.insar_dir() == p.run_root() / ".insar_agent"
    assert (p.insar_dir()/"project.json").exists()
```
- [ ] **Step 2-4:** verify fail → replace `workspace_root` field with `output_root`; derive run_root; re-point insar_dir/jobs_dir/configs_dir/logs_dir into run_root via RunLayout; `save()` writes project.json into `insar_dir()`; update `new_project`/`load` → verify pass.
- [ ] **Step 5: Commit** — `git commit -am "refactor(project): state under run_root/.insar_agent; output_root field"`

### Task 2.2: `Job`/`DownloadJob` jobs_dir + `progress_path`
**Files:** Modify `core/jobs.py` (Job 26-53; BatchJob.jobs_dir_for 97; DownloadJob.jobs_dir_for_task 141; add `progress_path`). Test: `test_job_layout_compat.py`, `test_m2_job_tracking.py`.
**Interfaces — Produces:** each job dataclass gains `progress_path: str|None=None`; `DownloadJob.jobs_dir_for_run(run_root)`==`run_root/.insar_agent/jobs`; `load` still drops unknown keys.
- [ ] **Step 1: Failing test**
```python
def test_jobs_dir_inside_run_and_progress(tmp_path):
    from insar_agent.core.jobs import DownloadJob
    assert DownloadJob.jobs_dir_for_run(tmp_path) == tmp_path/".insar_agent"/"jobs"
    d = DownloadJob(job_id="j", output_dir=str(tmp_path), progress_path=str(tmp_path/".insar_agent/progress.log"))
    assert d.progress_path.endswith("progress.log")
def test_old_job_json_tolerated(tmp_path):
    from insar_agent.core.jobs import DownloadJob
    (tmp_path/"j.json").write_text('{"job_id":"j","run_root":"/old/ws/t/outputs/r","legacy":1}')
    assert DownloadJob.load("j", tmp_path).job_id == "j"
```
- [ ] **Step 2-4:** verify fail → add field + `jobs_dir_for_run` (keep `jobs_dir_for_task` alias) → verify pass (update `test_job_layout_compat.py` to new shape).
- [ ] **Step 5: Commit** — `git commit -am "refactor(jobs): jobs under run_root/.insar_agent + progress_path"`

---

## Phase 3 — Tool signature collapse + write re-point

### Task 3.1: `insar_create_project(output_root, engine, workflow)`
**Files:** Modify `mcp/tools/project_tools.py`. Test: `test_create_project_layout.py`.
**Interfaces — Produces:** `insar_create_project(output_root, engine, workflow, name="", conda_env="")` → creates `<output_root>/<task>_<ts>/.insar_agent/project.json`; returns `{project_id, run_root, output_root, task, run_id}`.
- [ ] **Step 1: Failing test**
```python
def test_create_project_new_layout(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path/"reg")); (tmp_path/"reg").mkdir()
    from insar_agent.mcp.server import insar_create_project
    r = insar_create_project(output_root=str(tmp_path/"out"), engine="isce2", workflow="stack")
    rr = Path(r["run_root"])
    assert rr.parent == tmp_path/"out" and rr.name.startswith("stack-insar-isce2_")
    assert (rr/".insar_agent"/"project.json").exists()
```
- [ ] **Step 2-4:** verify fail → implement (use `new_project(output_root=...)`, derive task via existing `task_id_for`) → verify pass.
- [ ] **Step 5: Commit** — `git commit -am "refactor(create_project): single output_root, flat run dir"`

### Task 3.2: Re-point the layout-writing tools to `project_id` + new dirs
**Files (read each body first):** `mcp/server.py` (insar_download_rslc @925, insar_download_dem @1100, insar_prepare_sentinel_data @1387, `_apply_run_layout_to_runconfig` @363, depth check @758, infer @577), `mcp/tools/prepare_tools.py` (@46/@143/run_batch), `mcp/tools/{param_tools,product_tools,job_tools}.py`, `mcp/_helpers.py` (delete `.parent.parent[.parent]` 134/195/214 → `find_run_root`+`Project.load`), `mcp/_app.py` (`_TASK_ROOT_MANAGEMENT_DIRS`→`{".insar_agent","insar_product"}`), `engines/isce2/runner.py` (materialize_dem_for_tops @46 → `prepare_input_dir(output_root,"dem")`), `engines/{isce2,isce3}/mintpy.py` (rebase self-rooted `logs/`+`.jobs/` onto run layout). Test: `test_m4_stack_network.py`, `test_isce3_data_prep.py`, `test_raster_export.py` + one focused test per tool group.
**Interfaces — Transformation (every site):** replace `RunLayout(workspace_root, task_id, run_id)` / parent-walks with `project=Project.load(project_id); rl=RunLayout(project.output_root, project.task, project.run_id)`; data-prep dirs → `prepare_input_dir(project.output_root, kind)` **with reuse** (skip download if target exists); processing dirs → `resolve_output(rl.run_root, subdir)`.
- [ ] **Step 1: Failing tests** (one per group): prepare_stack → returns `stack_dir == run_root/insar_product/stack`; data-prep → writes `prepare/{dem,safe,orbits}` and **reuses** an existing DEM (assert no second download when present); download_dem(background) → target under `prepare/dem`.
- [ ] **Step 2: Verify fail.**
- [ ] **Step 3: Implement** the transformation at each site; delete depth-math helpers; re-point materialize_dem + mintpy dirs.
- [ ] **Step 4: Verify pass** (group tests + `test_m4_stack_network`, `test_isce3_data_prep`, `test_raster_export`).
- [ ] **Step 5: Commit** — `git commit -am "refactor(tools): project_id + insar_product/ + prepare/ reuse; drop depth math"`
> Right-sizing: if too large, split by file group (server.py / prepare_tools.py / param+product+job / engines) — each its own green commit.

---

## Phase 4 — Two-layer logging

### Task 4.1: `core/progress.py`
**Files:** Create `src/insar_agent/core/progress.py`. Test: `tests/unit/test_progress.py`.
**Interfaces — Produces:** `append_progress(run_root, message, *, step=None, total=None)` appends `"<utc-iso>\t[<step>/<total>] <message>"` to `<run_root>/.insar_agent/progress.log`; `read_progress_tail(run_root, n=20)->str`.
- [ ] **Step 1: Failing test**
```python
def test_append_and_tail(tmp_path):
    from insar_agent.core.progress import append_progress, read_progress_tail
    rr = tmp_path/"run"; (rr/".insar_agent").mkdir(parents=True)
    append_progress(rr, "下载 DEM"); append_progress(rr, "SYNTHESIZE", step=12, total=31)
    t = read_progress_tail(rr, n=5)
    assert "下载 DEM" in t and "[12/31] SYNTHESIZE" in t
```
- [ ] **Step 2-4:** verify fail → implement → verify pass. **Step 5: Commit** — `git commit -am "feat(logging): core/progress.py Layer-1 writer"`

### Task 4.2: `insar_get_job` returns compact `progress`
**Files:** Modify `mcp/tools/job_tools.py` (4 branches ~89/166/196/230). Test: `test_m2_job_tracking.py`.
**Interfaces — Consumes:** `read_progress_tail`. **Produces:** result gains `progress` (independent of `include_logs`).
- [ ] **Step 1: Failing test** — set up a job whose run_root has `.insar_agent/progress.log` with a line; assert `insar_get_job(...)["progress"]` contains it and is not the full raw log.
- [ ] **Step 2-4:** verify fail → add `progress` key in each branch (run_root via `find_run_root`) → verify pass. **Step 5: Commit** — `git commit -am "feat(logging): insar_get_job compact progress"`

### Task 4.3: GDAL FutureWarning suppression
**Files:** Modify `mcp/_helpers.py` `_conda_safe_env` (~12-18) + `engines/isce2/sentinel/_common.py` (~14-18). Test: `tests/unit/test_conda_env.py`.
- [ ] **Step 1: Failing test**
```python
def test_conda_env_silences_gdal_warning():
    from insar_agent.mcp._helpers import _conda_safe_env
    assert "FutureWarning" in _conda_safe_env({}).get("PYTHONWARNINGS","")
```
- [ ] **Step 2-4:** verify fail → set/merge `env["PYTHONWARNINGS"]="ignore::FutureWarning"` in both copies → verify pass. **Step 5: Commit** — `git commit -am "fix(logging): silence child GDAL FutureWarning"`

### Task 4.4: Emit Layer-1 markers
**Files:** Modify `engines/isce2/stack.py` (echoes 110-116 → tee `$PROGRESS_FILE`), `engines/isce2/assets/run_mintpy_isce2_stack.sh` (59-71), `engines/isce2/sentinel/prepare.py` (repoint `_append_log` step lines 301/369/449/474/540 → `append_progress`), `mcp/_helpers.py` (bg runners 759-944 inject `append_progress`), `mcp/server.py` (workflow launchers coarse markers ~283/471). Test: `tests/unit/test_progress_emit.py` (prep emitter, monkeypatch heavy bits).
**Interfaces — Consumes:** `append_progress`; `PROGRESS_FILE` env = `<run_root>/.insar_agent/progress.log` passed into inner shells via the command builders.
- [ ] **Step 1: Failing test** — stub prep, assert progress.log gets `SYNTHESIZE`/`DEM`/`ORBIT` lines.
- [ ] **Step 2-4:** verify fail → wire emitters (pass `PROGRESS_FILE`; `echo ... >> "$PROGRESS_FILE"`; prepare/runners call `append_progress`) → verify pass. **Step 5: Commit** — `git commit -am "feat(logging): emit Layer-1 step progress"`
> Layer-2 raw `<job>.log` already relocates under `insar_product/logs/` via Phase 1/3 — no mechanism change.

---

## Phase 5 — Conditional background dispatch

### Task 5.1: Long/short dispatch + `monitor` in returns
**Files:** Modify `mcp/server.py` (insar_prepare_sentinel_data dispatch ~1425) + bg-launch returns in `mcp/_helpers.py` (add `monitor`). Test: extend `test_sentinel_prepare_security.py`, new `test_background_dispatch.py`.
**Interfaces — Produces:** data-prep auto-backgrounds when long (scene_count>1 OR download_dem/orbits requested); bg returns include `job_id`, `poll`, `monitor` (=`tail -f <run>/.insar_agent/progress.log`), `log_path`.
- [ ] **Step 1: Failing tests**
```python
def test_multiscene_prepare_autobackgrounds(...):  # 2+ scenes + download → status "running" + job_id + monitor + poll
def test_single_quick_prepare_sync(...):           # organize-only 1 scene → inline result, no job_id
```
- [ ] **Step 2-4:** verify fail → heuristic + `monitor` field on all bg returns → verify pass. **Step 5: Commit** — `git commit -am "feat(dispatch): conditional background + user monitor command"`

---

## Phase 6 — Harness + skills + prompts + docs

### Task 6.1: Harness scripts
**Files:** Modify `/mnt/HDD2T/August/IntegrationTest2/scripts/launch-insar-claude-tmux.sh` (single `--output-root`; inject `output_root=<X>` once; transcript_dir→`<output_root>/<task>_<ts>/.insar_agent/transcript`), `finalize-tmux-transcript.sh` (read transcript from `.insar_agent/transcript`; discover run dir by `<task>_*`), `behavior-monitoring/model-run-metrics.py` (iterate `<output_root>/<task>_*`), `behavior-monitoring/product-quality-stats.py` (globs relative to `insar_product/`).
- [ ] **Step 1:** `bash -n` both shell scripts (syntax gate). **Step 2:** update the 2 python scripts; run `scripts/behavior-monitoring/test_*.py` → green. **Step 3: Commit** — `git commit -am "refactor(harness): single output_root + .insar_agent/transcript + insar_product globs"`

### Task 6.2: Skills + prompts + resources
**Files:** Modify 8 `skills/*/SKILL.md` (path templates: `<output_root>`, `prepare/`, `insar_product/`, `.insar_agent/progress.log`, `monitor`+poll discipline) + `mcp/prompts.py` (50-51,182-197) + `mcp/resources.py` workflow-guide (long-task→background+poll; single output_root). Test: `test_plugin_packaging_contract.py` + skill-contract tests (update asserted strings) → green.
- [ ] **Step 1:** update templates; contract tests green. **Step 2: Commit** — `git commit -am "docs(skills): new layout + progress + background guidance"`

### Task 6.3: Docs
**Files:** `docs/architecture.md`, `docs/engine-onboarding.md`, `docs/developer-documents/{refactor-status,MCP-tools,MCP-architechture}.md`; mark 2026-06-01 unified-output spec layout superseded.
- [ ] **Step 1:** update. **Step 2: Commit** — `git commit -am "docs: output_root/<task>_<ts> model"`

---

## Phase 7 — Verification

### Task 7.1: Full suite + small-scale + integration
- [ ] **Step 1:** `python -m pytest tests/unit/ -q` → all green (≥ baseline; new tests added).
- [ ] **Step 2:** `ruff check src/` clean.
- [ ] **Step 3: Small-scale** (insar-integration-tdd): create_project into temp `output_root`; `insar_prepare_sentinel_data(..., background=True)` on a tiny input; poll `insar_get_job`, confirm `progress` populates + files under `prepare/` and `<run>/insar_product/`.
- [ ] **Step 4: Integration:** launch DeepSeek E1 via updated harness with one `--output-root`; confirm layout (`prepare/` reused; `<task>_<ts>/{.insar_agent/progress.log, insar_product/...}`), Layer-1 progress via `monitor`, advisor subagent + hook still fire; finalize `--behavior-metrics false`.
- [ ] **Step 5: Commit** — `git commit -am "test: verify unified layout + logging + background e2e"`

---

## Self-Review (done at write time)
- **Spec coverage:** A-layout→Ph1-3; B-logging→Ph4; C-background→Ph5; harness/skills/docs→Ph6; verify→Ph7. prepare/-reuse (1.4/3.2), marker recovery (1.2), `.insar_agent` re-parent (2.1/2.2), GDAL (4.3), transcript loc (6.1), MintPy divergent logs + materialize_dem re-point (3.2) all covered.
- **Placeholder scan:** Tasks 3.2 & 4.4 span many near-identical sites; the transformation pattern + exact site list (line refs) is given, so each is executable (not "TODO"). No vague "handle edge cases".
- **Type consistency:** `RunLayout(output_root, task, run_id)`, `find_run_root`, `resolve_output(run_root, subdir)`, `prepare_input_dir(output_root, kind)`, `append_progress(run_root, msg, step, total)`, `read_progress_tail(run_root, n)`, `Project(output_root, task, run_id)`, job `progress_path` — consistent across tasks.
- **Open follow-up (non-blocking, confirm in Task 1.1):** current `make_run_id` behavior (whether it prefixes task) — ensure run-dir name isn't doubly-prefixed.
