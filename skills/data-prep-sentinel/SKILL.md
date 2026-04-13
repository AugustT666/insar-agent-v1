---
name: data-prep-sentinel
description: >
  Use when Sentinel-1 SAFE, ZIP, or burst inputs are not yet prepared for ISCE2,
  when the user needs grouped SAFE outputs, DEM download, or precise orbit
  download, or when the user wants all Sentinel-1 preprocessing paths prepared
  before running d-insar-isce2 or stack-insar-isce2.
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

## Hard constraints

- Use `insar_download_scene` only when the user still needs to download Sentinel data.
- Use `insar_prepare_sentinel_data` as the main preparation tool.
- Use `insar_download_dem` only through `insar_prepare_sentinel_data` for Sentinel-1 prep.
- Return `safe_root`, `grouped_safe_paths`, `dem_path`, and `orbit_dir`.
- Plugin-controlled logs must land under the selected workspace root `.insar_logs/`.
- Write prepared inputs under the project root:
  - `safe/`
  - `dem/`
  - `orbits/`

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
    dem_output_path="/path/to/project-root/dem/copernicus_30.tif",
    dem_backend="general",  # or "isce2"
    dem_type="version3",    # only for dem_backend="isce2"
    download_orbits=True,
    orbit_dir="/path/to/project-root/orbits",
    resume=True,
)
```

This returns:

- `safe_root`
- `grouped_safe_paths`
- `dem_path`
- `orbit_dir`
- `scene_count`
- `prep_log_path`
- `dem_log_path`
- `orbit_log_path`

Grouped SAFE paths are organized under:

- `safe/s1a_asc_rel014/`
- `safe/s1a_desc_rel079/`
- `safe/s1c_asc_rel014/`

### Step 3 — Hand those paths to ISCE2

- For `d-insar-isce2`, pick two SAFE paths from the same grouped directory and reuse `dem_path` and `orbit_dir`.
- For `stack-insar-isce2`, use one grouped directory as `slc_dir` and reuse `dem_path` and `orbit_dir`.
- For plugin-controlled logs, inspect the workspace root `.insar_logs/` directory first.

## Sentinel-2

Sentinel-2 support is intentionally not implemented in this version.
