---
name: stack-insar-isce3
description: >
  Use when the user has multiple NISAR RSLC files and wants to generate a batch
  interferogram network for time-series analysis. Invoke when the user mentions
  Stack-InSAR, batch processing, interferogram network, MintPy, time-series,
  multiple scenes, temporal baseline, or asks to process more than two RSLC files.
  Also invoke when the user wants to run parallel ISCE3 jobs across a scene stack.
  If the DEM or RSLC files are missing, invoke data-prep-nisar first.
---

# Stack-InSAR: Multi-scene Batch → Interferogram Network (Path B)

Path B tools operate directly on the filesystem and do not use the project registry.
Each step generates shell scripts that can either be launched manually or through
`insar_run_batch`.

## Execution modes

- Default to `interaction_mode="interactive"`.
- At the start, tell the user they can switch to `interaction_mode="auto"` if they want
  the AI to keep going with minimal interruptions.
- In `interactive` mode, obey the MCP response: when `handoff_required=true`, stop and
  let the user review the listed artifacts before continuing.
- In `auto` mode, keep executing when inputs are complete, but still show `log_path`,
  `poll`, and key output paths after every background launch.

## Required confirmations (ask only if missing)

- `data_dir`: directory containing multiple NISAR RSLC `.h5` files
- `base_runconfig`: base ISCE3 insar runconfig YAML (template). If omitted, Path B uses the built-in default `insar` template.
- `isce3_conda_env`: conda env that contains ISCE3 and a working GDAL HDF5 plugin path
- DEM path (`.tif`) — if missing, invoke `data-prep-nisar` first
- Output directory for stack and network results
- Network mode: `tbase`, `conn`, or custom pair list (see `references/network-modes.md`)
- Number of parallel jobs (`N`) for the shell scripts
- Interaction mode: `interactive` (default) or `auto`

## Hard constraints

- All ISCE3 operations must go through `insar_*` MCP tools. Do not run conda/python commands directly.
- If workflow parameters are unclear, ask the user — do not invent them.
- Core processing parameters in the base runconfig (multilook, unwrapping, etc.) are
  inherited by all pairs in the stack.
- Do not silently choose a project-specific base runconfig. Use the user-provided template.
  If the user does not provide one, use the built-in default `insar` template exposed by MCP.
- If the user wants parameter tuning, this workflow must invoke `param-advisor-isce3`
  **before Step 1** using a temporary project.
- `param-advisor-isce3` is the only supported route for processing-parameter changes in
  this workflow. It must call `insar_describe_rslc`, delegate recommendation generation
  to `.claude/agents/param-advisor-isce3.md`, present `yaml_diff_preview`, collect user
  confirmation, apply accepted changes via `insar_set_processing_param`, then export the
  tuned YAML as the new `base_runconfig`.
- Do not invoke `param-advisor-isce3` automatically. Run it only when the user asks for
  parameter tuning or explicitly asks for parameter recommendations.
- Before the first actual execution, confirm the chosen ISCE3 runtime. If batch execution
  uses `python_bin`, it must point into the confirmed env.
- Run Step 1 and Step 2 separately.
- Prefer an explicit reference date for reproducibility. If the user does not provide one,
  `reference="auto"` selects the earliest acquisition.
- For custom pair list mode: file must contain one `YYYYMMDD_YYYYMMDD` pair per line.

## Standard workflow (always follow this order)

### Step 0 — Optional parameter advisory

Run this only when the user wants to tune multilook, filtering, unwrapping,
ionosphere correction, troposphere correction, or other processing parameters
in the base runconfig.

- Enter `param-advisor-isce3` before generating any stack or network runconfigs.
- Use a temporary project to hold the working runconfig state.
- The required call chain is:
  `param-advisor-isce3` → `insar_describe_rslc` → `.claude/agents/param-advisor-isce3.md`
  → user diff review / confirmation → `insar_set_processing_param`
- If the user accepts the recommendation, export the tuned YAML and use it as the new
  `base_runconfig` for both Step 1 and Step 2.

### Step 1 — Generate single-reference stack

```
insar_prepare_stack(
    data_dir=<rslc_dir>,
    base_runconfig=<template.yaml>,
    dem=<dem.tif>,
    output_dir=<stack_output_dir>,
    reference="auto",   # or YYYYMMDD, or absolute path
    interaction_mode=<interactive|auto>
)
```

The response includes `run_command`, `handoff_required`, `handoff_reason`,
`review_artifacts`, and `next_recommended_action`.

- If `handoff_required=true`, stop. Show the reference date, number of secondary scenes,
  `run_command`, and the listed review artifacts. Wait for the user to approve or ask for
  a different reference before launching execution.
- If `handoff_required=false`, show the same information briefly, then continue.

**Option A — AI 代为执行（推荐）：**
```
insar_run_batch(
    batch_dir=<stack_output_dir>,
    max_jobs=<N>,
    execution_mode="parallel",   # or "serial"
    python_bin=<path from isce3_conda_env>,
    interaction_mode=<interactive|auto>
)
```
Returns `job_id`, `log_path`, `poll`, `command`, and `progress_hint`. Tell the user they can monitor real-time output with:
```bash
tail -f <log_path>
```
Poll `insar_get_job(job_id=<job_id>, batch_dir=<stack_output_dir>)` every ~30s until `status` is `done` or `failed`.

**Option B — 用户自行执行：**
```bash
bash <stack_output_dir>/run_parallel.sh <stack_output_dir> <N>
```
Wait for the user to confirm completion before proceeding to Step 2.

### Step 2 — Generate interferogram network

```
insar_prepare_network(
    data_dir=<rslc_dir>,
    base_runconfig=<template.yaml>,
    dem=<dem.tif>,
    output_dir=<network_output_dir>,
    network_mode="tbase",
    max_temporal_baseline_days=36,
    connection_span=3,
    pair_list="",
    interaction_mode=<interactive|auto>
)
```

See `references/network-modes.md` for network strategy options.

The response includes `run_command`, `gunw_pattern`, `handoff_required`,
`review_artifacts`, and `next_recommended_action`.

- If `handoff_required=true`, stop. Show the network mode, pair count, pair-list path,
  `gunw_pattern`, and the listed review artifacts. Let the user adjust the network before
  execution if needed.
- If `handoff_required=false`, show the same information briefly, then continue.

**Option A:**
```
insar_run_batch(
    batch_dir=<network_output_dir>,
    max_jobs=<N>,
    execution_mode="parallel",   # or "serial"
    python_bin=<path from isce3_conda_env>,
    interaction_mode=<interactive|auto>
)
```
Tell the user: `tail -f <log_path>` to monitor. Poll `insar_get_job(batch_dir=...)` until done.

**Option B:**
```bash
bash <network_output_dir>/run_parallel.sh <network_output_dir> <N>
```

## Output requirements (report after each step)

- Base runconfig source path, and whether `param-advisor-isce3` was used
- Step 1: number of secondary scenes, reference date, `run_command` to execute
- Step 2: network mode, number of pairs, pair list path, `run_command` to execute
- Final output structure: `<network_output_dir>/runs/<date1>_<date2>/products/GUNW_*.h5`
- In `interactive` mode, treat MCP handoff points as mandatory user review windows.

## Practical notes

- Path B touches three config layers:
  - `base_runconfig`: the starting ISCE3 template approved for this run
  - generated pair runconfigs under `runconfigs/`: one YAML per stack pair or network pair
  - `mintpy_config`: separate MintPy config, used later by `mintpy-isce3`, not by this skill
- A failed batch with no products is often an environment problem, not a pairing problem.
  Check the selected runtime before regenerating the network.

## References

- `references/network-modes.md` — network strategy options and parameters
- `references/baseline-viz.md` — baseline network visualization after Step 2
