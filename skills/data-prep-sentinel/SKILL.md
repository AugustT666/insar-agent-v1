---
name: data-prep-sentinel
description: >
  This skill should be used when Sentinel-1 SAFE, ZIP, or burst inputs are not yet
  prepared for ISCE2, when the user needs grouped SAFE outputs, DEM download, or precise orbit
  download, or when the user wants all Sentinel-1 preprocessing paths prepared
  before running d-insar-isce2 or stack-insar-isce2.
version: 0.1.0
---

# Data Preparation: Sentinel-1 SAFE, DEM, and Orbits

## Scope

- This skill is the unified Sentinel-1 data preparation entry for ISCE2.
- It prepares grouped SAFE paths, DEM, and precise orbit files.
- It does not decide stack grouping beyond factual SAFE grouping by track directory.
- Sentinel-2 is not implemented here.

## What to check first

- Existing SAFE directories or SAFE ZIP files
- Local burst files plus a manifest, if the user is working from ASF bursts
- Output `output_root` (the single root passed to `insar_create_project`)
- AOI file or bbox for DEM download
- Whether DEM download is needed
- Whether precise orbit download is needed
- Download URLs and proxy settings, if scene download is still needed

## Output layout

Shared prepare inputs land under `<output_root>/prepare/` — reused across runs:
- `<output_root>/prepare/safe/s1a_asc_rel014/` etc.
- `<output_root>/prepare/dem/`
- `<output_root>/prepare/orbits/`
- `<output_root>/prepare/weather/ERA5/` (optional; ERA5 GRIB for tropospheric correction)

Per-run products land under `<run_root> = <output_root>/<task>_<timestamp>`:
- `<run_root>/insar_product/<subdir>/`
- `<run_root>/.insar_agent/progress.log`  ← Layer-1 concise progress (relay to user)
- `<run_root>/insar_product/logs/`        ← Layer-2 raw engine output

## Capability Matrix

| 模块 | 当前做法 | 备注 |
|------|---------|------|
| 场景下载 | `insar_download_scene` | 仅在用户仍需下载 Sentinel 数据时使用 |
| 场景元数据检查 | `insar_describe_s1` | 作为代表场景检查步骤 |
| DEM 下载 | `insar_prepare_sentinel_data(download_dem=True)` 或 `insar_download_dem` | 允许只准备 DEM |
| 辅助数据 | `insar_prepare_sentinel_data(download_orbits=True)` | 轨道文件写入 `prepare/orbits/` |
| 辅助气象数据 | `insar_download_era5` | ERA5 GRIB 写入 `prepare/weather/ERA5/`，供 MintPy 对流层校正复用 |
| 目录约定 | `prepare/safe/`, `prepare/dem/`, `prepare/orbits/`, `prepare/weather/` | 全部位于 `output_root` 之下，跨 run 共享 |
| 服务器资源建议 | `insar_check_env` | 不使用 shell；仅通过 MCP 环境报告判断能力 |

## Hard constraints

- Use `insar_download_scene` only when the user still needs to download Sentinel data.
- Use `insar_prepare_sentinel_data` as the main preparation tool.
- Use `insar_download_dem` only through `insar_prepare_sentinel_data` for Sentinel-1 prep.
- Return `safe_root`, `grouped_safe_paths`, `dem_path`, and `orbit_dir`.
- Layer-1 concise progress log at `<run_root>/.insar_agent/progress.log` — relay `monitor` command to user.
- Layer-2 raw logs at `<run_root>/insar_product/logs/`.
- Write prepared inputs under `<output_root>/prepare/`:
  - `prepare/safe/`
  - `prepare/dem/`
  - `prepare/orbits/`
- For IntegrationTest workspace tasks, pass existing burst scene directories via
  `source_paths` directly. Do not create helper files such as
  `burst_manifest.txt` in `workspace/<task_id>/`; task-root children other than
  `.insar_agent`, `insar_product`, and `sessions` are treated as
  artifact pollution.

## Standard workflow

### Step 1 — Download SAFE/ZIP inputs if needed

If the user provides direct download URLs:

```python
insar_download_scene(
    urls=["https://.../S1A_IW_SLC__...zip", "..."],
    output_dir="/path/to/downloads",
    n_workers=2,
    proxy=None,
)
```

When the user has no URLs, discover them first with `insar_search` (turns an
AOI + time window into a downloadable list; removes the manual ASF Vertex step):

```python
insar_search(
    platform="sentinel1",
    aoi_path="/path/to/study_area.shp",        # or bbox=[W, S, E, N]
    start="2025-10-01", end="2026-01-06",
    flight_direction="ASCENDING",               # match the target stack geometry
    relative_orbit=14,                          # relative orbit (path) to stack
    polarizations=["VV", "VH"],
    existing_root="/path/to/sentinel/bursts",   # flags on-disk scenes -> fill only the gap
)
# -> {acquisitions, by_rel_dir, urls, missing_by_rel_dir, missing_urls, ...}
```

Feed `missing_by_rel_dir` to `insar_download_scene` once per rel-dir
(`output_dir=<bursts>/<rel_dir>`); each burst URL path reproduces the
`<scene>/IW*/{VV,VH}/<idx>.{tiff,xml}` layout automatically.

**Download reliability (ASF burst host):**
- One satellite on one relative orbit is one stack. Do not merge S1A and S1C
  bursts into the same InSAR stack — each satellite's AOI-intersecting bursts
  already fully cover the AOI on their own (verify with the burst footprints).
- Each burst download runs a full Earthdata URS OAuth; high concurrency gets
  throttled and returns an HTML login page (HTTP 200). Keep `n_workers` low
  (≈2) for `sentinel1-burst.asf.alaska.edu`. `insar_download_scene` now detects
  a login page / truncated file and retries with backoff, but low concurrency
  avoids the throttle up front.
- If a proxy resets TLS to the burst host (`SSL_ERROR_SYSCALL`) or corrupts
  payloads, pass `proxy="direct"` to bypass it, or `proxy="http://host:port"`
  to route through a clean/faster proxy.

### Step 1.5 — Environment check when needed

If environment status is missing, unclear, or blocking Sentinel preparation, use the MCP environment report:

```python
insar_check_env()
```

Use that result to decide whether required conda environments and project skills are available. Do not require this check when the task already supplies a valid environment context.

### Step 2 — Prepare grouped SAFE, DEM, and orbits

```python
insar_prepare_sentinel_data(
    project_id=<project_id>,   # pass project_id from insar_create_project
    aoi_path="/path/to/study_area.shp",  # or bbox=[min_lon, min_lat, max_lon, max_lat]
    source_paths=[
        "/path/to/S1A_IW_SLC__...zip",
        "/path/to/S1C_IW_SLC__...SAFE",
    ],
    burst_manifest="/path/to/burst_manifest.txt",  # only for burst input
    download_dem=True,
    dem_output_path="<output_root>/prepare/dem/isce2.dem.wgs84",
    dem_backend="isce2",    # required default for downstream d-insar-isce2 / stack-insar-isce2
    dem_type="version3",    # only for dem_backend="isce2"
    download_orbits=True,
    orbit_dir="<output_root>/prepare/orbits",
    validate_isce2_import=True,  # required for burst_manifest inputs
    resume=True,
    background=True,   # 多景 stack 必须为 True;返回 job 后睡醒式轮询(见下方说明)
)
```

> **多景 stack（≥2 景）或含 DEM/轨道下载时自动后台运行（关键）。** 31 景级的 SAFE 合成 + DEM + 轨道
> 同步跑会超过 MCP 客户端单次工具调用上限(~600s)而超时。长任务立即返回
> `{job_id, status:"running", poll, monitor, log_path}`,真正的 prep 在后台 detached 进程里跑;之后按
> **自定节奏睡-醒轮询**(间隔分钟级,**勿秒级紧凑 loop、勿 `while true`**;data-prep 通常几分钟完成,**每次唤醒间隔 ≤5 分钟、严禁排小时级 ScheduleWakeup**——否则任务早已完成你还在睡):
>
> ```python
> insar_get_job(job_id=<job_id>, project_id=<project_id>)
> ```
>
> 直到 `status` 为 `done`(再从结果/磁盘读 `safe_root`/`grouped_safe_paths`/`dem_path`/`orbit_dir`)
> 或 `failed`(读 `log_path` 排查)。返回里还带 `monitor` 命令(`tail -f <run>/.insar_agent/progress.log`)——
> **务必把它转告用户**,让用户能在自己终端实时看后台处理进度（Layer-1 concise progress）。
> 仅单对/小量 prep 可同步跑（无后台）。

For Sentinel workflows that will feed `d-insar-isce2` or `stack-insar-isce2`,
use `dem_backend="isce2"` and an ISCE2 DEM output such as
`isce2.dem.wgs84`. Use `dem_backend="general"` only when the downstream
workflow explicitly needs a GeoTIFF DEM instead of ISCE2 DEM sidecars.

For `burst_manifest` inputs, treat `isce2_import_validation.status != "passed"` as a data-prep failure and report each failed scene's `scene_id`, `safe_path`, `message`, and `log_path` before running D-InSAR or stack workflows.

This returns:

- `safe_root`
- `grouped_safe_paths`
- `dem_path`
- `orbit_dir`
- `scene_count`
- `prep_log_path`
- `dem_log_path`
- `orbit_log_path`
- `isce2_import_validation` when `validate_isce2_import=True`

Grouped SAFE paths are organized under `<output_root>/prepare/`:

- `prepare/safe/s1a_asc_rel014/`
- `prepare/safe/s1a_desc_rel079/`
- `prepare/safe/s1c_asc_rel014/`

### Step 2.3 — Download ERA5 weather data (optional, approval-gated)

If the user intends to apply ERA5 tropospheric correction in MintPy, download ERA5 GRIB files
now so they are cached and MintPy can reuse them without re-downloading at correction time.

**Step 2.3a — Preview the request (dry run):**

```python
insar_download_era5(
    project_id=<project_id>,
    dates=["20200101", "20200113", ...],   # YYYYMMDD strings, one per SAR acquisition
    bbox=[W, S, E, N],                     # same AOI/bbox used for DEM download
    hour="10",                             # ERA5 analysis hour closest to SAR overpass UTC
    dry_run=True,
)
```

This returns a plan — number of CDS requests, expected GRIB file paths under
`prepare/weather/ERA5/`, and the rounded `snwe` — without contacting the CDS API.
Present the plan to the user and **wait for confirmation** before proceeding.

**Step 2.3b — Download (after user approval):**

```python
insar_download_era5(
    project_id=<project_id>,
    dates=["20200101", "20200113", ...],
    bbox=[W, S, E, N],
    hour="10",
    dry_run=False,
)
```

GRIB files land under `<output_root>/prepare/weather/ERA5/`, named exactly as MintPy expects.
MintPy will reuse the pre-downloaded files and skip re-downloading at correction time.

**Credential check:** If `~/.cdsapirc` is missing, the tool returns
`{"error": "missing_credentials", ...}`. The user must register at
<https://cds.climate.copernicus.eu/how-to-api>, accept the ERA5 licence, and place
their CDS token in `~/.cdsapirc` before retrying.

**Background download:** For many dates (>30), pass `background=True` and poll with
`insar_get_job(job_id=<job_id>, project_id=<project_id>)` at minute-level intervals.

---

### Step 2.5 — Inspect representative scene

Before handing Sentinel inputs to `d-insar-isce2` or `stack-insar-isce2`, inspect one representative scene:

```python
insar_describe_s1(zip_path="/path/to/S1A_IW_SLC__...SAFE")
```

Capture at least: relative orbit, pass direction, polarization, acquisition time, and bbox.

### Alternative — DEM only

If the Sentinel scenes are already organized and the only missing asset is a DEM, you may skip
`insar_prepare_sentinel_data` and fetch the DEM directly:

```python
insar_download_dem(
    output_path="<output_root>/prepare/dem/copernicus_30.tif",
    aoi_path="/path/to/study_area.shp",  # or bbox=[min_lon, min_lat, max_lon, max_lat]
)
```

Use the same AOI / bbox that will be passed to the ISCE2 workflow.

### Step 3 — Hand those paths to ISCE2

- For `d-insar-isce2`, pick two SAFE paths from the same grouped directory and reuse `dem_path` and `orbit_dir`.
- For `stack-insar-isce2`, use one grouped directory as `slc_dir` and reuse `dem_path` and `orbit_dir`.
- Layer-1 concise progress: `<run_root>/.insar_agent/progress.log` (relay `monitor` to user).
- Layer-2 raw logs: `<run_root>/insar_product/logs/`.

## Sentinel-2

Sentinel-2 support is intentionally not implemented in this version.
