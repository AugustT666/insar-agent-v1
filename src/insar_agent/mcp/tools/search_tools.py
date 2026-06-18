"""MCP tools: search_tools — ASF/CMR catalog discovery (registered on FastMCP).

``insar_search`` answers "what InSAR data exists over this AOI and where do I
fetch it". Its output URLs feed directly into the existing download tools:
Sentinel-1 burst URLs -> ``insar_download_scene``; NISAR ``.h5`` URLs ->
``insar_download_rslc``.
"""

from __future__ import annotations

from insar_agent.mcp._app import *  # noqa: F403  (foundation: imports + constants + mcp)
from insar_agent.discovery import catalog

_S1_ALIASES = {"sentinel1", "sentinel-1", "s1"}


@mcp.tool()
def insar_search(
    platform: str,
    aoi_path: str = "",
    bbox: list[float] | None = None,
    start: str = "",
    end: str = "",
    flight_direction: str = "",
    relative_orbit: int | None = None,
    polarizations: list[str] | None = None,
    nisar_tier: str = "beta",
    existing_root: str = "",
    proxy: str | None = None,
) -> dict:
    """Search ASF / NASA CMR for downloadable InSAR granules over an AOI.

    Discovery only — it never downloads. Returned URLs feed the download tools.

    Args:
        platform:    ``"sentinel1"`` (IW BURST products) or ``"nisar"`` (RSLC).
        aoi_path:    AOI file (``.shp`` / ``.geojson``); alternatively pass ``bbox``.
        bbox:        ``[min_lon, min_lat, max_lon, max_lat]`` in WGS84.
        start, end:  ISO window, e.g. ``"2025-10-01"`` .. ``"2026-01-06"``.
                     Required for Sentinel-1; optional for NISAR.
        flight_direction: Sentinel-1 only — ``"ASCENDING"`` / ``"DESCENDING"``.
        relative_orbit:   Sentinel-1 only — relative orbit (path) number.
        polarizations:    Sentinel-1 only — e.g. ``["VV", "VH"]``.
        nisar_tier:  NISAR only — ``"beta"`` / ``"provisional"`` / ``"validated"``.
        existing_root: optional burst base dir. Acquisitions whose
                     ``<rel_dir>/<scene>`` already exists are flagged
                     ``on_disk`` and excluded from ``missing_by_rel_dir`` /
                     ``missing_urls`` — use these to download only the gap.
        proxy:       ``None`` inherits env proxy; ``"direct"`` bypasses it; or a URL.

    Returns:
        Sentinel-1: ``{acquisitions, by_rel_dir, urls, bbox, window, ...}`` plus
            ``{missing_by_rel_dir, missing_urls, n_missing}`` when
            ``existing_root`` is given.
        NISAR: ``{granules, urls, n_granules, tier, bbox}``.
        On bad input/transport: ``{"error": <code>, "message": <str>}``.
    """
    platform_norm = platform.strip().lower()
    if not aoi_path and not bbox:
        return {"error": "missing_aoi", "message": "provide aoi_path or bbox"}

    try:
        if platform_norm in _S1_ALIASES:
            if not start or not end:
                return {
                    "error": "missing_window",
                    "message": "start and end are required for Sentinel-1",
                }
            result = catalog.search_sentinel1_bursts(
                bbox=bbox or None,
                aoi_path=aoi_path or None,
                start=start,
                end=end,
                relative_orbit=relative_orbit,
                flight_direction=flight_direction or None,
                polarizations=polarizations or None,
                proxy=proxy,
            )
            if existing_root:
                missing_by_rel_dir, missing_urls = catalog.split_existing(
                    result["acquisitions"], existing_root
                )
                result["missing_by_rel_dir"] = missing_by_rel_dir
                result["missing_urls"] = missing_urls
                result["n_missing"] = sum(
                    1 for a in result["acquisitions"] if not a.get("on_disk")
                )
            return result

        if platform_norm == "nisar":
            return catalog.search_nisar_rslc(
                bbox=bbox or None,
                aoi_path=aoi_path or None,
                start=start or None,
                end=end or None,
                tier=nisar_tier,
                proxy=proxy,
            )

        return {
            "error": "bad_platform",
            "message": f"platform must be 'sentinel1' or 'nisar', got {platform!r}",
        }
    except (ValueError, RuntimeError, OSError) as exc:
        return {"error": "search_failed", "message": str(exc)}
