# RSLC Download: insar_download_rslc

MCP tool for remote-crop download of NISAR RSLC files from NASA Earthdata (ASF).
Ported from `docs/archive/knowledge-base/wangshuai/Scripts/nisar-test-download_v2.py`.

## How it works

Uses `fsspec` + `h5py` HTTP byte-range requests to download **only the pixels
inside the resolved bbox** without fetching the full ~14 GB frame. Two phases per file:

- **Phase 1** — Copy all HDF5 metadata groups except `/swaths` (fast, ~seconds).
- **Phase 2** — Build cropped `/swaths` from remote SLC data using parallel threads.

Output: `<name>_cropped.h5` files. Cropped size depends on study-area extent and pixel spacing of the processing version; a small study area typically yields files on the order of hundreds of MB per scene.

## Scope

The MCP tool exposes **full crop-download** only. V1 does not implement:

- ASF auto-search;
- preview / quick-look mode.

The user must provide the URL list in advance.

## Prerequisites

```bash
pip install fsspec
```

Auth: `~/.netrc` must contain:
```
machine urs.earthdata.nasa.gov login <earthdata_user> password <earthdata_pass>
```

## Tool parameters

| Parameter | Default | Notes |
|-----------|---------|-------|
| `urls` | required | `.h5` RSLC URLs from ASF; non-RSLC URLs are filtered out |
| `output_dir` | required | Local directory; created if missing |
| `bbox` | optional | `[min_lon, min_lat, max_lon, max_lat]`; mutually exclusive with `aoi_path` |
| `aoi_path` | optional | AOI file path (`.shp`, `.geojson`, `.kml`); mutually exclusive with `bbox` |
| `freq` | `"A"` | NISAR frequency band: `"A"` (L-band) or `"B"` |
| `margin` | `20` | Extra pixel margin around bbox crop window |
| `n_workers` | `8` | Parallel download threads per file |
| `chunk_rows` | `256` | Azimuth rows per thread chunk |
| `proxy` | `None` | HTTP proxy URL. Default: direct (no proxy). |

## AOI handling

When `aoi_path` is provided, the tool resolves the AOI file to a bbox before
downloading. Local parsing is attempted first; ASF `files_to_wkt` is used as a
fallback if local parsing fails.

## Proxy configuration

By default the tool clears any system proxy and downloads **direct**.
If direct access to `nisar.asf.earthdatacloud.nasa.gov` is slow or blocked,
ask the user for a proxy address and pass it explicitly:

```python
insar_download_rslc(..., proxy="http://<proxy-host>:<port>")
```

The proxy override applies only for the duration of the download; system proxy
env vars are restored afterwards.

**Scope:** the override sets `HTTP_PROXY`/`HTTPS_PROXY` process-wide for the
download session. It covers both the data server (`nisar.asf.earthdatacloud.nasa.gov`)
and the NASA Earthdata auth server (`urs.earthdata.nasa.gov`), which is critical
because authentication redirects to `urs.earthdata.nasa.gov` before serving data.

## Preparing the URL list

The tool does not search ASF itself. URLs must be obtained externally and then
passed to the `urls` parameter.

Supported input: `.h5` NISAR L1 RSLC product URLs. The tool silently skips
non-RSLC URLs (`_QA_STATS.h5`, `.png`, `.pdf`, `.xml`, `.kml`), but keeping
the list clean avoids unnecessary validation overhead.

## Performance notes

Each parallel thread opens a new HTTP connection per chunk. For slow connections
this connection overhead dominates. If speed is unacceptable, consider:
1. Providing a faster proxy (see above).
2. Downloading the full `.h5` with `aria2c` and cropping locally with `h5py`.
