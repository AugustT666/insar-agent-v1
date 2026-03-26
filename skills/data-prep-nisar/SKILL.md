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

> A programmatic ASF download tool is not yet available. Guide the user through the
> manual steps below.

1. Direct the user to ASF Vertex: https://search.asf.alaska.edu
2. Search for NISAR L1 RSLC products covering the target area and time range.
3. Submit a bulk download order; download `.h5` files to a local directory.

Expected filename pattern: `NISAR_L1_PR_RSLC_<track>_<date>_…_cropped.h5`

### Part B — Prepare DEM

#### Step B1 — Extract RSLC bounding box

Call the MCP tool with all available RSLC paths:

```
insar_extract_bbox(rslc_paths=["/path/to/rslc1.h5", "/path/to/rslc2.h5", ...])
```

Returns: `{min_lon, min_lat, max_lon, max_lat}` — the union bounding box across all scenes.

#### Step B2 — Download Copernicus 30m DEM

Use `ddem.py` with the bounding box from Step B1.
See `references/dem-download.md` for the exact command and options.

Verify the output GeoTIFF covers the full scene extent before proceeding.

## Output requirements (report after completion)

- RSLC data directory and file count
- DEM path, bounding box coordinates, and source used
- Confirmation that all files exist before handing off to the next skill
