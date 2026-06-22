---
name: data-prep
description: >
  This skill should be used when data inputs are not yet prepared before running InSAR processing.
  For NISAR/ISCE3: invoke when RSLC input files or DEM are missing, user says
  "download RSLC", "prepare DEM", "get started with data", mentions Copernicus 30m DEM.
  For Sentinel-1/ISCE2: invoke when SAFE/ZIP/burst inputs are not prepared, user needs
  grouped SAFE outputs, DEM, or precise orbits. Also invoke before d-insar or stack-insar
  workflows whenever input files are not confirmed to exist on disk.
version: 0.1.0
---

# Data Preparation: Unified Router

This skill is the unified entry point for all data preparation workflows. It dispatches
to engine-specific implementations based on the detected or selected engine:

- **NISAR/ISCE3** → `data-prep-nisar` (RSLC + DEM)
- **Sentinel-1/ISCE2** → `data-prep-sentinel` (SAFE/ZIP + DEM + Orbits)

## Role

本 skill 是一个**薄路由层**，它负责：

- 确定当前 engine（nisar 或 sentinel）
- 委派给相应的 engine-specific data-prep 子 skill
- 不直接执行数据下载或准备逻辑

## Capability Matrix

| 模块 | data-prep-nisar | data-prep-sentinel |
|------|----------------|--------------------|
| 场景下载 | `insar_download_rslc` | `insar_download_scene` |
| 场景元数据检查 | `insar_describe_rslc` | `insar_describe_s1` |
| DEM 下载 | `insar_download_dem`（独立 Part B） | `insar_download_dem` 直调或 `insar_prepare_sentinel_data(download_dem=True)` |
| 辅助数据 | N/A（state vectors 在 HDF 内） | orbits via `insar_prepare_sentinel_data(download_orbits=True)` |
| 辅助气象数据 | N/A | `insar_download_era5`；GRIB 写入 `prepare/weather/` |
| 目录约定 | `<output_root>/prepare/rslc/`, `<output_root>/prepare/dem/` | `<output_root>/prepare/safe/`, `<output_root>/prepare/dem/`, `<output_root>/prepare/orbits/`, `<output_root>/prepare/weather/` |
| 服务器资源建议 | `nproc` + `free -h` + `df -h` | 同样先做 `nproc` + `free -h` + `df -h` |

## Unified Workflow

### Step 1 — Determine Engine and Data Source

Ask the user (if not already clear):

1. What engine / data source are you using?
   - **NISAR RSLC** (ISCE3)
   - **Sentinel-1 SAFE/ZIP** (ISCE2)

2. What inputs are already available?
   - RSLC `.h5` URLs or download list (NISAR)
   - SAFE directories or SAFE ZIP files or burst manifest (Sentinel-1)
   - AOI file (`.shp`, `.geojson`, `.kml`) or bbox
   - DEM path (optional; will be prepared if not provided)
   - `output_root` — the single root passed to `insar_create_project`
     (shared prepare inputs land under `<output_root>/prepare/`; reused across runs)

### Step 2 — Delegate to Engine-Specific Skill

#### NISAR Path

If engine is NISAR:

```
Invoke `data-prep-nisar` with:
- RSLC URL list
- AOI path or bbox
- Output directory
- DEM output path (optional)
- Proxy settings (if needed)
- Worker count (default: 8)
```

Expected outputs:
- Downloaded RSLC files at `output_dir`
- DEM at `dem_path` (if prepared)

#### Sentinel-1 Path

If engine is Sentinel-1:

```
Invoke `data-prep-sentinel` with:
- SAFE directories, SAFE ZIPs, or burst manifest
- AOI path or bbox
- project_id (from insar_create_project, so prep joins the pinned run)
- DEM download flag (optional)
- Orbit download flag (optional)
- Proxy settings (if needed)
```

Expected outputs:
- Grouped SAFE paths under `<output_root>/prepare/safe/`
- DEM at `<output_root>/prepare/dem/` (if prepared)
- Orbits at `<output_root>/prepare/orbits/` (if prepared)

Long tasks auto-background: tool returns `{job_id, status:"running", poll, monitor, log_path}`.
Relay the `monitor` command (`tail -f <run>/.insar_agent/progress.log`) to the user.
Poll with `insar_get_job` at minute-level intervals — NOT a tight while-true loop.

### Step 3 — Return Prepared Data Paths

After the engine-specific skill completes, confirm and report back to the user:

- Input file paths (RSLC `.h5`, SAFE directories, etc.)
- DEM path (absolute, verified on disk)
- Auxiliary paths (orbit directory for Sentinel-1, etc.)
- Ready to proceed to next step (d-insar, stack-insar, etc.)

## Hard Constraints

- Always determine the engine before delegating
- Do not attempt to mix NISAR and Sentinel-1 in the same project
- Confirm all file paths exist on disk before returning to caller
- Pass only the minimum required parameters to engine-specific skills

## References

- `data-prep-nisar` — NISAR RSLC + DEM preparation (engine=nisar)
- `data-prep-sentinel` — Sentinel-1 SAFE/ZIP + DEM + Orbits preparation (engine=sentinel)
