---
name: d-insar-isce2
description: >
  This skill should be used when the user needs Sentinel-1 single-pair D-InSAR
  processing with ISCE2 (topsApp.py).
  Invoke when the user wants to process a pair of Sentinel-1 scenes to produce
  an interferogram, coherence map, or unwrapped displacement.
  Triggers on: "S1 interferogram", "Sentinel-1 DInSAR", "topsApp", "isce2 process",
  "S1 pair", "sentinel deformation", "C-band interferogram".
  If Sentinel SAFE/ZIP inputs are not already organized into grouped SAFE paths,
  invoke `data-prep` first.
version: 0.1.0
---

# Sentinel-1 D-InSAR with ISCE2 (Single Pair)

## Required confirmations (ask only if missing)

- Reference and secondary Sentinel-1 SAFE paths (or SAFE ZIP files)
- DEM path (`.tif`) — if missing, invoke `data-prep` first
- Precise orbit directory (`.orb` files) — if missing, can be downloaded via `data-prep`
- Workspace / output directory (absolute path)
- Conda environment name — run `insar_check_env()` first and read `capable.isce2` to
  discover the ACTUAL ISCE2-capable env name on this machine. Do NOT assume the env is
  literally named "isce2"; use the discovered name or a user-specified override.

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

Run `insar_check_env()` first and read `capable.isce2` to get the real ISCE2-capable env name.
Use the task/user specified ISCE2 environment if provided, otherwise use the first entry from
`capable.isce2`. Do NOT assume the env is literally named "isce2". If environment status is
missing, unclear, or a tool reports an environment-related error, use `insar_check_env()` or
invoke `env-setup` before retrying.

---

## Workflow

### Step 1 — Ensure Sentinel data is prepared

If the user only has raw SAFE ZIP / SAFE / burst inputs, stop and invoke:

```
data-prep
```

Select `engine=sentinel` and use the returned `grouped_safe_paths`, `dem_path`, and `orbit_dir` as the handoff.

---

### Step 2 — Inspect scene metadata

For the two selected SAFE / ZIP inputs, check key parameters before processing:

```python
insar_describe_s1(zip_path="/mnt/.../safe/s1a_asc_rel014/S1A_IW_SLC__...SAFE")
```

Confirm:
- Same `relative_orbit` for reference and secondary (required for InSAR)
- Same `mode` (IW)
- Compatible `polarizations` (e.g. both contain VV)
- `pass_direction` is consistent
- Temporal baseline is reasonable (6–48 days typical for S1)

---

### Step 3 — Reuse prepared DEM and orbits

Prefer the `dem_path` and `orbit_dir` returned by `data-prep`.
Only ask the user for replacements if they explicitly want to override them.
The user still needs to provide:

- `workspace_root`

---

### Step 4 — Create project

```
insar_create_project(
    engine="isce2",
    workflow="tops",
    output_root=<output_root>,
    name="s1-dinsar-<region>-<date>",
    conda_env=<discovered ISCE2-capable env from insar_check_env capable.isce2, or user-specified env>,
    task_id=<task_id>        # auto-derived; drives the run-root layout
)
```

> Before calling this, run `insar_check_env()` and read `capable.isce2` to get the
> real ISCE2-capable env name on this machine. Do NOT hardcode `conda_env="isce2"`.

**One project, one run.** The run_id is pinned at creation; all later steps join it. Do NOT
re-create the project to fix a recoverable error (that mints a new run). If the workflow
fails on a conda/env problem, correct it in place: `insar_run_workflow(project_id,
conda_env=<discovered_env>)`. On any failure, retry within the same `project_id`; create a new project
only when abandoning the run entirely.

Returns `project_id` and `required_fields` list.
Per-run products land under `<run_root> = <output_root>/<task>_<timestamp>/insar_product/`.
Agent state and Layer-1 progress log: `<run_root>/.insar_agent/progress.log`.
Raw engine logs (Layer-2): `<run_root>/insar_product/logs/`.

---

### Step 5 — Set required parameters

Set all `required_fields` using `insar_set_processing_param`. Arm this run's param writes once first (ungated; writes a per-run marker keyed by `project_id`) — otherwise the PreToolUse gate DENIES every `insar_set_processing_param` below. Mandatory fields:

```
insar_arm_param_write(project_id, mode="confirm")

insar_set_processing_param(project_id, key="reference_safe",
    value="/mnt/.../safe/s1a_asc_rel014/S1A_IW_SLC__...SAFE", justification="reference scene path")

insar_set_processing_param(project_id, key="secondary_safe",
    value="/mnt/.../safe/s1a_asc_rel014/S1A_IW_SLC__...SAFE", justification="secondary scene path")

insar_set_processing_param(project_id, key="orbit_dir",
    value="/mnt/.../orbits", justification="prepared POEORB orbit files directory")

insar_set_processing_param(project_id, key="dem_file",
    value="/mnt/.../dem/dem.tif", justification="prepared DEM path from data-prep")
```

Optional parameters (change only if needed):

| Key | Default | When to change |
|-----|---------|---------------|
| `bbox` | None (full swath) | Limit to AOI: `[S, N, W, E]` |
| `swaths` | `[1,2,3]` | Process subset, e.g. `[2]` for speed |
| `polarization` | `"vv"` | Use `"vh"` for cross-pol applications |
| `range_looks` / `azimuth_looks` | 20 / 4 | Adjust for different resolution |
| `filter_strength` | 0.5 | 0 = no filter, 1 = max filter |
| `do_esd` | True | Set False if ESD fails in low-coherence |
| `unwrap_method` | 动态发现（见下） | snaphu（稳健默认）/ icu（更快欠稳健）/ 本地其它已装方法 |

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

This happens **after required path fields are set and before `insar_run_workflow`**.
The advisor flow must build a metadata-first evidence profile using:

- `insar_describe_s1(reference_safe)`
- `insar_describe_s1(secondary_safe)`
- `insar_get_runconfig(format='yaml')`

It then **must invoke the `insar-agent-plugin:param-advisor` subagent** (via the Task tool,
`subagent_type: insar-agent-plugin:param-advisor`) to generate recommendations — the main
session must not substitute its own advice. Accepted changes are applied via
`insar_set_processing_param` only; choosing the default parameters is a valid outcome, but the
subagent must still have been consulted first.

---

### Step 5 — Run workflow

```
insar_run_workflow(project_id=project_id)
```

ISCE2 will:
1. Generate `configs/topsApp.xml` from project parameters
2. Sets work_dir under the run root; use the `run_root` the tool returns, don't hand-assemble the path.
3. Launch `topsApp.py` in the `isce2` conda env with work_dir as the working directory
4. Return `job_id`, `log_path`, `pid`, and `run_root`

ISCE2 native outputs (`merged/`, `geom_reference/`, `fine_interferogram/`, etc.) land directly inside `run_root`.

---

### Step 6 — Monitor progress

```
insar_get_job(job_id=job_id, project_id=project_id)
```

Typical runtime: 30–120 minutes depending on scene size and number of swaths.
Each response includes `progress` (Layer-1 concise tail from `.insar_agent/progress.log`).

**轮询纪律 — Monitor 优先 + 后台 sleep 兜底（自定节奏睡-醒-判断；勿秒级紧凑轮询，会撑爆上下文）：** `timeout_ms` 与内部 `sleep` 由 agent 按当前阶段**现场决定**（分钟级，别久到不能及时接管）。

```text
Monitor(description="isce2/tops <job_id>", persistent=false, timeout_ms=<现场定>, command='''
LOG="<insar_run_workflow 返回的 log_path>"; EXIT="${LOG%.log}.exitcode"; prev=""
while true; do
  [ -f "$EXIT" ] && { echo "TERMINAL exitcode=$(cat "$EXIT")"; break; }
  HIT=$(grep -oE "Running |filt_topophase|geocod|Traceback|ERROR|FAILED|Killed" "$LOG" 2>/dev/null | tail -1)
  [ "$HIT" != "$prev" ] && { echo "progress: $HIT"; prev="$HIT"; }
  sleep <现场定>
done''')
```

`timeout_ms`=定时网（到点必醒判断，上限 1h），echo=事件唤醒。**兜底**（Monitor 报错时回滚）：`Bash(run_in_background=true, command='sleep <现场定>; echo "TICK <job_id>"')`。**每次醒来**（echo/超时/tick）：以 `insar_get_job(job_id=job_id, project_id=project_id)` 为权威状态 + 进度/日志尾**多信号判断**健康/挂死/报错 → 健康则重新 arm（优先 Monitor，失败回滚 sleep）、异常进收口；睡前用 **CST(UTC+8)** 播报下次重检时间。**绝不用永不退出的 `while true` 后台命令**（Monitor 内 break-on-terminal + finite timeout 有界，不在此列）。

Relay the `monitor` command from the `insar_run_workflow` response to the user:
```bash
tail -f <run_root>/.insar_agent/progress.log
```
This is the Layer-1 concise progress log (what the user watches in their terminal).
Layer-2 raw ISCE2 engine logs are at `<run_root>/insar_product/logs/`.

---

### Step 7 — Inspect outputs

```
insar_list_outputs(project_id=project_id)
```

Key output files (located under `<run_root>/` returned by `insar_run_workflow`):

| File | Description |
|------|-------------|
| `merged/filt_topophase.unw.geo` | Geocoded unwrapped interferogram |
| `merged/filt_topophase.unw.geo.vrt` | VRT for GIS viewing |
| `merged/phsig.cor.geo` | Geocoded coherence |
| `merged/filt_topophase.flat.geo` | Flat-Earth corrected wrapped phase |
| `merged/dem.crop` | Cropped DEM used in processing |

---

## Hard constraints

- Reference and secondary must be from the same relative orbit (same track).
- Do NOT mix ascending and descending pass scenes.
- If raw Sentinel inputs are not yet organized, always go through `data-prep` first with `engine=sentinel`.
- `data-prep` is expected to prepare grouped SAFE paths, `dem_path`, and `orbit_dir`.
- `orbit_dir` must contain the correct POEORB files. ISCE2 downloads them
  automatically if `do_download_orbit` is enabled and internet is available.
- Processing must run inside `conda run -n <discovered_isce2_env>` — never run `topsApp.py`
  directly without the correct ISCE2 environment active. Discover the env name via
  `insar_check_env() capable.isce2`; do NOT assume it is literally named "isce2".
- `insar_run_workflow` generates `topsApp.xml` automatically from project params.
  Do not edit the XML manually — use `insar_set_processing_param` instead.

---

## Troubleshooting

### Orbit Download Timeouts

**Symptom**: `RETRY attempt X after transient failure: Connection timeout` appears repeatedly in logs.

**Cause**: Network connectivity issues reaching `dataspace.copernicus.eu` (ESA Dataspace service).

**Solutions**:
1. **Auto-Retry (Default)**: The MCP tool automatically retries orbit downloads with exponential backoff (3 attempts, 2–8 second delays). Check logs to see if the retry succeeds.
2. **Pre-Download Orbits**: Use `data-prep` with `engine=sentinel` and `download_orbits=True` before workflow launch.
3. **Provide Orbit Directory**: If orbits are already cached, set `orbit_dir` to the directory containing `.EOF` files and omit `download_orbits`.
4. **Check Credentials**: Verify dataspace.copernicus.eu credentials are correct (in `~/.netrc` or via `orbit_username`/`orbit_password`).

### ESD Failures in Low-Coherence Areas

**Symptom**: `EstimateSlant2GroundRange (ESD) failed` appears in logs, but interferogram generation succeeds.

**Cause**: Enhanced Spectral Diversity (ESD) is sensitive to low coherence (< 0.3) in forests, water, or complex terrain.

**Solutions**:
1. **Disable ESD**: Set `do_esd=False` in Step 5 (optional parameters).
2. **Increase Filter Strength**: Set `filter_strength=0.8` to pre-filter phase before ESD.
3. **Reduce Swaths**: Process only high-coherence swaths (e.g., `swaths=[1]` instead of `[1,2,3]`).

### Unwrapping Failures (SNAPHU)

**Symptom**: SNAPHU phase unwrapper crashes or produces unrealistic displacement fields.

**Cause**: Often caused by wrapped-phase discontinuities in low-coherence regions or incorrect cost function parameters.

**Solutions**:
1. **Use ICU Instead**: Set `unwrap_method="icu"` for faster, albeit less robust, unwrapping.
2. **Reduce Looks**: Increase `azimuth_looks` to 6 or higher to smooth phase before unwrapping.
3. **Increase Filter**: Set `filter_strength=0.8–1.0` to maximize coherence before unwrapping.
4. **Subset Swaths**: Try `swaths=[2]` to isolate a single high-coherence swath.

### Low Coherence Output

**Symptom**: Coherence map (`.cor.geo`) is predominantly < 0.3, making phase unreliable.

**Cause**: Temporal decorrelation (scenes too far apart), geometric decorrelation (steep topography), or volumetric scattering (dense vegetation).

**Solutions**:
1. **Check Temporal Baseline**: Run `insar_describe_s1` on both scenes and verify baseline is 6–48 days (Sentinel-1 typical).
2. **Check Baseline Direction**: Perpendicular baseline > 150 m can amplify geometric decorrelation. Choose scenes with smaller perpendicular separation.
3. **Subset to Coherent Regions**: Use `bbox` parameter to focus on stable areas (water bodies, urban areas, bare rock).
4. **Use Ascending + Descending Pair**: Combine ascending and descending geometries in a stack (use `stack-insar-isce2` instead) to decorrelate topographic effects.

### Memory or Compute Constraints

**Symptom**: Process hangs, OOM kill, or extreme runtime (> 4 hours).

**Cause**: Processing full-resolution multi-swath interferogram uses 40–80 GB RAM; large datasets or low-spec hardware.

**Solutions**:
1. **Reduce Looks Aggressively**: Set `azimuth_looks=8`, `range_looks=40` to downsample.
2. **Limit Swaths**: Use `swaths=[2]` instead of `[1,2,3]`.
3. **Use Smaller AOI**: Set `bbox=[lon_min, lat_min, lon_max, lat_max]` to clip to region of interest.
4. **Increase System Swap**: If out of RAM, temporarily increase swap space, but note processing will be very slow.

### No Output Files Generated

**Symptom**: `insar_list_outputs` returns empty list; no `merged/` directory created.

**Cause**: `topsApp.py` failed early (before merging step) or was killed.

**Solutions**:
1. **Check Job Status**: Run `insar_get_job(job_id=...)` to see if job is `failed`, `timeout`, or still `running`.
2. **Inspect Raw Logs**: View full topsApp output at Layer-2 log path:
   ```bash
   tail -200 <run_root>/insar_product/logs/isce2_*.log
   ```
3. **Validate Inputs**: Verify both SAFE/ZIP paths exist and contain valid manifest files:
   ```bash
   unzip -l <safe.zip> | grep manifest.safe
   ```
4. **Check DEM Coverage**: Ensure DEM covers the interferogram AOI; run `insar_describe_s1` to see scene bounds.

### XML Generation or Parameter Errors

**Symptom**: Error message mentions `topsApp.xml` validation or `<parameter> not recognized`.

**Cause**: Project parameters do not conform to ISCE2 `topsApp` XML schema, or a path is invalid.

**Solutions**:
1. **Re-validate Paths**: Ensure `reference_safe`, `secondary_safe`, `dem_file`, `orbit_dir` all exist and are readable.
2. **Check Parameter Types**: Confirm numeric parameters (`range_looks`, `azimuth_looks`) are integers, not strings.
3. **Use Default Parameters**: If unsure, omit optional parameters and use defaults in Step 5.

---

## Expected Runtimes

For reference (Intel i7 with 32 GB RAM, NVMe storage):

| Swaths | Resolution | Typical Runtime |
|--------|------------|-----------------|
| 1      | 2-looks    | 15–30 min       |
| 2      | 2-looks    | 30–60 min       |
| 3      | 2-looks    | 60–120 min      |
| 3      | 1-looks    | 150–240 min     |

---

## Log Inspection

Two-layer logging:
- **Layer-1 concise progress** at `<run_root>/.insar_agent/progress.log` — relay `monitor` command to user.
- **Layer-2 raw engine output** at `<run_root>/insar_product/logs/`:
  - `isce2_<job_id>.log` — Main ISCE2 process output (text format)
  - `sentinel_prep_<job_id>.log` — Data preparation log (if data-prep was used)
  - `sentinel_orbit_<job_id>.log` — Orbit download log with retry messages

To watch Layer-1 live (relay this to the user):
```bash
tail -f <run_root>/.insar_agent/progress.log
```

To inspect raw Layer-2 ISCE2 output:
```bash
tail -200 <run_root>/insar_product/logs/isce2_*.log
```

To search for error patterns in Layer-2:
```bash
grep -i "error\|failed\|exception" <run_root>/insar_product/logs/*.log
```
