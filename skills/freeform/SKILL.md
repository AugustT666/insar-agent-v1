---
name: freeform
description: >
  This skill should be used when the user wants ad-hoc or partial InSAR
  execution rather than a full end-to-end workflow: "只跑一段", "rerun one
  stage", "resume from step N", "re-unwrap", "只重跑 unwrap/geocode",
  "reprocess an intermediate file", "复用引擎小工具", "只跑 run_05 到 run_08",
  "重跑一个 MintPy 版本". It maps each engine's native partial-execution
  granularity onto the existing gated insar_* MCP tools. Do not invoke for a
  first full run (use the engine workflow skills) or for data prep (use
  data-prep).
version: 0.1.0
---

# Freeform — Engine-Native Partial Execution

Use this skill to run a slice of a workflow, resume from a step, rerun one
stage, or reprocess an intermediate file — WITHOUT leaving the safety envelope.
It is a thin routing/config skill: it never executes engines directly and never
invents a finer granularity than the engine itself provides.

## Hard Constraints (safety red lines)

- Never run `run_files/` (or any engine script) with bare `bash`/`. ` yourself.
  ISCE2 stack execution goes ONLY through `insar_run_workflow`, which sources
  `run_NN` with `. "$f"` + `sync` barriers to preserve wait/env semantics.
- run-containment: every product/scratch path must stay inside the run's
  `run_root`. Do not point ISCE3 `product_path`/`scratch_path` outside it.
- Irreversible execution still passes the PreToolUse param-advisor gate. There
  is no fast-path that bypasses it. Non-path science parameters still require
  user confirmation (or `auto` mode).
- Partial execution is exposed as NEW PARAMETERS on existing gated tools, never
  as a new bypass tool.
- Any `insar_set_processing_param(...)` call (e.g. the MintPy `scope="mintpy"`
  tuning referenced below) still requires the run to be armed first via
  `insar_arm_param_write(project_id, mode=...)`. This skill never arms or calls
  `insar_set_processing_param` itself — that belongs to the `param-advisor`
  skill's flow.
- Default to read-only inspection first (`insar_get_job`, `insar_list_outputs`,
  `insar_get_runconfig`). Escalate to a mutating/exec call only after the user
  agrees.

## Engine-Native Granularity Map

| Engine / flow | Native unit | How to run a slice |
|---|---|---|
| ISCE2 stack | `run_files/run_NN` | `insar_run_workflow(resume_from_run=N)` runs `[N..end]`. A bounded window `[start..end]` is available on `build_stack_command` (start_step/end_step); surface it through the same tool. Reuses existing `run_files/`; fails (exit 4) if there is nothing to resume. To review before the irreversible execute phase: `insar_run_workflow(generate_only=True)` runs `stackSentinel.py` prep to produce `run_files/` + `configs/` then STOPS — no execution. Show the generated files to the user, then execute with `insar_run_workflow(resume_from_run=1)`. Mutually exclusive with `resume_from_run`. |
| ISCE2 tops | `topsApp.py --steps --start/--end` | `insar_run_workflow(from_step=..., to_step=...)`. Step names are validated against a fixed topsApp whitelist (e.g. `unwrap`, `geocode`). Runs with `run_root` as cwd so `PICKLE/` + `merged/` resolve. Use to re-unwrap/geocode after a bad unwrap. |
| ISCE3 single pair | runconfig stage `enabled:` toggles (ISCE3 has no CLI step selection) | `insar_set_runconfig_value` on a curated stage-enable key (e.g. `runconfig.groups.processing.dense_offsets.enabled`, `...rubbersheet.enabled`, `...fine_resample.enabled`, `...troposphere_delay.enabled`, `...ionosphere_phase_correction.enabled`, `...offsets_product.enabled`) then rerun. Keep `product_path`/`scratch_path` in `run_root`. |
| ISCE3 batch | `run_parallel.sh` / `run_all.sh` SKIP-if-valid | `insar_run_batch`. Runners skip products that open as valid HDF5 and rerun missing/corrupt ones — no manual deletion needed. |
| MintPy | `smallbaselineApp.py --start/--dostep/--end` | `insar_run_mintpy_isce2(start_step=..., end_step=...)`. To keep a prior result, point `mintpy_work_dir` at a NEW directory = a new MintPy version; change science keys via `insar_set_processing_param(scope="mintpy")` (gated) first. **A tuned rerun MUST then pass `mintpy_config=<mintpy_work_dir>/isce2_stack.txt` explicitly** — `insar_run_mintpy_isce2(mintpy_work_dir=..., stack_work_dir=..., mintpy_config="<mintpy_work_dir>/isce2_stack.txt", ...)`. Omitting `mintpy_config` (or passing `mintpy_config=""`) regenerates the template from defaults via `smallbaselineApp.py -g` and SILENTLY DISCARDS the `scope="mintpy"` edits. |

## Intermediate-File Tools (freestanding, already gated by name where relevant)

- `insar_geocode_runw` — geocode a RUNW product to GeoTIFF.
- `insar_apply_troposphere_isce2` — ERA5 tropo post-correction for topsApp.
- `insar_export_geotiff` — export a product raster.
- `insar_plot_baseline` — spatiotemporal baseline network plot.

Do not add post-hoc reprocessing tools speculatively; request one only when a
concrete need appears (YAGNI).

## Procedure

1. Identify the run: get `project_id` / `run_root` / `job_id` from the
   conversation, or read them back with `insar_get_project` / `insar_get_job`.
2. Confirm the native unit for the engine/flow from the table above.
3. State the exact slice to the user (which steps / which stage / which window)
   and the tool call you will make. For non-path science changes, surface the
   diff and wait for confirmation (interactive) unless the session is `auto`.
4. Execute via the mapped gated MCP tool. Never hand-run engine scripts.
5. Poll with `insar_get_job` at minute-level intervals; report step + percent.

## Handoff

- Full first run instead of a slice -> the engine workflow skill
  (`d-insar-isce2`, `stack-insar-isce2`, `d-insar-isce3`, `stack-insar-isce3`).
- MintPy version/config tuning -> `mintpy` + `param-advisor` (scope=mintpy).
- Parameter recommendations before a rerun -> `param-advisor`.
- Turning a repeated manual slice into a reusable asset -> `yodo`.
