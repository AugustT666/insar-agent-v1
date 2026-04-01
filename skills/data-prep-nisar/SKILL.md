---
name: data-prep-nisar
description: >
  Use when NISAR RSLC input files or a DEM are missing before running D-InSAR or
  Stack-InSAR processing. Invoke when the user says "I don't have a DEM", "download
  RSLC", "prepare DEM", "prepare AOI", mentions Copernicus 30m DEM, or asks how to
  get started with data. Also invoke before d-insar-isce3 or stack-insar-isce3
  whenever input files are not yet confirmed to exist on disk.
---

# Data Preparation: NISAR RSLC + DEM

## Required confirmations (ask only if missing)

- RSLC download URL list
- Research area input: AOI file path or explicit bbox
- Output directory for downloaded RSLC data
- DEM output path if DEM should be created

## Hard constraints

- Do not edit downloaded RSLC files.
- Use `copernicus_30` as the default DEM source; only change if user specifies otherwise.
- Confirm all file paths exist on the user's machine before handing off to the next skill.

## Standard workflow

### Part A — Download NISAR RSLC data (ASF)

Use the MCP tool `insar_download_rslc` for programmatic remote-crop download.
See `references/rslc-download.md` for full details, AOI usage, pitfalls, and proxy setup.

#### Step A1 — Prepare inputs

- The user must provide the RSLC `.h5` download URL list.
- The user must also provide either:
  - an AOI file path (`.shp`, `.geojson`, `.kml`), or
  - an explicit bbox `[min_lon, min_lat, max_lon, max_lat]`.

- Pass only `.h5` file URLs to the tool; non-RSLC URLs (`_QA_`, `.png`, `.pdf`, `.xml`, `.kml`) are filtered out but including them adds noise.

#### Step A2 — Run RSLC download

```python
insar_download_rslc(
    urls=[...],                          # .h5 RSLC URLs from ASF
    output_dir="/path/to/output",
    aoi_path="/path/to/study_area.shp",  # or bbox=[...]
    freq="A",                            # L-band
    proxy=None,                          # default: direct; set if direct is slow
)
```

Prerequisites (install once): `pip install fsspec`
Auth: `~/.netrc` must contain `machine urs.earthdata.nasa.gov login <user> password <pass>`

Expected output filename: `NISAR_L1_PR_RSLC_<cycle>_<track>_…_cropped.h5`

### Part B — Prepare DEM

#### Step B1 — Check whether DEM already exists

- If the user already provided `dem_path` and the file exists, treat DEM as ready.
- Otherwise, ask whether DEM should be downloaded for the same AOI / bbox used by the RSLC download.

#### Step B2 — Download Copernicus 30m DEM

Use the MCP tool `insar_download_dem` with the same AOI file or bbox.
See `references/dem-download.md` for the exact call and options.

- DEM download can start before RSLC download finishes.
- Once the user confirms DEM creation, DEM 和 RSLC 可以并行准备。

## Output requirements (report after completion)

- RSLC data directory and file count
- DEM path, AOI/bbox input, and source used
- Confirmation that all files exist before handing off to the next skill
