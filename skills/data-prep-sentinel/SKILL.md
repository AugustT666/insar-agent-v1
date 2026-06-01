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
- Output `project_root`
- AOI file or bbox for DEM download
- Whether DEM download is needed
- Whether precise orbit download is needed
- Download URLs and proxy settings, if scene download is still needed

## Capability Matrix

| 模块 | 当前做法 | 备注 |
|------|---------|------|
| 场景下载 | `insar_download_scene` | 仅在用户仍需下载 Sentinel 数据时使用 |
| 场景元数据检查 | `insar_describe_s1` | 作为代表场景检查步骤 |
| DEM 下载 | `insar_prepare_sentinel_data(download_dem=True)` 或 `insar_download_dem` | 允许只准备 DEM |
| 辅助数据 | `insar_prepare_sentinel_data(download_orbits=True)` | 轨道文件写入 `orbits/` |
| 目录约定 | `safe/`, `dem/`, `orbits/` | 全部位于 `project_root` 之下 |
| 服务器资源建议 | `insar_check_env` | 不使用 shell；仅通过 MCP 环境报告判断能力 |

## Hard constraints

- Use `insar_download_scene` only when the user still needs to download Sentinel data.
- Use `insar_prepare_sentinel_data` as the main preparation tool.
- Use `insar_download_dem` only through `insar_prepare_sentinel_data` for Sentinel-1 prep.
- Return `safe_root`, `grouped_safe_paths`, `dem_path`, and `orbit_dir`.
- Plugin-controlled logs land under the run's `logs/` directory (`<run_root>/logs/`).
- Write prepared inputs under the project root:
  - `safe/`
  - `dem/`
  - `orbits/`
- For IntegrationTest workspace tasks, pass existing burst scene directories via
  `source_paths` directly. Do not create helper files such as
  `burst_manifest.txt` in `workspace/<task_id>/`; task-root children other than
  `.insar_agent`, `outputs`, and `sessions` are treated as
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

### Step 1.5 — Environment check when needed

If environment status is missing, unclear, or blocking Sentinel preparation, use the MCP environment report:

```python
insar_check_env()
```

Use that result to decide whether required conda environments and project skills are available. Do not require this check when the task already supplies a valid environment context.

### Step 2 — Prepare grouped SAFE, DEM, and orbits

```python
insar_prepare_sentinel_data(
    project_root="/path/to/project-root",
    aoi_path="/path/to/study_area.shp",  # or bbox=[min_lon, min_lat, max_lon, max_lat]
    source_paths=[
        "/path/to/S1A_IW_SLC__...zip",
        "/path/to/S1C_IW_SLC__...SAFE",
    ],
    burst_manifest="/path/to/burst_manifest.txt",  # only for burst input
    download_dem=True,
    dem_output_path="/path/to/project-root/dem/isce2.dem.wgs84",
    dem_backend="isce2",    # required default for downstream d-insar-isce2 / stack-insar-isce2
    dem_type="version3",    # only for dem_backend="isce2"
    download_orbits=True,
    orbit_dir="/path/to/project-root/orbits",
    validate_isce2_import=True,  # required for burst_manifest inputs
    resume=True,
)
```

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

Grouped SAFE paths are organized under:

- `safe/s1a_asc_rel014/`
- `safe/s1a_desc_rel079/`
- `safe/s1c_asc_rel014/`

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
    output_path="/path/to/project-root/dem/copernicus_30.tif",
    aoi_path="/path/to/study_area.shp",  # or bbox=[min_lon, min_lat, max_lon, max_lat]
)
```

Use the same AOI / bbox that will be passed to the ISCE2 workflow.

### Step 3 — Hand those paths to ISCE2

- For `d-insar-isce2`, pick two SAFE paths from the same grouped directory and reuse `dem_path` and `orbit_dir`.
- For `stack-insar-isce2`, use one grouped directory as `slc_dir` and reuse `dem_path` and `orbit_dir`.
- For plugin-controlled logs, inspect the run's `logs/` directory (`<run_root>/logs/`).

## Sentinel-2

Sentinel-2 support is intentionally not implemented in this version.
