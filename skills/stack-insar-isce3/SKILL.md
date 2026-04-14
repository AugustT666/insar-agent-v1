---
name: stack-insar-isce3
description: >
  Use when the user has multiple NISAR RSLC files and wants to run Stack processing
  (single-reference hub-and-spoke pairs), Network processing (short-baseline any-to-any
  pairs for MintPy), or both. Invoke when the user mentions Stack-InSAR, batch processing,
  interferogram network, MintPy, time-series, multiple scenes, temporal baseline, or asks
  to process more than two RSLC files. Stack and Network are independent — either can be
  run alone. If the DEM or RSLC files are missing, invoke `data-prep` first.
---

# Stack-InSAR: Multi-scene Batch Processing (Path B)

> Stack（单主影像拓扑）与 Network（短基线任意配对）互相独立，无依赖关系，可按需单独运行。
> 两者都直接读取原始 RSLC 文件；Stack 用于建立统一的参考景，Network 用于生成 MintPy 时序反演所需的配对产品。

Path B tools operate directly on the filesystem and do not use the project registry.
Each option generates shell scripts that can be launched manually or through `insar_run_batch`.

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
- `base_runconfig`: base ISCE3 insar runconfig YAML (template). If omitted, uses the built-in default `insar` template.
- `isce3_conda_env`: conda env that contains ISCE3 and a working GDAL HDF5 plugin path
- DEM path (`.tif`) — if missing, invoke `data-prep` first
- Which option(s) to run: Stack only, Network only, or both
- Output directory (one per option if running both)
- Network mode (only if running Option B): `tbase`, `conn`, or custom pair list (see `references/network-modes.md`)
- Number of parallel jobs (`N`) for the shell scripts
- Interaction mode: `interactive` (default) or `auto`

## Hard constraints

- All ISCE3 operations must go through `insar_*` MCP tools. Do not run conda/python commands directly.
- If workflow parameters are unclear, ask the user — do not invent them.
- Core processing parameters in the base runconfig (multilook, unwrapping, etc.) are
  inherited by all pairs in the batch.
- Do not silently choose a project-specific base runconfig. Use the user-provided template.
  If the user does not provide one, use the built-in default `insar` template exposed by MCP.
- `param-advisor (engine=isce3)` is the only supported route for processing-parameter changes in
  this workflow. It must call `insar_describe_rslc`, delegate recommendation generation
  to `.claude/agents/param-advisor.md`, present `yaml_diff_preview`, collect user
  confirmation, apply accepted changes via `insar_set_processing_param`, then export the
  tuned YAML as the new `base_runconfig`.
- Before the first actual execution, confirm the chosen ISCE3 runtime. If batch execution
  uses `python_bin`, it must point into the confirmed env.
- Option A only: prefer an explicit reference date for reproducibility. If the user does
  not provide one, `reference="auto"` selects the earliest acquisition.
- For custom pair list mode: file must contain one `YYYYMMDD_YYYYMMDD` pair per line.

## Standard workflow

### Step 0 — 参数调优

收到 `PARAM_ADVISOR_PROMPT` 后，先用 Glob 工具检测 `<data_dir>/base_runconfig_param_tuned.yaml`
是否存在（`insar_prepare_stack` / `insar_prepare_network` 调用后也会在返回值中确认
`param_tuned_found` 和 `param_tuned_base_runconfig` 字段）：

- **若文件存在（或调用后 `param_tuned_found: true`）**：
  - interactive：提示用户"已有已优化参数文件（路径），是否复用？"，等待确认后复用或重新调优
  - auto：直接将其作为 base_runconfig 传入后续选项，跳过调优
- **若不存在**，根据 interaction_mode 决策：

**interactive 模式：** 询问用户是否在生成 runconfigs 之前进行参数调优，等待确认。
提供三个选项：
1. 使用默认参数，直接继续
2. 进入 param-advisor (engine=isce3) 进行专家调优
3. 手动指定 base_runconfig 路径

**auto 模式：** 直接进入 `param-advisor (engine=isce3)`，无需用户确认。
自动接受推荐参数，导出调优后的 YAML 作为 base_runconfig。

param-advisor (engine=isce3) 调用链（Path B）：
- `insar_describe_rslc`（data_dir 中代表性 RSLC 的元数据）
- `.claude/agents/param-advisor.md`（生成推荐）
- interactive：展示 yaml_diff_preview，等待确认；auto：自动接受
- 若接受：`insar_set_processing_param`（临时 project）
- **落盘**：将调优后的 YAML 保存为 `<data_dir>/base_runconfig_param_tuned.yaml`，供后续复用
- 使用该文件作为后续选项的 base_runconfig

若用户选择跳过，使用内置默认模板或用户指定路径。

---

运行以下选项中的一个或两个，顺序不限：

### Option A — Single-reference stack

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

- If `handoff_required=true`, stop. Show the reference date, number of secondary scenes,
  `run_command`, and the listed review artifacts. Wait for user approval before executing.
- If `handoff_required=false`, show the same information briefly, then continue.

```
insar_run_batch(
    batch_dir=<stack_output_dir>,
    max_jobs=<N>,
    execution_mode="parallel",
    python_bin=<path from isce3_conda_env>,
    interaction_mode=<interactive|auto>
)
```
Tell the user: `tail -f <log_path>` to monitor. Poll `insar_get_job(job_id=..., batch_dir=...)` until done.
Or execute manually: `bash <stack_output_dir>/run_parallel.sh <stack_output_dir> <N>`

### Option B — Short-baseline network

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

- If `handoff_required=true`, stop. Show the network mode, pair count, pair-list path,
  `gunw_pattern`, and the listed review artifacts. Let the user adjust before executing.
- If `handoff_required=false`, show the same information briefly, then continue.

```
insar_run_batch(
    batch_dir=<network_output_dir>,
    max_jobs=<N>,
    execution_mode="parallel",
    python_bin=<path from isce3_conda_env>,
    interaction_mode=<interactive|auto>
)
```
Tell the user: `tail -f <log_path>` to monitor. Poll `insar_get_job(batch_dir=...)` until done.
Or execute manually: `bash <network_output_dir>/run_parallel.sh <network_output_dir> <N>`

## Output requirements (report after each completed option)

- Base runconfig source path, and whether `param-advisor (engine=isce3)` was used
- If Option A ran: number of secondary scenes, reference date, `run_command`
- If Option B ran: network mode, number of pairs, pair list path, `run_command`
- Final GUNW output: `<output_dir>/runs/<date1>_<date2>/products/GUNW_*.h5`
- In `interactive` mode, treat MCP handoff points as mandatory user review windows.

## Practical notes

- Path B touches three config layers:
  - `base_runconfig`: the starting ISCE3 template approved for this run
  - generated pair runconfigs under `runconfigs/`: one YAML per stack pair or network pair
  - `mintpy_config`: separate MintPy config, used later by `mintpy` (engine=isce3), not by this skill
- A failed batch with no products is often an environment problem, not a pairing problem.
  Check the selected runtime before regenerating.

## References

- `references/network-modes.md` — network strategy options and parameters
- `references/baseline-viz.md` — baseline network visualization after Option B
