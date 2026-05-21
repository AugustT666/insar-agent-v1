---
name: stack-insar-isce2
description: >
  This skill should be used when the user needs Sentinel-1 time-series InSAR
  processing with ISCE2 (stackSentinel.py + MintPy).
  Invoke when the user wants to process multiple S1 scenes to produce a deformation
  time series or velocity map.
  Triggers on: "S1 time series", "Sentinel-1 stack", "stackSentinel", "S1 velocity",
  "s1 time-series insar", "sentinel stack processing", "isce2 stack".
  If Sentinel SAFE/ZIP inputs are not already organized into grouped SAFE paths,
  invoke `data-prep` first.
version: 0.1.0
---

# Sentinel-1 Time-Series InSAR with ISCE2

## Required confirmations (ask only if missing)

- Grouped Sentinel-1 SAFE directory (e.g., `safe/s1a_asc_rel014/`)
- DEM path (`.tif`) — if missing, invoke `data-prep` first
- Precise orbit directory — if missing, can be downloaded via `data-prep`
- Workspace / output directory (absolute path)
- Conda environment name — use `insar_check_env` only; do not run shell commands to inspect conda

## Execution modes

- Check CLAUDE.md first: if it declares AUTO mode, set `interaction_mode="auto"` immediately without notifying the user.
- Otherwise default to `interaction_mode="interactive"` and tell the user they can switch to auto at any time.
- **interactive**: At Step 5.5, pause and ask the user whether to run param-advisor (engine=isce2).
  Wait for confirmation before proceeding.
- **auto**: At Step 5.5, automatically enter param-advisor (engine=isce2) without asking.
  Skip only if the user has explicitly said to use default parameters.


## Prerequisites

```
insar_check_env()
```

Confirm `envs.isce2.status == "ok"`.
If missing, invoke the `env-setup` skill first.

---

## Workflow

### Step 1 — Ensure Sentinel data is prepared

If the user only has raw SAFE ZIP / SAFE / burst inputs, stop and invoke:

```
data-prep
```

Use one returned grouped SAFE directory plus the returned `dem_path` and `orbit_dir` as the handoff for this skill. For burst-derived SAFE inputs, require `data-prep` to return `isce2_import_validation.status == "passed"`; if it fails, stop and report the failed scene messages/logs instead of running stackSentinel.

---

### Step 2 — Inspect a representative scene

First discover available scenes using the MCP tool (do NOT use glob/read directly on the SAFE directory):

```python
insar_discover(slc_dir="/mnt/.../safe/s1a_asc_rel014/")
```

Then call describe on the first returned scene path:

```python
insar_describe_s1(zip_path="<first SAFE path from insar_discover result>")
```

Note: relative orbit, polarization, pass direction, bbox.

---

### Step 3 — Reuse prepared DEM and orbits

Prefer the `dem_path` and `orbit_dir` returned by `data-prep`.
Only ask the user for replacements if they explicitly want to override them.
The user still needs to provide:

- `workspace_root`

---

### Step 4 — Create stack project

```
insar_create_project(
    engine="isce2",
    workflow="stack",
    workspace_root=<workspace_root>,
    name="s1-stack-<region>",
    conda_env="isce2",
    task_id=<task_id>        # short identifier, e.g. "E4" — drives outputs/<task_id>/<run_id>/stack
)
```

---

### Step 5 — Set stack parameters

Mandatory fields:

```
insar_set_processing_param(project_id, key="slc_dir",
    value="/mnt/.../safe/s1a_asc_rel014", justification="directory containing grouped S1 SAFE inputs for one stack")

insar_set_processing_param(project_id, key="orbit_dir",
    value="/mnt/.../orbits", justification="prepared POEORB orbit files directory")

insar_set_processing_param(project_id, key="dem_file",
    value="/mnt/.../dem/dem.tif", justification="prepared DEM path from data-prep")
```

Key optional parameters:

| Key | Default | Notes |
|-----|---------|-------|
| `bbox` | None | Crop to AOI: `[S, N, W, E]` |
| `swaths` | `[1,2,3]` | Process subset for speed |
| `num_connections` | 3 | Interferogram connections per scene |
| `coregistration` | `"NESD"` | ESD-based; use `"geometry"` if ESD fails |
| `range_looks` / `azimuth_looks` | 20 / 4 | Multilook factors |
| `filter_strength` | 0.5 | Goldstein filter strength |
| `unwrap_method` | `"snaphu"` | Unwrapping algorithm |

---

### Step 5.5 — Optional parameter tuning

If the user wants help choosing looks, network density, coregistration mode,
filtering, or swath/bbox tradeoffs, enter:

```
param-advisor (engine=isce2)
```

This should happen **after required fields are set and before `insar_run_workflow`**.
The advisor flow should build a compressed evidence profile from:

- `insar_get_runconfig(format='yaml')`
- `insar_describe_s1(...)` on 1–3 representative scenes from `slc_dir`

The skill then delegates recommendation generation to:

- `agents/param-advisor.md`

and applies accepted changes via `insar_set_processing_param` only.

---

### Step 6 — Run stackSentinel (prepare + execute)

```
insar_run_workflow(project_id=project_id)
```

This calls `stackSentinel.py` which:
1. Reads the SAFE inputs from the selected grouped directory
2. Downloads orbit files if needed
3. Sets work_dir to `<workspace>/outputs/<task_id>/<run_id>/stack` (run-root layout)
4. Executes stack processing inside that work_dir

Returns `job_id`, `log_path`, `pid`, and `run_root`.

For multi-hour stack jobs, rely on the background job returned by `insar_run_workflow`. Always return:

- the job id
- the absolute log path (`<run_root>/logs/<job_id>.log`)
- the `run_root` (use it for MintPy: `mintpy_work_dir=<run_root>/mintpy`)
- the exact `insar_get_job` polling call

Monitor only with `insar_get_job(job_id=job_id, project_id=project_id)`.
Do not execute generated run scripts manually; the MCP tool owns stack execution.

> Runtime: several hours to days depending on scene count and AOI size.

---

### Step 7 — MintPy time-series analysis

After stack processing completes, delegate to the unified **mintpy** skill with `engine=isce2`:

```
Invoke the /insar-agent:mintpy skill
- engine: isce2
- stack_work_dir: <run_root>/stack   (returned by insar_run_workflow as run_root + "/stack")
- mintpy_work_dir: <run_root>/mintpy  (recommended run-root layout)
- conda_env: the task/user specified MintPy env, or "isce2" if none was specified
- interaction_mode: interactive (default) or auto
```

Do not use stack paths from earlier sessions, previous successful runs, or similarly named output directories.

The mintpy skill will:
- Validate the ISCE2 stack structure
- Prepare the MintPy config if needed
- Launch `insar_run_mintpy_isce2` with appropriate parameters
- Poll the background job and report completion

MintPy reads the ISCE2 stack outputs and performs:
- Network inversion → displacement time series
- Velocity estimation
- Tropospheric / DEM error correction (optional)

For advanced tuning of MintPy parameters, the user can edit the MintPy config file directly.


---

### Step 8 — Optional baseline inspection

For ISCE2 stacks, baseline products are typically prepared by topsStack itself under
`<stack_work_dir>/merged/baselines/` and `baselines_txt/`. Do **not** call the
ISCE3-only `insar_plot_baseline(network_dir=...)` tool here.

If the user wants to inspect baseline connectivity, point them to the generated
baseline text products inside the stack work directory or continue through the unified
`mintpy` skill, which treats ISCE2 baseline plotting as optional.

---

### Step 9 — Export results

```
insar_list_outputs(project_id=project_id)
insar_export_geotiff(project_id=project_id, product="velocity")
```

Key MintPy outputs:

| File | Description |
|------|-------------|
| `timeseries.h5` | Displacement time series (m) |
| `velocity.h5` | Line-of-sight velocity (m/yr) |
| `temporalCoherence.h5` | Temporal coherence mask |
| `geometryGeo.h5` | Incidence angle, heading, DEM |

---

## Hard constraints

- All scenes must share the same relative orbit number.
- If raw Sentinel inputs are not yet organized, always go through `data-prep` first.
- `data-prep` is expected to prepare grouped SAFE paths, `dem_path`, and `orbit_dir`.
- Orbit files (POEORB) must be pre-downloaded or accessible online.
  ISCE2 can auto-download them if `fetchOrbit.py` can reach ESA servers.
- `slc_dir` must contain only the S1 ZIPs/SAFEs for this stack (no mixed orbits).
- Sentinel MintPy runs in the `isce2` conda env after MintPy is installed there.
- Do not mix ascending and descending pass scenes in the same stack.
- Processing must run inside `conda run -n isce2` (handled automatically by the tool).


---

## 任务小结（Task Debrief — 强制执行）

任务最后一步，无论成功或失败，必须输出以下结构化小结，不得跳过。

```
【任务小结】
实验 ID / run_id：<task_id 或 N/A>_<run_id 或 N/A>

工作流合规性
  Skill 流程：<完全遵循 | 部分偏离 | 严重偏离>
  MCP 工具：<全程使用 mcp__insar-agent__* 接口 | 部分绕过 | 未使用>

偏离记录（如无填"无"）
  1. <偏离点：说明发生了什么，与 skill 规定步骤的差异>

根因分类（有偏离时勾选，可多选）
  □ Skill 指引不完备（步骤缺失 / 说明不清 / 边界条件未覆盖）
  □ MCP 工具问题（参数不直观 / 返回值格式异常 / 工具功能缺失）
  □ 环境 / 数据问题（conda env / 文件路径 / 权限 — 非插件问题）
  □ 其他：___

开发 agent 介入建议
  需要介入：<是 | 否>
  建议：<具体改进点，说明异常在哪、应如何修复 | "无">

最终结果：<成功 | 失败>
摘要：<一句话：处理了什么数据，产生了什么产品>
```
