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
- ISCE2 conda environment: run `insar_check_env()` first and read `capable.isce2`
  to discover the ACTUAL ISCE2-capable env name on this machine. Do NOT assume it
  is literally named "isce2". Use the user-specified env if provided, otherwise use
  the first entry from `capable.isce2`.

## Execution modes

- Check CLAUDE.md first: if it declares AUTO mode, set `interaction_mode="auto"` immediately without notifying the user.
- Otherwise default to `interaction_mode="interactive"` and tell the user they can switch to auto at any time.
- **interactive**: At Step 4.5, consulting param-advisor (engine=isce2) is required before
  execution; run it, then present the three-choice (defaults / recommended / custom) and wait
  for the user's pick.
- **auto**: At Step 4.5, automatically enter param-advisor (engine=isce2) without asking.
- Consulting the advisor is mandatory in both modes — accepting default parameters afterward is
  fine, but the param-advisor subagent must be invoked first. A PreToolUse gate blocks
  `insar_run_workflow` until the `insar-agent-plugin:param-advisor` subagent has run this session.

## Prerequisites

Before launching processing, confirm these inputs are available:

- grouped SAFE directory
- DEM file
- orbit directory or permission to download orbits through `data-prep`
- ISCE2 conda environment: the discovered ISCE2-capable env from `insar_check_env() capable.isce2`,
  or a user-specified env. Do NOT assume it is literally named "isce2".

If any prerequisite is missing, ask the user or invoke the appropriate preparation skill before creating the project.

---

## Workflow

> **Create the project FIRST, then prepare data.** `insar_create_project` is cheap —
> it just writes `project.json` and pins the run_id. Doing it first means every later
> step (data-prep, DEM, param-advice, stack, MintPy) passes `project_id`
> and joins that one pinned run. If you prepare data before the project exists, the
> prep mints its own run and the task ends up split across two run directories.
> Shared inputs land under `<output_root>/prepare/` — reused if already present (DEM/SAFE not re-downloaded).
> Per-run products land under `<run_root> = <output_root>/<task>_<timestamp>/insar_product/`.

### Step 1 — Create stack project (FIRST — pins the run)

```
insar_create_project(
    engine="isce2",
    workflow="stack",
    output_root=<output_root>,
    name="s1-stack-<region>",
    conda_env=<discovered ISCE2-capable env from insar_check_env capable.isce2, or user-specified env>,
    task_id=<task_id>        # auto-derived; drives the run-root layout
)
```

> Before calling this, run `insar_check_env()` and read `capable.isce2` to get the
> real ISCE2-capable env name on this machine. Do NOT hardcode `conda_env="isce2"`.

**One project, one run — do NOT re-create the project to fix a recoverable error.**
`insar_create_project` pins the run_id once; every later step (data-prep, DEM,
param-advice, workflow) joins that same run when given `project_id`.
Re-creating the project mints a NEW run_id and splits the task across two run directories.

- **Always pass `conda_env` at creation** (using the discovered env name). If you forgot
  it (or the workflow fails with a conda/env-resolution error), do NOT rebuild the project.
  Correct it in place: `insar_run_workflow(project_id, conda_env=<discovered_env>)` updates
  the project's env and re-uses the same run.
- **On any tool failure, take over / retry within the SAME `project_id`** so follow-up
  products stay in the original run. Only create a new project if you are abandoning the run
  entirely (so the failed run can be deleted wholesale).
- Whether the task is "done" is your judgement, based on whether the terminal product exists
  (`mintpy/velocity.h5` for a completed time-series). The plugin does not close runs.

---

### Step 2 — Ensure Sentinel data is prepared (joins the pinned run)

If the user only has raw SAFE ZIP / SAFE / burst inputs, invoke `data-prep`, passing the
same `project_id` from Step 1 so the prepared inputs land under
`<output_root>/prepare/` (shared, reused across runs):

```
data-prep   # with project_id=<project_id>
```

Use one returned grouped SAFE directory plus the returned `dem_path` and `orbit_dir` as the handoff for this skill. For burst-derived SAFE inputs, require `data-prep` to return `isce2_import_validation.status == "passed"`; if it fails, stop and report the failed scene messages/logs instead of running stackSentinel.

---

### Step 3 — Inspect a representative scene

First discover available scenes using the MCP tool:

```python
insar_discover(slc_dir="/mnt/.../safe/s1a_asc_rel014/")
```

Then call describe on the first returned scene path:

```python
insar_describe_s1(zip_path="<first SAFE path from insar_discover result>")
```

Note: relative orbit, polarization, pass direction, bbox. Prefer the `dem_path` and
`orbit_dir` returned by `data-prep`; only ask the user for replacements if they explicitly
want to override them.

---

### Step 4 — Set stack parameters

Mandatory fields (arm this run's param writes once first — ungated, writes a per-run marker keyed by `project_id`; otherwise the PreToolUse gate DENIES every `insar_set_processing_param` below):

```
insar_arm_param_write(project_id, mode="confirm")

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
| `swaths` | `[1,2,3]` | Process the user-selected Sentinel-1 swaths |
| `num_connections` | 3 | Interferogram connections per scene |
| `coregistration` | `"NESD"` | ESD-based; use `"geometry"` if the user chooses geometry-only coregistration |
| `range_looks` / `azimuth_looks` | 9 / 3 | Multilook factors (~90 m pixel) |
| `filter_strength` | 0.5 | Goldstein filter strength |
| `unwrap_method` | 动态发现（见下） | 解缠算法：snaphu（稳健默认）/ icu / 本地其它已装方法 |
| `do_unwrap` | `true` | Set false only when the user explicitly wants to skip unwrapping |

**解缠方法动态发现（勿假定静态枚举）：** 执行前调用 `insar_probe_host()` 取 `unwrap_methods`（本地可用方法及来源/GPU 能力）和 `unwrap_recommended`（默认推荐）。**不要写死只有 snaphu/icu**——新装的 GPU 解缠器（如 phunwrap）会自动出现在列表里。把可用方法呈现给用户选择，默认用 `unwrap_recommended`；具体取舍交 param-advisor 按场景（形变梯度、AOI 大小、相干性、是否有 GPU）推荐。snaphu/icu 为 ISCE2 内置（需运行环境装了 ISCE2，见 `insar_check_env` 的 `capable.isce2`）。

---

### Step 4.5 — Parameter advisor (required before execution)

Consulting the param-advisor is **mandatory before `insar_run_workflow`**, even when the final
choice is to keep default parameters. A PreToolUse gate denies `insar_run_workflow` until the
`insar-agent-plugin:param-advisor` subagent has been invoked this session.

Enter:

```
param-advisor (engine=isce2)
```

This happens **after required fields are set and before `insar_run_workflow`**.
The advisor flow should build a compressed evidence profile from:

- `insar_get_runconfig(format='yaml')`
- `insar_describe_s1(...)` on 1–3 representative scenes from `slc_dir`
- runtime/hardware evidence included by the ISCE2 param-advisor profile, especially current `num_proc`, logical CPUs, memory, and conservative parallelism guidance

It then **must invoke the `insar-agent-plugin:param-advisor` subagent** (via the Task tool,
`subagent_type: insar-agent-plugin:param-advisor`) to generate recommendations — the main
session must not substitute its own advice. Accepted changes are applied via
`insar_set_processing_param` only; choosing the default parameters is a valid outcome, but the
subagent must still have been consulted first.

---

### Step 5 — Run stackSentinel (prepare + execute)

```
insar_run_workflow(project_id=project_id)
```

This calls `stackSentinel.py` which:
1. Reads the SAFE inputs from the selected grouped directory
2. Downloads orbit files if needed
3. Sets work_dir under the run root (`<run_root>/stack`); use the `run_root` the tool returns, don't hand-assemble the path.
4. Executes stack processing inside that work_dir, including generated `run_files`

Returns `job_id`, `log_path`, `pid`, and `run_root`.

> ⚠️ **严禁直接执行 run_files/ 里的任何脚本**，无论串行还是并行。
> ISCE2 topsStack 的 run 文件必须通过 `insar_run_workflow()` 启动；
> 该工具内部通过 `. "$f" || exit 1` 串行 source，保留所有 wait barriers 和环境变量。
> 绕过工具直接 Bash 调用会导致竞态条件、环境变量丢失和不可预知的处理失败。

#### 断点续跑（处理中途失败时）

stackSentinel 有 16 个 run step、可跑十几小时。若在某步（如 run_16 解缠）失败或需调参后续跑，**不要从 run_01 重跑**——用 `resume_from_run` 从指定步骤续跑：

```
insar_run_workflow(project_id=project_id, resume_from_run=16)
```

- `resume_from_run=N`（N≥1）：跳过 `stackSentinel.py` 预处理与 `rm -rf` 清理，**复用已有 run_files/configs/产物**，只执行 run 号 ≥ N 的步骤；并绕过 done/running 去重强制启新 job。
- 前提：该 run 之前已正常跑过、`run_files/` 存在（否则报错 exit 4，提示先不带 `resume_from_run` 跑一次）。
- 调参后续跑：先用 `insar_set_processing_param` 改参（如 `num_proc`），再 `resume_from_run=N` 让新参数从第 N 步生效。
- 只适用于 ISCE2 stack；tops / ISCE3 传入会被拒。
- 想确认从哪步续：看 `<run_root>/logs/<job_id>.log` 里最后的 `[insar-agent] Step: run_NN`。

For multi-hour stack jobs, rely on the background job returned by `insar_run_workflow`. Always return:

- the job id
- the Layer-1 progress monitor command (`tail -f <run_root>/.insar_agent/progress.log`) — relay to user
- the `run_root` (use it for MintPy: `mintpy_work_dir=<run_root>/insar_product/mintpy`)
- the exact `insar_get_job` polling call
- Layer-2 raw engine logs at `<run_root>/insar_product/logs/`

监控以 `insar_get_job(job_id=job_id, project_id=project_id)` 为状态权威源。

**轮询纪律 — Monitor 优先 + 后台 sleep 兜底（自定节奏睡-醒-判断；勿秒级紧凑轮询，会撑爆数据 agent 上下文，长跑会话曾因此崩溃）：** `timeout_ms` 与内部 `sleep` 由 agent 按当前阶段**现场决定**（分钟级，别久到不能及时接管）。

```text
Monitor(description="isce2/stack <job_id>", persistent=false, timeout_ms=<现场定>, command='''
LOG="<insar_run_workflow 返回的 log_path>"; EXIT="${LOG%.log}.exitcode"; prev=""
while true; do
  [ -f "$EXIT" ] && { echo "TERMINAL exitcode=$(cat "$EXIT")"; break; }
  HIT=$(grep -oE "Step: run_[0-9]+|All stack steps completed|Traceback|ERROR|FAILED|Killed" "$LOG" 2>/dev/null | tail -1)
  [ "$HIT" != "$prev" ] && { echo "progress: $HIT"; prev="$HIT"; }
  sleep <现场定>
done''')
```

`timeout_ms`=定时网（到点必醒判断，上限 1h），echo=事件唤醒。**兜底**（Monitor 报错/不可用时回滚）：`Bash(run_in_background=true, command='sleep <现场定>; echo "TICK <job_id>"')`。**每次醒来**（echo/超时/tick 一致）：以上面的 `insar_get_job` 为权威状态 + 进度/日志尾**多信号判断**健康/挂死/报错 → 健康则重新 arm（优先 Monitor，失败回滚 sleep）、异常进失败分类/收口；睡前用 **CST(UTC+8)** 播报下次重检时间。**绝不用永不退出的 `while true` 后台命令**（Monitor 内 break-on-terminal + finite timeout 有界，不在此列）。这与开发 agent 监控隔离会话的机制一致。

Do not execute generated run scripts manually; the MCP workflow owns stack execution.

> Runtime: several hours to days depending on scene count and AOI size.

---

### Step 6 — MintPy time-series analysis

After stack processing completes, **ask the user whether to enable ERA5 tropospheric correction** before launching MintPy (see Step 6.5 below).

Then delegate to the unified **mintpy** skill with `engine=isce2`:

```
Invoke the /insar-agent:mintpy skill
- engine: isce2
- stack_work_dir: <run_root>/insar_product/stack   (returned by insar_run_workflow)
- mintpy_work_dir: <run_root>/insar_product/mintpy  (canonical run-root layout)
- conda_env: the task/user specified MintPy env, or the discovered ISCE2-capable env
  (from `insar_check_env() capable.isce2`) if none was specified; do NOT assume "isce2"
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

### Step 6.5 — Optional: ERA5 tropospheric correction

Ask the user: "Do you want to apply ERA5 tropospheric correction in MintPy?"

If the user says **yes**:

**6.5a — Ensure ERA5 GRIB is available.**
If `data-prep` (Step 2) already downloaded ERA5 for this project, the GRIB files are at
`<output_root>/prepare/weather/ERA5/` and can be reused directly. Otherwise, download now
using the approval-gated flow from `data-prep-sentinel` Step 2.3:

```python
# Preview first (dry_run=True), get user OK, then:
insar_download_era5(
    project_id=<project_id>,
    dates=["20200101", "20200113", ...],   # YYYYMMDD, one per SAR acquisition
    bbox=[W, S, E, N],                     # same AOI used for DEM
    hour="10",                             # ERA5 analysis hour closest to SAR overpass UTC
    dry_run=False,
)
# -> weather_dir = <output_root>/prepare/weather
# -> grib_dir    = <output_root>/prepare/weather/ERA5/
```

If `~/.cdsapirc` is missing the tool returns `{"error": "missing_credentials"}`:
direct the user to <https://cds.climate.copernicus.eu/how-to-api> to register and place
their token in `~/.cdsapirc`.

**6.5b — Run MintPy with the tropo switch enabled.**
Pass `weather_dir` to `insar_run_mintpy_isce2`; MintPy reuses the pre-downloaded GRIB
and enables native pyAPS ERA5 correction (`method = pyaps`):

```python
insar_run_mintpy_isce2(
    mintpy_work_dir="<run_root>/insar_product/mintpy",
    stack_work_dir="<run_root>/insar_product/stack",
    conda_env=<discovered ISCE2-capable env>,
    weather_dir="<output_root>/prepare/weather",   # points at the ERA5 parent dir
    weather_model="ERA5",                           # default; explicit for clarity
)
```

**Expected outputs after a successful ERA5-corrected run:**

| File | Description |
|------|-------------|
| `velocity_ERA5.h5` | ERA5-corrected LOS velocity (m/yr) |
| `timeseries_ERA5.h5` | ERA5-corrected displacement time series |

The export step (`insar_export_geotiff`) automatically emits a before/after/residual
comparison figure when both `velocity.h5` and `velocity_ERA5.h5` are present.

**Post-hoc correction (re-running MintPy on a finished stack):**
If the stack run finished but MintPy was run without ERA5, re-run just the MintPy step
using `resume_from_run` — no need to redo the full stackSentinel processing:

```python
insar_run_workflow(
    project_id=<project_id>,
    resume_from_run=<N>,   # run-file number of the MintPy step; check the log for
                           # the last "Step: run_NN" line before MintPy was launched
)
```

Then immediately call `insar_run_mintpy_isce2` with `weather_dir` as shown in Step 6.5b.

---

### Step 7 — Optional baseline inspection

For ISCE2 stacks, baseline products are typically prepared by topsStack itself under
`<stack_work_dir>/merged/baselines/` and `baselines_txt/`. Do **not** call the
ISCE3-only `insar_plot_baseline(network_dir=...)` tool here.

If the user wants to inspect baseline connectivity, point them to the generated
baseline text products inside the stack work directory or continue through the unified
`mintpy` skill, which treats ISCE2 baseline plotting as optional.

---

### Step 8 — Export results

```
insar_list_outputs(project_id=project_id)

# Export velocity map — velocity.h5 is at <run_root>/insar_product/mintpy/velocity.h5
insar_export_geotiff(
    h5_path="<run_root>/insar_product/mintpy/velocity.h5",
    output_dir="<run_root>/insar_product/exports"
)
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
- Do not mix ascending and descending pass scenes in the same stack.
- Processing must use the conda environment configured on the project and is launched by the MCP workflow tool.
- Never directly execute run_files/ scripts (via Bash or any other means). All ISCE2 stack execution must go through `insar_run_workflow()`.
