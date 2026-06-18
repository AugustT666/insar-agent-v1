"""ASF / CMR catalog search for NISAR RSLC and Sentinel-1 bursts.

Design notes
------------
* No third-party dependencies. The MCP server is launched as a bare
  ``python -m insar_agent.mcp.server`` whose interpreter is whatever is on
  PATH, so discovery must work with the standard library only (``urllib``).
* Pure parsing/grouping (``parse_burst_results`` / ``parse_nisar_granules``)
  is separated from network I/O so it can be unit-tested with fixtures.
* Sentinel-1 burst products map 1:1 onto the on-disk layout already used by
  ``insar_download_scene``: the burst download URL path is
  ``<scene>/<subswath>/<pol>/<index>.tiff`` and the per-burst annotation is the
  same URL with a ``.xml`` suffix. Downloading both into the relative-orbit
  directory therefore reproduces ``<rel_dir>/<scene>/IW*/VV|VH/<idx>.{tiff,xml}``.
"""

from __future__ import annotations

import json
import struct
import time
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import ProxyHandler, Request, build_opener

ASF_SEARCH_API = "https://api.daac.asf.alaska.edu/services/search/param"
CMR_GRANULES = "https://cmr.earthdata.nasa.gov/search/granules.umm_json"
S1_BURST_HOST = "sentinel1-burst.asf.alaska.edu"

# NASA CMR collection concept-ids for the three NISAR RSLC release tiers.
NISAR_COLLECTIONS = {
    "beta": "C2850225585-ASF",
    "provisional": "C2853145197-ASF",
    "validated": "C3622236985-ASF",
}

_DIRECT_PROXY_VALUES = {"direct", "none", "off", "false", "no_proxy", "no-proxy"}


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def _platform_short(dataset: str) -> str:
    """``"SENTINEL-1A"`` -> ``"S1A"``."""
    return dataset.upper().replace("-", "").replace("SENTINEL", "S")


def _burst_xml_url(tiff_url: str) -> str:
    """Annotation URL for a burst: same path with ``.xml`` instead of ``.tiff``."""
    if tiff_url.endswith(".tiff"):
        return tiff_url[: -len(".tiff")] + ".xml"
    return tiff_url


def _rel_dir_name(platform_short: str, path: int, flight_direction: str) -> str:
    """Relative-orbit directory, e.g. ``S1A_rel014_ascending``."""
    return f"{platform_short}_rel{int(path):03d}_{flight_direction.lower()}"


def _scene_from_burst_url(url: str) -> str:
    parts = urlparse(url).path.lstrip("/").split("/")
    return parts[0] if parts else ""


def _burst_components_from_url(url: str) -> tuple[str, str, str, int]:
    """Return ``(scene, subswath, pol, index)`` parsed from a burst URL path."""
    parts = urlparse(url).path.lstrip("/").split("/")
    if len(parts) < 4:
        raise ValueError(f"unexpected burst URL layout: {url}")
    scene, subswath, pol, filename = parts[0], parts[1], parts[2], parts[3]
    index = int(filename.split(".")[0])
    return scene, subswath, pol, index


def parse_burst_results(
    results: Iterable[dict],
    relative_orbit: int | None = None,
    flight_direction: str | None = None,
    polarizations: Sequence[str] | None = None,
) -> dict:
    """Filter + group ASF SearchAPI burst results into acquisitions.

    Args:
        results: ``results`` list from an ASF SearchAPI ``output=jsonlite``
            burst query.
        relative_orbit: keep only this ``path`` (relative orbit) when given.
        flight_direction: keep only ``ASCENDING`` / ``DESCENDING`` when given.
        polarizations: keep only these polarizations (e.g. ``["VV", "VH"]``).

    Returns a dict with ``acquisitions`` (grouped by date+scene), a flat
    ``urls`` list (tiff + xml per burst) and ``by_rel_dir`` mapping each
    download directory to its URL list.
    """
    pol_filter = {p.upper() for p in polarizations} if polarizations else None
    fd_filter = flight_direction.upper() if flight_direction else None

    acquisitions: dict[tuple[str, str], dict] = {}
    for record in results:
        url = record.get("downloadUrl") or ""
        if S1_BURST_HOST not in url:
            continue
        path = record.get("path")
        fdir = (record.get("flightDirection") or "").upper()
        if path is None or not fdir:
            continue  # malformed record — cannot place it in a relative-orbit dir
        if relative_orbit is not None and path != relative_orbit:
            continue
        if fd_filter is not None and fdir != fd_filter:
            continue

        scene, subswath, pol, index = _burst_components_from_url(url)
        if pol_filter is not None and pol.upper() not in pol_filter:
            continue

        date = (record.get("startTime") or "")[:10].replace("-", "")
        platform = record.get("dataset") or ""
        rel_dir = _rel_dir_name(_platform_short(platform), path, fdir)
        key = (date, scene)

        acq = acquisitions.get(key)
        if acq is None:
            acq = {
                "date": date,
                "platform": platform,
                "path": path,
                "flight_direction": fdir,
                "scene": scene,
                "rel_dir": rel_dir,
                "bursts": [],
                "size_mb": 0.0,
            }
            acquisitions[key] = acq

        acq["bursts"].append(
            {
                "subswath": subswath,
                "pol": pol,
                "index": index,
                "tiff": url,
                "xml": _burst_xml_url(url),
            }
        )
        acq["size_mb"] += float(record.get("sizeMB") or 0.0)

    ordered: list[dict] = []
    by_rel_dir: dict[str, list[str]] = {}
    all_urls: list[str] = []
    for key in sorted(acquisitions):
        acq = acquisitions[key]
        acq["bursts"].sort(key=lambda b: (b["subswath"], b["pol"], b["index"]))
        acq["n_bursts"] = len(acq["bursts"])
        acq["size_mb"] = round(acq["size_mb"], 1)
        urls: list[str] = []
        for burst in acq["bursts"]:
            urls.append(burst["tiff"])
            urls.append(burst["xml"])
        by_rel_dir.setdefault(acq["rel_dir"], []).extend(urls)
        all_urls.extend(urls)
        ordered.append(acq)

    return {
        "platform": "sentinel1",
        "product": "BURST",
        "n_acquisitions": len(ordered),
        "n_bursts": sum(a["n_bursts"] for a in ordered),
        "acquisitions": ordered,
        "by_rel_dir": by_rel_dir,
        "urls": all_urls,
    }


def split_existing(
    acquisitions: list[dict], existing_root: str
) -> tuple[dict[str, list[str]], list[str]]:
    """Flag acquisitions already on disk and collect URLs for the missing ones.

    A burst acquisition is considered present when
    ``<existing_root>/<rel_dir>/<scene>`` exists and is non-empty (mirrors the
    layout produced by ``insar_download_scene``). Each acquisition gains an
    ``on_disk`` flag; only absent ones contribute to the returned download URLs.
    """
    root = Path(existing_root)
    missing_by_rel_dir: dict[str, list[str]] = {}
    missing_urls: list[str] = []
    for acq in acquisitions:
        scene_dir = root / acq["rel_dir"] / acq["scene"]
        on_disk = scene_dir.is_dir() and any(scene_dir.iterdir())
        acq["on_disk"] = on_disk
        if on_disk:
            continue
        for burst in acq["bursts"]:
            missing_by_rel_dir.setdefault(acq["rel_dir"], []).extend(
                [burst["tiff"], burst["xml"]]
            )
            missing_urls.extend([burst["tiff"], burst["xml"]])
    return missing_by_rel_dir, missing_urls


def _pick_h5_url(related_urls: Iterable[dict]) -> str:
    """Pick the primary HTTPS ``.h5`` GET DATA url (skip S3 mirror and QA files)."""
    for item in related_urls:
        url = item.get("URL", "")
        if item.get("Type") != "GET DATA":
            continue
        if not url.startswith("https://") or not url.endswith(".h5"):
            continue
        if "_QA_" in url or url.endswith("_QA_STATS.h5"):
            continue
        return url
    return ""


def parse_nisar_granules(items: Iterable[dict]) -> dict:
    """Parse CMR ``umm_json`` granule items into NISAR RSLC records."""
    import re

    pattern = re.compile(
        r"NISAR_L1_PR_RSLC_(\d{3})_(\d{3})_([AD])_(\d{3})_\d+_([A-Z]{4})_[AD]_"
        r"(\d{8})T\d+_"
    )
    granules: list[dict] = []
    urls: list[str] = []
    for item in items:
        umm = item.get("umm", {})
        ur = umm.get("GranuleUR", "")
        match = pattern.search(ur)
        if not match:
            continue
        cycle, track, direction, frame, pol, date = match.groups()
        h5_url = _pick_h5_url(umm.get("RelatedUrls", []))
        granules.append(
            {
                "granule": ur,
                "cycle": cycle,
                "track": track,
                "frame": frame,
                "direction": direction,
                "polarization": pol,
                "date": date,
                "stack_id": f"{track}_{direction}_{frame}",
                "h5_url": h5_url,
            }
        )
        if h5_url:
            urls.append(h5_url)

    granules.sort(key=lambda g: g["date"])
    return {
        "platform": "nisar",
        "product": "RSLC",
        "n_granules": len(granules),
        "granules": granules,
        "urls": urls,
    }


# ---------------------------------------------------------------------------
# AOI resolution
# ---------------------------------------------------------------------------
def _bbox_from_shapefile(shp_path: str) -> list[float]:
    """Read ``[min_lon, min_lat, max_lon, max_lat]`` from a shapefile header."""
    with open(shp_path, "rb") as handle:
        header = handle.read(100)
    if len(header) < 68:
        raise ValueError(f"not a valid .shp file: {shp_path}")
    xmin, ymin, xmax, ymax = struct.unpack("<4d", header[36:68])
    return [xmin, ymin, xmax, ymax]


def _bbox_from_geojson(path: str) -> list[float]:
    data = json.loads(Path(path).read_text())
    xs: list[float] = []
    ys: list[float] = []

    def _walk(coords: Any) -> None:
        if (
            isinstance(coords, (list, tuple))
            and len(coords) >= 2
            and all(isinstance(v, (int, float)) for v in coords[:2])
        ):
            xs.append(float(coords[0]))
            ys.append(float(coords[1]))
            return
        if isinstance(coords, (list, tuple)):
            for child in coords:
                _walk(child)

    features = data.get("features") if isinstance(data, dict) else None
    geometries = (
        [f.get("geometry", {}) for f in features]
        if features
        else [data.get("geometry", data) if isinstance(data, dict) else data]
    )
    for geom in geometries:
        if isinstance(geom, dict):
            _walk(geom.get("coordinates", []))
    if not xs or not ys:
        raise ValueError(f"no coordinates found in geojson: {path}")
    return [min(xs), min(ys), max(xs), max(ys)]


def resolve_bbox(
    bbox: Sequence[float] | None = None, aoi_path: str | None = None
) -> list[float]:
    """Return ``[min_lon, min_lat, max_lon, max_lat]`` from a bbox or AOI file."""
    if bbox:
        if len(bbox) != 4:
            raise ValueError("bbox must be [min_lon, min_lat, max_lon, max_lat]")
        return [float(v) for v in bbox]
    if aoi_path:
        lowered = str(aoi_path).lower()
        if lowered.endswith(".shp"):
            return _bbox_from_shapefile(aoi_path)
        if lowered.endswith((".geojson", ".json")):
            return _bbox_from_geojson(aoi_path)
        raise ValueError(f"unsupported AOI file type: {aoi_path}")
    raise ValueError("provide either bbox or aoi_path")


def bbox_to_wkt(bbox: Sequence[float]) -> str:
    """Closed counter-clockwise polygon WKT for an [W, S, E, N] bbox."""
    w, s, e, n = bbox
    return (
        f"POLYGON(({w} {s},{e} {s},{e} {n},{w} {n},{w} {s}))"
    )


# ---------------------------------------------------------------------------
# Network I/O
# ---------------------------------------------------------------------------
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _fetch_once(url: str, timeout: int, proxy: str | None) -> bytes:
    """Single HTTP GET returning the raw body, honouring an explicit/disabled proxy.

    ``proxy=None`` inherits environment proxies; one of ``direct``/``none``/...
    bypasses them; any other value is used as the HTTP/HTTPS proxy URL.
    """
    proxy_mode = proxy.strip().lower() if proxy else None
    if proxy_mode in _DIRECT_PROXY_VALUES:
        handler = ProxyHandler({})  # empty mapping disables proxies
    elif proxy:
        handler = ProxyHandler({"http": proxy, "https": proxy})
    else:
        handler = ProxyHandler()  # inherit environment
    opener = build_opener(handler)
    request = Request(url, headers={"User-Agent": "insar-agent-discovery"})
    with opener.open(request, timeout=timeout) as response:
        return response.read()


def _http_get_json(
    url: str,
    params: dict[str, str],
    timeout: int = 90,
    proxy: str | None = None,
    retries: int = 4,
    backoff: float = 3.0,
) -> dict:
    """GET ``url?params`` as JSON, retrying transient (429/5xx/network) errors.

    The ASF SearchAPI returns intermittent 504s under load, so a bounded retry
    with linear backoff keeps discovery reliable.
    """
    full_url = f"{url}?{urlencode(params)}"
    last_error: str = "request failed"
    for attempt in range(1, retries + 1):
        try:
            return json.loads(_fetch_once(full_url, timeout, proxy).decode("utf-8"))
        except HTTPError as exc:
            last_error = f"HTTP {exc.code}: {exc.reason}"
            if exc.code not in _RETRYABLE_STATUS:
                raise RuntimeError(f"catalog {last_error} for {url}") from exc
        except (URLError, TimeoutError) as exc:
            last_error = f"transport error: {getattr(exc, 'reason', exc)}"
        if attempt < retries and backoff:
            time.sleep(backoff * attempt)
    raise RuntimeError(f"catalog request failed after {retries} tries ({last_error}) for {url}")


def search_sentinel1_bursts(
    *,
    bbox: Sequence[float] | None = None,
    aoi_path: str | None = None,
    start: str,
    end: str,
    relative_orbit: int | None = None,
    flight_direction: str | None = None,
    polarizations: Sequence[str] | None = None,
    proxy: str | None = None,
    timeout: int = 90,
) -> dict:
    """Discover Sentinel-1 IW burst products intersecting an AOI."""
    resolved = resolve_bbox(bbox, aoi_path)
    params = {
        "intersectsWith": bbox_to_wkt(resolved),
        "processingLevel": "BURST",
        "beamMode": "IW",
        "start": start,
        "end": end,
        "output": "jsonlite",
    }
    data = _http_get_json(ASF_SEARCH_API, params, timeout=timeout, proxy=proxy)
    results = data.get("results", []) if isinstance(data, dict) else []
    parsed = parse_burst_results(
        results,
        relative_orbit=relative_orbit,
        flight_direction=flight_direction,
        polarizations=polarizations,
    )
    parsed["bbox"] = resolved
    parsed["window"] = {"start": start, "end": end}
    return parsed


def search_nisar_rslc(
    *,
    bbox: Sequence[float] | None = None,
    aoi_path: str | None = None,
    start: str | None = None,
    end: str | None = None,
    tier: str = "beta",
    proxy: str | None = None,
    timeout: int = 90,
) -> dict:
    """Discover NISAR RSLC granules over an AOI from NASA CMR."""
    if tier not in NISAR_COLLECTIONS:
        raise ValueError(f"unknown NISAR tier {tier!r}; choose {list(NISAR_COLLECTIONS)}")
    resolved = resolve_bbox(bbox, aoi_path)
    w, s, e, n = resolved
    params = {
        "collection_concept_id": NISAR_COLLECTIONS[tier],
        "bounding_box": f"{w},{s},{e},{n}",
        "page_size": "500",
    }
    if start and end:
        params["temporal"] = f"{start},{end}"
    data = _http_get_json(CMR_GRANULES, params, timeout=timeout, proxy=proxy)
    items = data.get("items", []) if isinstance(data, dict) else []
    parsed = parse_nisar_granules(items)
    parsed["tier"] = tier
    parsed["bbox"] = resolved
    return parsed
