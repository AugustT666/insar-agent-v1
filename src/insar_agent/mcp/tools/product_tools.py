"""MCP tools: product_tools (registered on the shared FastMCP)."""

from __future__ import annotations

from insar_agent.mcp._app import *  # noqa: F403  (foundation: imports + constants + mcp)
from insar_agent.mcp._helpers import *  # noqa: F403  (shared helpers)


@mcp.tool()
def insar_geocode_runw(
    runw_h5: str,
    rdr2geo_dir: str,
    output_dir: str,
    frequency: str = "A",
    polarization: str = "HH",
) -> dict:
    """
    Salvage a geocoded GeoTIFF from a radar-geometry RUNW product.

    Use this when the ISCE3 geocode step produced a degenerate GUNW grid (for
    example a metric ``geocode.output_posting`` applied under a geographic
    EPSG:4326 grid collapsed the raster to ~1x1 pixel). The radar-geometry RUNW
    interferogram is unaffected, so its unwrappedPhase / coherenceMagnitude /
    connectedComponents are re-geocoded directly via GDAL geolocation arrays
    built from the rdr2geo lon/lat rasters — no ISCE3 re-run is required.

    Outputs are written under <output_dir>/geocoded/. Requires h5py, numpy, and
    GDAL — must be run inside the isce3 conda environment.

    Args:
        runw_h5: Absolute path to the RUNW .h5 file (e.g. <scratch>/RUNW.h5).
        rdr2geo_dir: Directory holding x.rdr (lon) and y.rdr (lat), typically
                     <scratch>/rdr2geo/freq<frequency>.
        output_dir: Directory where the geocoded/ subdirectory will be created.
        frequency: NISAR frequency band ("A" or "B").
        polarization: Polarization channel (e.g. "HH").
    """
    if not Path(runw_h5).exists():
        return {"error": "path_not_found", "message": f"File not found: {runw_h5!r}"}
    if not Path(rdr2geo_dir).exists():
        return {"error": "path_not_found", "message": f"Directory not found: {rdr2geo_dir!r}"}

    try:
        result = geocode_runw_to_geotiff(
            runw_h5=runw_h5,
            rdr2geo_dir=rdr2geo_dir,
            output_dir=output_dir,
            frequency=frequency,
            polarization=polarization,
        )
    except RuntimeError as exc:
        return {"error": "dependency_missing", "message": str(exc)}
    except FileNotFoundError as exc:
        return {"error": "path_not_found", "message": str(exc)}
    except Exception as exc:
        return {"error": "geocode_failed", "message": str(exc)}

    return {
        "output_dir": result["output_dir"],
        "n_files": len(result["files"]),
        "files": result["files"],
        "skipped": result["skipped"],
    }
