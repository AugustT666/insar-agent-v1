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


@mcp.tool()
def insar_apply_troposphere_isce2(
    run_root: str,
    ref_date: str,
    sec_date: str,
    grib_files: list[str],
    conda_env: str = "isce2",
    out_dir: str | None = None,
) -> dict:
    """
    Apply an ERA5 tropospheric correction to a finished ISCE2 (Sentinel-1)
    D-InSAR run.

    Sentinel-1/topsApp has no built-in troposphere stage (unlike ISCE3's
    ``troposphere_delay``), so this is an original post-processing step: per epoch
    it computes the pyAPS ERA5 line-of-sight delay on the geocoded interferogram
    grid, differences the two epochs, subtracts it from the unwrapped phase, and
    writes corrected GeoTIFFs + a before/after PNG + JSON into ``<out_dir>``
    (default ``<run_root>/troposphere_correction/``).

    Multi-epoch GRIBs are split internally (per-epoch z,t,q, ordered for pyAPS);
    intermediate splits go to a temp dir and are removed, so no GRIBs are
    scattered into the run.

    The computation runs via ``conda run -n <conda_env>`` because it needs
    pyaps3 + pygrib + GDAL, which live in the isce2/isce3gpu/mintpy envs rather
    than the bare MCP server interpreter.

    Args:
        run_root: D-InSAR run directory containing ``merged/`` (filt_topophase.unw.geo, ...).
        ref_date: Reference epoch ``YYYYMMDD``.
        sec_date: Secondary epoch ``YYYYMMDD``.
        grib_files: ERA5 pressure-level GRIB path(s); one multi-epoch file or per-epoch files.
        conda_env: Conda env that has pyaps3/pygrib/GDAL (default ``"isce2"``).
        out_dir: Output dir; defaults to ``<run_root>/troposphere_correction/``.
    """
    import json as _json
    import subprocess

    import insar_agent
    from insar_agent.engines.isce2.runner import (
        TROPO_RESULT_SENTINEL,
        build_troposphere_command,
    )

    if not (Path(run_root) / "merged" / "filt_topophase.unw.geo.vrt").exists():
        return {"error": "path_not_found",
                "message": f"merged unwrapped product not found under run_root={run_root!r}"}
    missing = [g for g in grib_files if not Path(g).exists()]
    if missing:
        return {"error": "path_not_found", "message": f"GRIB file(s) not found: {missing}"}

    cmd = build_troposphere_command(
        run_root, ref_date, sec_date, grib_files, conda_env=conda_env, out_dir=out_dir)
    src_path = str(Path(insar_agent.__file__).resolve().parents[1])
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=1800,
            env=_conda_safe_env({"PYTHONPATH": src_path}),
        )
    except FileNotFoundError:
        return {"error": "dependency_missing", "message": "conda not found on PATH"}
    except subprocess.TimeoutExpired:
        return {"error": "timeout", "message": "troposphere correction exceeded 1800s"}

    for line in proc.stdout.splitlines():
        if line.startswith(TROPO_RESULT_SENTINEL):
            return _json.loads(line[len(TROPO_RESULT_SENTINEL):])
    return {"error": "correction_failed",
            "message": (proc.stderr or proc.stdout or "no result emitted").strip()[-1200:]}
