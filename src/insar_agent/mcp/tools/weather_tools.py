"""MCP tool: insar_download_era5 (ERA5 GRIB for tropospheric correction)."""
from __future__ import annotations

from pathlib import Path

from insar_agent.mcp._app import *  # noqa: F401, F403  (mcp instance + constants)
from insar_agent.mcp._helpers import *  # noqa: F401, F403  (shared helpers + _resolve_bbox_input)
from insar_agent.core.output_resolver import prepare_input_dir
from insar_agent.engines import era5


def _cdsapi_retrieve(dataset: str, request: dict, target: str, rc_path: str = "") -> None:
    """Issue one real CDS request. Isolated for test monkeypatching."""
    import cdsapi

    if rc_path:
        url, key = _cds_rc(rc_path)
        client = cdsapi.Client(url=url, key=key)
    else:
        client = cdsapi.Client()
    client.retrieve(dataset, request, target)


def _cds_rc(rc_path: str) -> tuple[str, str]:
    import configparser

    cfg = configparser.ConfigParser()
    raw = "[cds]\n" + Path(rc_path).expanduser().read_text()
    cfg.read_string(raw)
    return cfg["cds"]["url"], cfg["cds"]["key"]


@mcp.tool()  # noqa: F405
def insar_download_era5(
    dates: list[str],
    bbox: list[float] | None = None,
    aoi_path: str = "",
    hour: str = "10",
    output_dir: str = "",
    project_id: str = "",
    dry_run: bool = False,
    background: bool = False,
    cds_rc_path: str = "",
    conda_env: str = "",
) -> dict:
    """Download ERA5 pressure-level GRIB for tropospheric correction.

    Files are named exactly as MintPy expects and written under
    ``<output_dir>/ERA5/`` (default ``<output_root>/prepare/weather/ERA5/``), so
    MintPy's correct_troposphere step reuses them without re-downloading.

    Use ``dry_run=True`` to preview the exact CDS request(s) and file plan WITHOUT
    sending anything (approval gate). Multiple dates are batched into as few CDS
    requests as the 120000-item cap allows (one request when possible).

    Args:
        dates: Acquisition epochs as ``YYYYMMDD`` strings (one per SAR scene).
        bbox: ``[W,S,E,N]`` WGS84; or pass aoi_path instead.
        aoi_path: Path to an AOI file (GeoJSON/KML/SHP); or pass bbox instead.
        hour: ERA5 analysis hour ``"HH"`` (closest to SAR overpass UTC; e.g. "10").
        output_dir: weather dir; default ``<output_root>/prepare/weather`` via project_id.
        project_id: Project UUID; used to derive output_dir when output_dir is omitted.
        dry_run: If true, return the request plan and file plan without contacting CDS.
        background: If true, launch as a background job (poll with insar_get_job).
        cds_rc_path: Path to a CDS API RC file (default: ``~/.cdsapirc``).
        conda_env: Conda env that has cdsapi+pygrib to run the download/split in.
            Default "" auto-discovers one (NEVER hardcodes an env name).
    """
    if not dates:
        return {"error": "invalid_input", "message": "dates must be a non-empty list of YYYYMMDD"}

    # Resolve weather dir
    if not output_dir.strip():
        if not project_id.strip():
            return {"error": "missing_input",
                    "message": "Provide output_dir or project_id."}
        try:
            _proj = Project.load(project_id.strip())  # noqa: F405
        except (KeyError, FileNotFoundError):
            return {"error": "project_not_found", "message": f"Project {project_id!r} not found"}
        output_dir = str(prepare_input_dir(_proj.output_root, "weather"))

    weather_dir = Path(output_dir).expanduser()
    grib_dir = weather_dir / "ERA5"

    try:
        w, s, e, n = _resolve_bbox_input(bbox=bbox, aoi_path=aoi_path)
    except FileNotFoundError as exc:
        return {"error": "path_not_found", "message": str(exc)}
    except ValueError as exc:
        return {"error": "invalid_input", "message": str(exc)}

    snwe = era5.round_snwe(w=w, s=s, e=e, n=n)
    requests = era5.build_cds_requests(sorted(set(dates)), snwe, hour)
    targets = era5.target_grib_paths(sorted(set(dates)), snwe, hour, grib_dir)
    file_plan = [str(p) for p in targets.values()]

    if dry_run:
        return {
            "dry_run": True,
            "n_requests": len(requests),
            "est_dates": len(targets),
            "weather_dir": str(weather_dir),
            "snwe": list(snwe),
            "hour": hour,
            "requests": requests,
            "file_plan": file_plan,
        }

    if background:
        return _launch_era5_download_background({  # noqa: F405
            "dates": list(dates),
            "bbox": [w, s, e, n],
            "aoi_path": "",
            "hour": hour,
            "output_dir": str(weather_dir),
            "project_id": project_id,
            "cds_rc_path": cds_rc_path,
        })

    return _download_era5_real(
        requests, targets, snwe, hour, grib_dir,
        weather_dir, dates, cds_rc_path, conda_env,
    )


def _has_credentials(cds_rc_path: str) -> bool:
    rc = Path(cds_rc_path).expanduser() if cds_rc_path else (Path.home() / ".cdsapirc")
    return rc.is_file()


def _build_era5_runner_command(conda_env: str, job_path: str) -> list[str]:
    """argv to run the ERA5 download/split inside *conda_env* (no hardcoded env)."""
    return [
        "conda", "run", "-n", conda_env, "--no-capture-output",
        "python", "-m", "insar_agent.engines.era5_runner", str(job_path),
    ]


def _run_era5_download_in_env(
    conda_env: str, requests: list[dict], snwe: tuple, hour: str,
    grib_dir: Path, dates: list[str], cds_rc_path: str,
) -> list[str]:
    """Dispatch retrieve+split to a conda env that has cdsapi+pygrib and return the
    written per-date filenames. Runs ``insar_agent.engines.era5_runner`` via conda."""
    import json as _json
    import subprocess
    import tempfile

    import insar_agent
    from insar_agent.engines.era5_runner import RESULT_SENTINEL

    grib_dir.mkdir(parents=True, exist_ok=True)
    spec = {
        "requests": requests, "snwe": list(snwe), "hour": hour,
        "grib_dir": str(grib_dir), "dates": list(dates), "cds_rc_path": cds_rc_path,
    }
    src_path = str(Path(insar_agent.__file__).resolve().parents[1])
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as jf:
        _json.dump(spec, jf)
        job = jf.name
    try:
        proc = subprocess.run(
            _build_era5_runner_command(conda_env, job),
            capture_output=True, text=True, timeout=3600,
            env=_conda_safe_env({"PYTHONPATH": src_path}),  # noqa: F405
        )
    finally:
        Path(job).unlink(missing_ok=True)
    for line in proc.stdout.splitlines():
        if line.startswith(RESULT_SENTINEL):
            return _json.loads(line[len(RESULT_SENTINEL):])["written"]
    raise RuntimeError(
        f"era5 download failed in env {conda_env!r}: {(proc.stderr or proc.stdout)[-800:]}"
    )


def _download_era5_real(
    requests: list[dict],
    targets: dict,
    snwe: tuple,
    hour: str,
    grib_dir: Path,
    weather_dir: Path,
    dates: list[str],
    cds_rc_path: str,
    conda_env: str = "",
) -> dict:
    from insar_agent.core.conda_env import resolve_conda_env

    dates = sorted(set(dates))

    # Reuse short-circuit: all target files already present
    if all(p.exists() for p in targets.values()):
        return {
            "weather_dir": str(weather_dir),
            "grib_dir": str(grib_dir),
            "grib_files": [p.name for p in targets.values()],
            "dates_covered": dates,
            "n_requests": 0,
            "reused": True,
        }

    if not _has_credentials(cds_rc_path):
        return {
            "error": "missing_credentials",
            "message": (
                "No ~/.cdsapirc found. Register at "
                "https://cds.climate.copernicus.eu/how-to-api, accept the "
                "ERA5 licence, and place your token in ~/.cdsapirc "
                "(url: https://cds.climate.copernicus.eu/api / key: <token>)."
            ),
        }

    # Run cdsapi retrieve + pygrib split in a conda env that has them (discovered,
    # never hardcoded) — the MCP server's base interpreter usually lacks pygrib.
    env = resolve_conda_env(conda_env, ["cdsapi", "pygrib"], prefer=["mintpy", "isce2"])
    if not env:
        return {
            "error": "no_capable_env",
            "message": (
                "No conda env with cdsapi+pygrib found to download ERA5. "
                "Run insar_check_env; install e.g. 'conda install -n <env> -c conda-forge cdsapi pygrib'."
            ),
        }

    written = _run_era5_download_in_env(env, requests, snwe, hour, grib_dir, dates, cds_rc_path)
    written_set = set(written)
    covered = sorted(d for d in dates if era5.grib_filename(snwe, d, hour) in written_set)
    return {
        "weather_dir": str(weather_dir),
        "grib_dir": str(grib_dir),
        "grib_files": sorted(set(written)),
        "dates_covered": covered,
        "n_requests": len(requests),
        "reused": False,
        "conda_env": env,
    }
