"""NISAR RSLC bounding box extraction.

Normalised from docs/archive/knowledge-base/tianxiaolong/.../nisar_bbox_dem.py.
Provides importable library functions used by the MCP tool layer.
"""
from __future__ import annotations

import re
from pathlib import Path


_COORD_RE = re.compile(r"(-?\d+\.\d+)\s+(-?\d+\.\d+)")
_H5_BBOX_PATH = "/science/LSAR/identification/boundingPolygon"


def _parse_bounding_polygon(wkt_text: str) -> tuple[float, float, float, float]:
    """Parse a WKT POLYGON string and return (min_lon, min_lat, max_lon, max_lat)."""
    coords = _COORD_RE.findall(wkt_text)
    if not coords:
        raise ValueError(f"No coordinates found in WKT: {wkt_text!r}")
    lons = [float(lon) for lon, _ in coords]
    lats = [float(lat) for _, lat in coords]
    return min(lons), min(lats), max(lons), max(lats)


def extract_bbox(rslc_path: str | Path) -> tuple[float, float, float, float]:
    """Extract (min_lon, min_lat, max_lon, max_lat) from a single NISAR RSLC HDF5 file."""
    import h5py  # deferred: not available in all envs

    rslc_path = Path(rslc_path)
    if not rslc_path.exists():
        raise FileNotFoundError(str(rslc_path))

    with h5py.File(rslc_path, "r") as f:
        wkt = f[_H5_BBOX_PATH][()].decode("utf-8")

    return _parse_bounding_polygon(wkt)


def union_bbox(
    rslc_paths: list[str | Path],
) -> dict[str, float]:
    """Return the union bounding box over one or more NISAR RSLC files.

    Returns a dict with keys: min_lon, min_lat, max_lon, max_lat.
    Raises FileNotFoundError if any path does not exist.
    """
    if not rslc_paths:
        raise ValueError("rslc_paths must not be empty")

    all_min_lon, all_min_lat, all_max_lon, all_max_lat = [], [], [], []
    for p in rslc_paths:
        mn_lon, mn_lat, mx_lon, mx_lat = extract_bbox(p)
        all_min_lon.append(mn_lon)
        all_min_lat.append(mn_lat)
        all_max_lon.append(mx_lon)
        all_max_lat.append(mx_lat)

    return {
        "min_lon": min(all_min_lon),
        "min_lat": min(all_min_lat),
        "max_lon": max(all_max_lon),
        "max_lat": max(all_max_lat),
    }
