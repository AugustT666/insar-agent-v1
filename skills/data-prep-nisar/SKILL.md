---
name: data-prep-nisar
description: >
  Use when NISAR RSLC input files or a DEM are missing before running D-InSAR or
  Stack-InSAR processing. Invoke when the user says "I don't have a DEM", "download
  RSLC", "get data from ASF", "prepare DEM", "extract bounding box", mentions
  Copernicus 30m DEM, ASF Vertex, or asks how to get started with data. Also invoke
  before d-insar-isce3 or stack-insar-isce3 whenever input files are not yet confirmed
  to exist on disk.
---

# Data Preparation: NISAR RSLC + DEM

## Required confirmations (ask only if missing)

- RSLC file paths or target area (needed to derive DEM bounding box)
- Output directory for downloaded data
- Output path for DEM GeoTIFF

## Hard constraints

- Do not edit downloaded RSLC files.
- Use `copernicus_30` as the default DEM source; only change if user specifies otherwise.
- Confirm all file paths exist on the user's machine before handing off to the next skill.

## Standard workflow

### Part A — Download NISAR RSLC data (ASF)

Use the MCP tool `insar_download_rslc` for programmatic remote-crop download.
See `references/rslc-download.md` for full details, pitfalls, and proxy setup.

#### Step A1 — Assemble URL list

Use ASF Vertex (https://search.asf.alaska.edu) to search NISAR L1 RSLC products
covering the target area and time range, then export the download URL list.

- Pass only `.h5` file URLs to the tool; non-RSLC URLs (`_QA_`, `.png`, `.pdf`, `.xml`, `.kml`) are filtered out but including them adds noise.

#### Step A2 — Confirm bbox

**Critical:** do NOT derive the download bbox from `identification/boundingPolygon`
inside the HDF5 — that field stores the **full-frame** extent and is wrong for
already-cropped files. Use the known target study area coordinates instead.
See `references/rslc-download.md` for details.

#### Step A3 — Run download

```python
insar_download_rslc(
    urls=[...],                          # .h5 RSLC URLs from ASF
    bbox=[min_lon, min_lat, max_lon, max_lat],
    output_dir="/path/to/output",
    freq="A",                            # L-band
    proxy=None,                          # default: direct; set if direct is slow
)
```

Prerequisites (install once): `pip install fsspec`
Auth: `~/.netrc` must contain `machine urs.earthdata.nasa.gov login <user> password <pass>`

Expected output filename: `NISAR_L1_PR_RSLC_<cycle>_<track>_…_cropped.h5`

### Part B — Prepare DEM

#### Step B1 — Extract RSLC bounding box

Call the MCP tool with all available RSLC paths:

```
insar_extract_bbox(rslc_paths=["/path/to/rslc1.h5", "/path/to/rslc2.h5", ...])
```

Returns: `{min_lon, min_lat, max_lon, max_lat}` — the union bounding box across all scenes.

> **Warning:** `nisar_bbox_dem.py` reads `identification/boundingPolygon`, which
> reflects the **full-frame** source extent copied during download — not the actual
> cropped SLC pixel extent. Use `insar_extract_bbox` (MCP tool) or the known study
> area coordinates instead.

#### Step B2 — Download Copernicus 30m DEM

Use `ddem.py` with the bounding box from Step B1.
See `references/dem-download.md` for the exact command and options.

Verify the output GeoTIFF covers the full scene extent before proceeding.

## Output requirements (report after completion)

- RSLC data directory and file count
- DEM path, bounding box coordinates, and source used
- Confirmation that all files exist before handing off to the next skill
