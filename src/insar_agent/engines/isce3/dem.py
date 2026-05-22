from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any


COPERNICUS_30 = "copernicus_30"
SRTM_C = "srtm_c"
DEFAULT_DEM_MARGIN_DEG = 0.1
_COPERNICUS_30_BASE_URL = "https://copernicus-dem-30m.s3.eu-central-1.amazonaws.com"
_CGIAR_SRTM_BASE_URL = "https://srtm.csi.cgiar.org/wp-content/uploads/files/srtm_5x5/TIFF"


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


def _cgiar_srtm_tile_name(row: int, col: int) -> str:
    return f"srtm_{col:02d}_{row:02d}"


def _cgiar_srtm_tile_urls(bbox: tuple[float, float, float, float]) -> list[str]:
    min_lon, min_lat, max_lon, max_lat = bbox
    lon_edges = range(math.floor(min_lon / 5) * 5, math.ceil(max_lon / 5) * 5, 5)
    lat_edges = range(math.floor(min_lat / 5) * 5, math.ceil(max_lat / 5) * 5, 5)
    urls: set[str] = set()
    for lon_west in lon_edges:
        col = int((lon_west + 180) / 5) + 1
        for lat_south in lat_edges:
            row = int((60 - (lat_south + 5)) / 5) + 1
            tile_name = _cgiar_srtm_tile_name(row, col)
            urls.add(f"{_CGIAR_SRTM_BASE_URL}/{tile_name}.zip")
    return sorted(urls)


def _gdal_sources_for(source: str, bbox: tuple[float, float, float, float]) -> tuple[list[str], list[str]]:
    if source == COPERNICUS_30:
        tile_urls = _copernicus_tile_urls(bbox)
        return tile_urls, [f"/vsicurl/{url}" for url in tile_urls]
    if source == SRTM_C:
        tile_urls = _cgiar_srtm_tile_urls(bbox)
        gdal_sources = []
        for url in tile_urls:
            tile_name = Path(url).stem
            gdal_sources.append(f"/vsizip//vsicurl/{url}/{tile_name}.tif")
        return tile_urls, gdal_sources
    raise ValueError(f"Unsupported DEM source: {source!r}")


def _warp_dem(
    *,
    output: Path,
    gdal_sources: list[str],
    expanded_bbox: tuple[float, float, float, float],
) -> None:
    from osgeo import gdal

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


def download_dem(
    *,
    output_path: str,
    bbox: tuple[float, float, float, float],
    source: str = COPERNICUS_30,
    margin_deg: float = DEFAULT_DEM_MARGIN_DEG,
    on_progress: Any = None,
    proxy: str | None = None,
) -> dict:
    from osgeo import gdal

    expanded_bbox = expand_bbox(bbox, margin_deg=margin_deg)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    proxy_keys = ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")
    old_proxy_env = {k: os.environ.get(k) for k in proxy_keys}
    if proxy is not None:
        for k in proxy_keys:
            os.environ[k] = proxy
        proxy_info = f"proxy override: {proxy}"
    else:
        proxy_info = "proxy: system settings"

    sources_to_try = [source]
    if source == COPERNICUS_30:
        sources_to_try.append(SRTM_C)

    errors: list[str] = []
    try:
        gdal.UseExceptions()
        for candidate_source in sources_to_try:
            tile_urls, gdal_sources = _gdal_sources_for(candidate_source, expanded_bbox)
            if on_progress:
                on_progress(
                    f"[dem] source={candidate_source} tiles={len(tile_urls)} bbox={expanded_bbox} | {proxy_info}"
                )
            try:
                _warp_dem(output=output, gdal_sources=gdal_sources, expanded_bbox=expanded_bbox)
                return {
                    "output_path": str(output),
                    "source": candidate_source,
                    "bbox": list(expanded_bbox),
                    "tile_urls": tile_urls,
                }
            except Exception as exc:
                errors.append(f"{candidate_source}: {exc}")
                if output.exists():
                    output.unlink()
        raise RuntimeError("DEM download failed for all sources: " + "; ".join(errors))
    finally:
        for k, v in old_proxy_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
