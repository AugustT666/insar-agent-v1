from __future__ import annotations

import math
from pathlib import Path
from typing import Any


COPERNICUS_30 = "copernicus_30"
DEFAULT_DEM_MARGIN_DEG = 0.1
_COPERNICUS_30_BASE_URL = "https://copernicus-dem-30m.s3.eu-central-1.amazonaws.com"


def expand_bbox(
    bbox: tuple[float, float, float, float],
    margin_deg: float = DEFAULT_DEM_MARGIN_DEG,
) -> tuple[float, float, float, float]:
    min_lon, min_lat, max_lon, max_lat = bbox
    return (
        min_lon - margin_deg,
        min_lat - margin_deg,
        max_lon + margin_deg,
        max_lat + margin_deg,
    )


def _copernicus_tile_name(lat: int, lon: int) -> str:
    lat_prefix = "N" if lat >= 0 else "S"
    lon_prefix = "E" if lon >= 0 else "W"
    return (
        f"Copernicus_DSM_COG_10_"
        f"{lat_prefix}{abs(lat):02d}_00_"
        f"{lon_prefix}{abs(lon):03d}_00_DEM"
    )


def _copernicus_tile_urls(bbox: tuple[float, float, float, float]) -> list[str]:
    min_lon, min_lat, max_lon, max_lat = bbox
    urls: list[str] = []
    for lat in range(math.floor(min_lat), math.ceil(max_lat)):
        for lon in range(math.floor(min_lon), math.ceil(max_lon)):
            tile_name = _copernicus_tile_name(lat, lon)
            urls.append(f"{_COPERNICUS_30_BASE_URL}/{tile_name}/{tile_name}.tif")
    return urls


def download_dem(
    *,
    output_path: str,
    bbox: tuple[float, float, float, float],
    source: str = COPERNICUS_30,
    margin_deg: float = DEFAULT_DEM_MARGIN_DEG,
    on_progress: Any = None,
) -> dict:
    if source != COPERNICUS_30:
        raise ValueError(f"Unsupported DEM source: {source!r}")

    from osgeo import gdal

    expanded_bbox = expand_bbox(bbox, margin_deg=margin_deg)
    tile_urls = _copernicus_tile_urls(expanded_bbox)
    gdal_sources = [f"/vsicurl/{url}" for url in tile_urls]
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    if on_progress:
        on_progress(
            f"[dem] source={source} tiles={len(tile_urls)} bbox={expanded_bbox}"
        )

    gdal.UseExceptions()
    dataset = gdal.Warp(
        str(output),
        gdal_sources,
        options=gdal.WarpOptions(
            format="GTiff",
            outputBounds=expanded_bbox,
            dstSRS="EPSG:4326",
            creationOptions=["TILED=YES", "COMPRESS=LZW"],
            multithread=True,
        ),
    )
    if dataset is None:
        raise RuntimeError(f"GDAL Warp returned no dataset for {output}")
    dataset = None

    return {
        "output_path": str(output),
        "source": source,
        "bbox": list(expanded_bbox),
        "tile_urls": tile_urls,
    }
