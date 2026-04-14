---
name: data-prep
description: >
  Use when data inputs are not yet prepared before running InSAR processing.
  For NISAR/ISCE3: invoke when RSLC input files or DEM are missing, user says
  "download RSLC", "prepare DEM", "get started with data", mentions Copernicus 30m DEM.
  For Sentinel-1/ISCE2: invoke when SAFE/ZIP/burst inputs are not prepared, user needs
  grouped SAFE outputs, DEM, or precise orbits. Also invoke before d-insar or stack-insar
  workflows whenever input files are not confirmed to exist on disk.
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
   - Workspace / project root directory

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
- Project root
- DEM download flag (optional)
- Orbit download flag (optional)
- Proxy settings (if needed)
```

Expected outputs:
- Grouped SAFE paths under `safe_root`
- DEM at `dem_path` (if prepared)
- Orbits at `orbit_dir` (if prepared)

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
