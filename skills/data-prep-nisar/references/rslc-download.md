# RSLC Download: insar_download_rslc

MCP tool for remote-crop download of NISAR RSLC files from NASA Earthdata (ASF).
Ported from `docs/archive/knowledge-base/wangshuai/Scripts/nisar-test-download_v2.py`.

## How it works

Uses `fsspec` + `h5py` HTTP byte-range requests to download **only the pixels
inside the bbox** without fetching the full ~14 GB frame. Two phases per file:

- **Phase 1** — Copy all HDF5 metadata groups except `/swaths` (fast, ~seconds).
- **Phase 2** — Build cropped `/swaths` from remote SLC data using parallel threads.

Output: `<name>_cropped.h5` files. Cropped size depends on bbox extent and pixel spacing of the processing version; a small study area (~30 km across) typically yields files on the order of hundreds of MB per scene.

## Download modes

The MCP tool currently exposes **full crop-download** only: all swath data
within the bbox is downloaded at full resolution. Output size scales with
bbox extent and pixel spacing of the processing version.

The underlying script (`nisar-test-download_v2.py`) also implements a
**preview / quick-look downsample** mode that downloads a spatially subsampled
version for fast scene inspection before committing to a full download. This
mode is not yet exposed in `insar_download_rslc`. If preview is needed, run
the script directly or request the feature be added to the tool.

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
| `bbox` | required | `[min_lon, min_lat, max_lon, max_lat]` |
| `output_dir` | required | Local directory; created if missing |
| `freq` | `"A"` | NISAR frequency band: `"A"` (L-band) or `"B"` |
| `margin` | `20` | Extra pixel margin around bbox crop window |
| `n_workers` | `8` | Parallel download threads per file |
| `chunk_rows` | `256` | Azimuth rows per thread chunk |
| `proxy` | `None` | HTTP proxy URL. Default: direct (no proxy). |

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

## Common pitfall: wrong bbox from boundingPolygon

`identification/boundingPolygon` in the HDF5 stores the **full-frame** geographic
extent copied verbatim during Phase 1 metadata copy — even for already-cropped files.

| Method | Result |
|--------|--------|
| `nisar_bbox_dem.py` / `boundingPolygon` | Full frame extent (varies by track/frame, typically hundreds of km) — **wrong** |
| SLC pixel axes (zeroDopplerTime + slantRange + geolocationGrid interpolation) | Actual cropped extent — **correct** |

Use the known study area coordinates as the bbox, not values derived from
`boundingPolygon`.

## Preparing the URL list

The tool does not search ASF itself. URLs must be obtained externally from
[ASF Vertex](https://search.asf.alaska.edu) or a similar catalog, then passed
to the `urls` parameter.

Supported input: `.h5` NISAR L1 RSLC product URLs. The tool silently skips
non-RSLC URLs (`_QA_STATS.h5`, `.png`, `.pdf`, `.xml`, `.kml`), but keeping
the list clean avoids unnecessary validation overhead.

Data selection criteria (processing version, acquisition mode, temporal
baseline) are scientific decisions that depend on the study area and objective.
Consult the ASF Vertex filter options and NISAR mission documentation for
current guidance.

## Performance notes

Each parallel thread opens a new HTTP connection per chunk. For slow connections
this connection overhead dominates. If speed is unacceptable, consider:
1. Providing a faster proxy (see above).
2. Downloading the full `.h5` with `aria2c` and cropping locally with `h5py`.
