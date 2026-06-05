"""insar-agent MCP server: public import surface and stdio entry point.

Most tools/resources/prompts/helpers live in focused sibling modules and are
re-exported here so ``from insar_agent.mcp.server import <name>`` keeps working
(detached background runners import ``insar_agent.mcp.server``).  Tools whose
tests monkeypatch ``insar_agent.mcp.server.<name>`` — and the helpers they call —
remain DEFINED in this module so the patch target and its caller share one
namespace.  Per docs/architecture.md, MCP binding stays inside ``mcp``.
"""
from __future__ import annotations

from insar_agent.mcp._app import *  # noqa: F403  (foundation: imports + constants + mcp)
from insar_agent.mcp._app import mcp  # noqa: F401  (explicit: shared FastMCP instance)
from insar_agent.mcp._helpers import *  # noqa: F403  (shared helpers)

# Importing these registers their @mcp.resource / @mcp.prompt / @mcp.tool
# decorators on the shared ``mcp`` instance.  The names are re-exported below so
# ``from insar_agent.mcp.server import <name>`` and the background here-doc resolve.
from insar_agent.mcp import resources as _resources  # noqa: F401
from insar_agent.mcp import prompts as _prompts  # noqa: F401
from insar_agent.mcp import tools as _tools  # noqa: F401
from insar_agent.mcp.resources import (  # noqa: F401  (re-export)
    get_workflow_guide,
    get_allowed_fields,
)
from insar_agent.mcp.prompts import (  # noqa: F401  (re-export)
    process_insar_pair,
    process_insar_batch,
)
from insar_agent.mcp.tools.project_tools import (  # noqa: F401  (re-export)
    insar_discover,
    insar_list_engines,
    insar_list_workflows,
    insar_get_project,
    insar_create_project,
    insar_get_runconfig,
    insar_set_runconfig_value,
)
from insar_agent.mcp.tools.param_tools import (  # noqa: F401  (re-export)
    insar_record_param_advice,
    insar_set_processing_param,
    insar_export_runconfig,
)
from insar_agent.mcp.tools.job_tools import (  # noqa: F401  (re-export)
    insar_get_job,
    insar_list_outputs,
    insar_get_mintpy_status,
)
from insar_agent.mcp.tools.prepare_tools import (  # noqa: F401  (re-export)
    insar_prepare_stack,
    insar_prepare_network,
    insar_run_batch,
    insar_describe_rslc,
    insar_download_scene,
    insar_describe_s1,
)
from insar_agent.mcp.tools.product_tools import (  # noqa: F401  (re-export)
    insar_geocode_runw,
)
from insar_agent.mcp.tools.env_tools import (  # noqa: F401  (re-export)
    insar_check_env,
)


# ── STAY: definitions whose tests monkeypatch insar_agent.mcp.server.<name>
# (and their callers).  Patched name + caller must share this module namespace.


def _read_dem_bbox(dem_file: str) -> list[float]:
    try:
        proc = subprocess.run(
            ["gdalinfo", "-json", dem_file],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        info = json.loads(proc.stdout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"Cannot read DEM bounds with gdalinfo for {dem_file!r}: {exc}") from exc

    corner_coordinates = info.get("cornerCoordinates") or {}
    xs: list[float] = []
    ys: list[float] = []
    try:
        for key in ("upperLeft", "lowerLeft", "upperRight", "lowerRight"):
            corner = corner_coordinates.get(key)
            if not isinstance(corner, list | tuple) or len(corner) < 2:
                continue
            xs.append(float(corner[0]))
            ys.append(float(corner[1]))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Cannot parse DEM bounds from gdalinfo for {dem_file!r}: {exc}") from exc
    if not xs or not ys:
        raise ValueError(f"Cannot read DEM bounds from gdalinfo for {dem_file!r}.")
    return [min(xs), min(ys), max(xs), max(ys)]


def _validate_isce2_dem_scene_overlap(params: dict, workflow: str) -> list[str]:
    dem_file = params.get("dem_file")
    if not dem_file:
        return []

    scene_paths = _sentinel_scene_paths_for_isce2(params, workflow)
    if not scene_paths:
        return []

    try:
        dem_bbox = _read_dem_bbox(str(dem_file))
    except ValueError as exc:
        return [str(exc)]

    errors: list[str] = []
    scene_read_errors: list[str] = []
    valid_scene_count = 0
    for scene_path in scene_paths:
        try:
            scene_id, metadata = _read_safe_metadata(scene_path)
        except (FileNotFoundError, ValueError, zipfile.BadZipFile) as exc:
            scene_read_errors.append(f"{scene_path}: {exc}")
            continue
        scene_bbox = metadata.get("bbox")
        if not _is_bbox(scene_bbox):
            scene_read_errors.append(f"{scene_path}: missing or invalid bbox")
            continue
        valid_scene_count += 1
        if not _bbox_intersects(dem_bbox, scene_bbox):
            errors.append(
                "DEM does not overlap Sentinel-1 scene coverage: "
                f"dem_file={dem_file!r}, dem_bbox={dem_bbox}, "
                f"scene={scene_id!r}, scene_bbox={scene_bbox}. "
                "Use a DEM covering the Sentinel-1 AOI before running ISCE2."
            )
    if valid_scene_count == 0 and scene_read_errors:
        errors.append(
            "Cannot verify DEM coverage because Sentinel-1 scene bounds could not be read: "
            + "; ".join(scene_read_errors[:3])
        )
    return errors


def _run_workflow_isce2(project: Project, dry_run: bool) -> dict:
    """Launch an ISCE2 workflow (topsApp.py or stackSentinel.py)."""
    params = project.runconfig

    # Validate required fields
    errors = isce2_validate_params(params, project.workflow)
    if errors:
        return {
            "error": "params_invalid",
            "message": "ISCE2 project parameters have validation errors — fix them before running.",
            "errors": errors,
        }

    if not dry_run:
        existing_job = _find_reusable_workflow_job(project)
        if existing_job is not None:
            return {
                **_job_result(existing_job),
                "dry_run": False,
                "deduplicated": True,
                "poll": f"insar_get_job(job_id='{existing_job.job_id}', project_id='{project.project_id}')",
                "message": "Existing workflow job found for this project; not launching a duplicate process.",
            }

    errors = _validate_isce2_safe_annotation_geolocation(params, project.workflow)
    errors.extend(_validate_isce2_dem_scene_overlap(params, project.workflow))
    if errors:
        return {
            "error": "params_invalid",
            "message": "ISCE2 project parameters have validation errors — fix them before running.",
            "errors": errors,
        }

    configs_dir: Path | None = None
    _isce2_layout: RunLayout | None = None

    if project.workflow == "tops":
        # Apply run-root layout so ISCE2 native outputs (merged/, geom_reference/, etc.)
        # land inside <run_root>/ rather than scattering at workspace root.
        _isce2_layout = _resolve_run_layout(project)
        if _isce2_layout:
            _isce2_layout.run_root.mkdir(parents=True, exist_ok=True)
            _isce2_layout.logs_dir.mkdir(parents=True, exist_ok=True)
            configs_dir = _isce2_layout.configs_dir
        else:
            configs_dir = project.configs_dir()
        configs_dir.mkdir(parents=True, exist_ok=True)
        isce2_work_dir = str(_isce2_layout.run_root) if _isce2_layout else project.workspace_root

        try:
            dem_root = _isce2_layout.run_root if _isce2_layout else Path(project.workspace_root)
            dem_file = materialize_dem_for_tops(params["dem_file"], dem_root)
            xml_content = build_topsapp_xml({**params, "dem_file": dem_file})
        except Exception as exc:
            return {"error": "config_generation_failed", "message": str(exc)}

        config_path = configs_dir / "topsApp.xml"
        config_path.write_text(xml_content)
        project.runconfig_exported_path = str(config_path)
        project.save()

        command = isce2_build_workflow_command(
            workflow="tops",
            config_path=str(config_path),
            conda_env=project.conda_env,
            do_esd=params.get("do_esd"),
        )

    elif project.workflow == "stack":
        # stackSentinel.py args are passed directly (no config file)
        # Apply run-root layout: work_dir = <run_root>/stack to avoid scatter at workspace root
        _isce2_layout = _resolve_run_layout(project)
        isce2_work_dir = str(_isce2_layout.stack_dir) if _isce2_layout else project.workspace_root
        if _isce2_layout:
            _isce2_layout.stack_dir.mkdir(parents=True, exist_ok=True)
            _isce2_layout.logs_dir.mkdir(parents=True, exist_ok=True)
        command = isce2_build_stack_command(
            params=params,
            work_dir=isce2_work_dir,
            conda_env=project.conda_env,
        )
        config_path = None

    else:
        return {"error": "workflow_not_found", "message": f"Unknown ISCE2 workflow: {project.workflow!r}"}

    # Build Job — include run-layout metadata when available (both tops and stack)
    if _isce2_layout is not None:
        job = Job(
            project_id=project.project_id,
            engine=project.engine,
            workflow=project.workflow,
            command=command,
            runconfig_path=str(config_path) if config_path else "",
            task_id=_isce2_layout.task_id,
            run_id=_isce2_layout.run_id,
            run_root=str(_isce2_layout.run_root),
            logs_dir=str(_isce2_layout.logs_dir),
            tool_name="insar_run_workflow",
            job_type=f"{project.engine}_{project.workflow}_workflow",
        )
        _logs_dir = _isce2_layout.logs_dir
    else:
        job = Job(
            project_id=project.project_id,
            engine=project.engine,
            workflow=project.workflow,
            command=command,
            runconfig_path=str(config_path) if config_path else "",
            tool_name="insar_run_workflow",
            job_type=f"{project.engine}_{project.workflow}_workflow",
        )
        _logs_dir = project.logs_dir()

    log_path = str(_logs_dir / f"{job.job_id}.log")
    exit_code_path = str(_logs_dir / f"{job.job_id}.exitcode")
    job.log_path = log_path
    job.exit_code_path = exit_code_path

    if dry_run:
        result: dict = {
            "job_id": job.job_id,
            "project_id": project.project_id,
            "command": command,
            "status": "dry_run",
            "dry_run": True,
        }
        if _isce2_layout is not None:
            result["run_root"] = str(_isce2_layout.run_root)
            if project.workflow == "stack":
                result["stack_dir"] = str(_isce2_layout.stack_dir)
        return result

    _logs_dir.mkdir(parents=True, exist_ok=True)
    project.outputs_dir().mkdir(parents=True, exist_ok=True)

    job.started_at = _utc_now()
    job.status = "running"
    job.save(project.jobs_dir())

    try:
        shell_command = (
            f"{shlex.join(command)}; "
            f"status=$?; "
            f"printf '%s' \"$status\" > {shlex.quote(exit_code_path)}; "
            f"exit $status"
        )
        job.pid = _launch_detached_shell_job(
            shell_command,
            cwd=isce2_work_dir,
            env=_conda_safe_env(),
            log_path=log_path,
        )
        job.save(project.jobs_dir())
    except Exception as exc:
        job.status = "failed"
        job.finished_at = _utc_now()
        job.exit_code = -1
        job.save(project.jobs_dir())
        return {"error": "launch_failed", "message": str(exc)}

    response: dict = {
        "job_id": job.job_id,
        "project_id": project.project_id,
        "command": command,
        "status": "running",
        "pid": job.pid,
        "submitted_at": job.submitted_at,
        "log_path": log_path,
        "dry_run": False,
        "poll": f"insar_get_job(job_id='{job.job_id}', project_id='{project.project_id}')",
    }
    if _isce2_layout is not None:
        response["run_root"] = str(_isce2_layout.run_root)
    return response


@mcp.tool()
def insar_run_workflow(project_id: str, dry_run: bool = False, conda_env: str = "") -> dict:
    """
    Validate, export, and launch the ISCE3 NISAR workflow.

    Automatically validates the runconfig and writes the YAML to disk before
    launching. No separate validate or export step is needed.
    Execution happens inside the project's configured conda environment.

    Args:
        project_id: Project UUID
        dry_run: If true, validate and export but do not launch the process
        conda_env: Optional conda env override; when provided, updates the project's conda_env in place (avoids re-creating the project just to fix the env).
    """
    try:
        project = Project.load(project_id)
    except (KeyError, FileNotFoundError):
        return _project_error(project_id)

    if conda_env.strip() and conda_env.strip() != (project.conda_env or ""):
        project.conda_env = conda_env.strip()
        try:
            project.save()
        except Exception:
            pass  # in-memory override still applies to this run

    # Dispatch to engine-specific run logic
    if project.engine == "isce2":
        return _run_workflow_isce2(project, dry_run)
    if project.engine == "isce3" and project.workflow == "stack":
        return {
            "error": "workflow_not_runnable",
            "message": "ISCE3 stack projects are managed through insar_prepare_stack, insar_prepare_network, insar_run_batch, and MintPy tools, not insar_run_workflow.",
            "project_id": project_id,
        }

    # Resolve run layout (enforces workspace_root structure, generates run_id)
    run_layout = _resolve_run_layout(project)
    if run_layout is not None:
        _apply_run_layout_to_runconfig(project, run_layout)
    else:
        # Fallback for legacy projects with non-conforming workspace_root
        _ensure_project_logging(project)
        _normalize_isce3_output_paths(project)

    if run_layout is not None:
        _param_tuned_path = run_layout.param_tuned_dir / "runconfig.yaml"
    else:
        _task_dir = (Path(project.workspace_root) / project.task_id) if project.task_id else Path(project.workspace_root)
        _param_tuned_path = _task_dir / "param_tuned" / "runconfig.yaml"
    _param_tuned_found = _param_tuned_path.exists()
    # Step 1: validate
    errors = validate_runconfig(project.runconfig, project.workflow)
    if errors:
        return {
            "error": "runconfig_invalid",
            "message": "Runconfig has validation errors — fix them before running.",
            "errors": errors,
        }

    # Step 2: export YAML into run_root/configs/ (run-specific) or task-level configs/
    if run_layout is not None:
        auth_configs_dir = run_layout.configs_dir
    else:
        auth_configs_dir = project.configs_dir()

    try:
        auth_configs_dir.mkdir(parents=True, exist_ok=True)
        yaml_path = auth_configs_dir / "runconfig.yaml"
        yaml_content = yaml.dump(project.runconfig, default_flow_style=False, allow_unicode=True)
        yaml_path.write_text(yaml_content)
    except Exception as exc:
        return {"error": "export_failed", "message": str(exc)}

    project.runconfig_exported_path = str(yaml_path)
    project.save()
    runconfig_path = str(yaml_path)

    command = build_workflow_command(
        workflow=project.workflow,
        runconfig_path=runconfig_path,
        conda_env=project.conda_env,
    )

    if run_layout is not None:
        logs_dir = run_layout.logs_dir
        logs_dir.mkdir(parents=True, exist_ok=True)
        expected_output = str(run_layout.products_dir / f"{run_layout.run_id}_GUNW.h5")
        job = Job(
            project_id=project.project_id,
            engine=project.engine,
            workflow=project.workflow,
            command=command,
            runconfig_path=runconfig_path,
            task_id=run_layout.task_id,
            run_id=run_layout.run_id,
            run_root=str(run_layout.run_root),
            products_dir=str(run_layout.products_dir),
            scratch_dir=str(run_layout.scratch_dir),
            configs_dir=str(run_layout.configs_dir),
            logs_dir=str(run_layout.logs_dir),
            metrics_path=str(run_layout.metrics_dir / "product_metrics.json"),
            output_paths=[expected_output],
            tool_name="insar_run_workflow",
            job_type=f"{project.engine}_{project.workflow}_workflow",
        )
    else:
        logs_dir = project.logs_dir()
        expected_output = None
        job = Job(
            project_id=project.project_id,
            engine=project.engine,
            workflow=project.workflow,
            command=command,
            runconfig_path=runconfig_path,
            tool_name="insar_run_workflow",
            job_type=f"{project.engine}_{project.workflow}_workflow",
        )

    log_path = str(logs_dir / f"{job.job_id}.log")
    exit_code_path = str(logs_dir / f"{job.job_id}.exitcode")
    job.log_path = log_path
    job.exit_code_path = exit_code_path

    if dry_run:
        result: dict = {
            "job_id": job.job_id,
            "project_id": project_id,
            "command": command,
            "status": "dry_run",
            "dry_run": True,
            "param_tuned_found": _param_tuned_found,
            "param_tuned_config": str(_param_tuned_path) if _param_tuned_found else None,
        }
        if run_layout is not None:
            result.update({
                "run_root": str(run_layout.run_root),
                "products_dir": str(run_layout.products_dir),
                "scratch_dir": str(run_layout.scratch_dir),
                "configs_dir": str(run_layout.configs_dir),
                "expected_output": expected_output,
            })
        return result

    logs_dir.mkdir(parents=True, exist_ok=True)
    project.outputs_dir().mkdir(parents=True, exist_ok=True)

    job.started_at = _utc_now()
    job.status = "running"
    job.save(project.jobs_dir())

    try:
        shell_command = (
            f"{shlex.join(command)}; "
            f"status=$?; "
            f"printf '%s' \"$status\" > {shlex.quote(exit_code_path)}; "
            f"exit $status"
        )
        job.pid = _launch_detached_shell_job(
            shell_command,
            cwd=project.workspace_root,
            env=_conda_safe_env(),
            log_path=log_path,
        )
        job.save(project.jobs_dir())
    except Exception as exc:
        job.status = "failed"
        job.finished_at = _utc_now()
        job.exit_code = -1
        job.save(project.jobs_dir())
        return {"error": "launch_failed", "message": str(exc)}

    result = {
        "job_id": job.job_id,
        "project_id": project_id,
        "command": command,
        "status": "running",
        "pid": job.pid,
        "submitted_at": job.submitted_at,
        "log_path": log_path,
        "dry_run": False,
        "poll": f"insar_get_job(job_id='{job.job_id}', project_id='{project_id}')",
        "param_tuned_found": _param_tuned_found,
        "param_tuned_config": str(_param_tuned_path) if _param_tuned_found else None,
    }
    if run_layout is not None:
        result.update({
            "run_root": str(run_layout.run_root),
            "products_dir": str(run_layout.products_dir),
            "scratch_dir": str(run_layout.scratch_dir),
            "configs_dir": str(run_layout.configs_dir),
            "expected_output": expected_output,
        })
    return result


def _resolve_bbox_input(
    *,
    bbox: list[float] | None,
    aoi_path: str,
) -> tuple[float, float, float, float]:
    has_bbox = bbox is not None
    has_aoi = bool(aoi_path.strip())

    if has_bbox == has_aoi:
        raise ValueError("Provide exactly one of bbox or aoi_path")

    if has_bbox:
        assert bbox is not None
        if len(bbox) != 4:
            raise ValueError("bbox must be [min_lon, min_lat, max_lon, max_lat]")
        values = tuple(float(value) for value in bbox)
        if values[0] >= values[2] or values[1] >= values[3]:
            raise ValueError("bbox must satisfy min_lon < max_lon and min_lat < max_lat")
        return values

    path = Path(aoi_path)
    if not path.exists():
        raise FileNotFoundError(str(path))
    return resolve_aoi_bbox(path)


@mcp.tool()
def insar_export_geotiff(h5_path: str, output_dir: str = "") -> dict:
    """
    Export InSAR rasters to QGIS-ready (CRS-bearing) GeoTIFF.

    Accepts a file OR a directory:
      - NISAR GUNW .h5            -> per-dataset GeoTIFF + colour PNG under browse/ (now georeferenced)
      - MintPy .h5 / mintpy dir   -> velocity, temporalCoherence, masks (+ masked velocity);
                                     ISCE2 radar-coordinate products are auto-geocoded first
      - ISCE2 .geo / .geo.vrt     -> already-geocoded layers
    Unsupported formats (e.g. GAMMA) are reported in `notes`, not exported.

    output_dir: where outputs are written. When omitted, defaults to the run's
    qgis_export/ directory derived from the path.

    Requires GDAL + h5py — run inside the isce2/isce3 conda environment.
    """
    src = Path(h5_path)
    if not src.exists():
        return {"error": "path_not_found", "message": f"File not found: {h5_path!r}"}

    # Default output: the run's qgis_export/ when omitted.
    out = output_dir.strip()
    if not out:
        rr = infer_run_root(src)
        out = str((rr / "qgis_export") if rr is not None else (src.parent / "qgis_export"))

    # GUNW .h5 keeps its browse/+PNG behavior via export_geotiff (now georeferenced).
    # An .h5 file routes here unless it is positively a MintPy/geocoded geo_h5
    # (which the general exporter handles); files h5py cannot open default to GUNW
    # so the export_geotiff path (and its tests) still apply.
    if src.is_file() and src.suffix.lower() in (".h5", ".hdf5", ".he5"):
        is_geo_h5 = False
        try:
            import h5py
            with h5py.File(src, "r") as f:
                is_geo_h5 = "X_FIRST" in f.attrs
        except Exception:
            is_geo_h5 = False
        if not is_geo_h5:
            try:
                result = export_geotiff(h5_path=str(src), output_dir=out)
            except RuntimeError as exc:
                return {"error": "dependency_missing", "message": str(exc)}
            except Exception as exc:  # noqa: BLE001
                return {"error": "export_failed", "message": str(exc)}
            return {
                "output_dir": result["output_dir"],
                "n_files": len(result["files"]),
                "files": result["files"],
                "skipped": result["skipped"],
            }

    # Everything else (MintPy dir/.h5, ISCE2 .geo, single rasters) -> general exporter.
    from insar_agent.engines import raster_export
    try:
        return raster_export.export_path(src, out, tag="E")
    except RuntimeError as exc:
        return {"error": "dependency_missing", "message": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"error": "export_failed", "message": str(exc)}


@mcp.tool()
def insar_run_mintpy(
    mintpy_work_dir: str,
    gunw_glob: str,
    dem_path: str,
    conda_env: str,
    mintpy_config: str = "",
    python_bin: str | None = None,
    smallbaseline_bin: str | None = None,
    interaction_mode: str = "interactive",
) -> dict:
    """Launch MintPy time-series processing asynchronously.

    Wraps run_mintpy_nisar_stack.sh inside the given conda environment.
    stdout and stderr are written to <mintpy_work_dir>/logs/<job_id>.log.

    Args:
        mintpy_work_dir: Output directory for MintPy results.
        gunw_glob:       Shell glob pattern matching GUNW .h5 files,
                         e.g. /path/to/network/runs/*/products/*.h5
        dem_path:        Path to the DEM GeoTIFF used during preprocessing.
        conda_env:       Conda environment that contains MintPy and GDAL.
        mintpy_config:   Path to MintPy smallbaselineApp config (.cfg or .txt).
                         Optional — a minimal NISAR default is auto-generated if omitted.
    """
    try:
        interaction_mode = _normalize_interaction_mode(interaction_mode)
    except ValueError as exc:
        return {"error": "invalid_input", "message": str(exc)}

    if not gunw_glob.strip():
        return {"error": "invalid_input", "message": "gunw_glob must not be empty"}

    if not Path(dem_path).exists():
        return {"error": "path_not_found", "message": f"dem_path not found: {dem_path!r}"}

    if mintpy_config and mintpy_config.strip() and not Path(mintpy_config).exists():
        return {"error": "path_not_found", "message": f"mintpy_config not found: {mintpy_config!r}"}

    try:
        result = run_mintpy(
            mintpy_work_dir=mintpy_work_dir,
            gunw_glob=gunw_glob,
            mintpy_config=mintpy_config or None,
            dem_path=dem_path,
            conda_env=conda_env,
            python_bin=python_bin,
            smallbaseline_bin=smallbaseline_bin,
        )
    except FileNotFoundError as exc:
        return {"error": "path_not_found", "message": str(exc)}
    except Exception as exc:
        return {"error": "launch_failed", "message": str(exc)}

    job_id = result["job_id"]
    response: dict = {
        "job_id": job_id,
        "pid": result["pid"],
        "status": result["status"],
        "interaction_mode": interaction_mode,
        "log_path": result["log_path"],
        "submitted_at": result["submitted_at"],
        "command": shlex.join(result.get("command", [])) if result.get("command") else "",
        "progress_hint": (
            f"Poll via insar_get_job(job_id='{job_id}', work_dir='{mintpy_work_dir}'); "
            "if the job fails, call the same tool with include_logs=True."
        ),
        "poll": f"insar_get_job(job_id='{job_id}', work_dir='{mintpy_work_dir}')",
        "work_dir": mintpy_work_dir,
    }
    # Warn if mintpy_work_dir is too shallow for run-root layout
    _workspace_guess = Path(mintpy_work_dir).parent
    _depth_warn = _check_output_dir_depth(mintpy_work_dir, _workspace_guess.parent, "mintpy")
    if _depth_warn:
        response["layout_warning"] = (
            _depth_warn + " Recommended: <workspace>/<task_id>/outputs/<run_id>/mintpy"
        )
    return response


@mcp.tool()
def insar_run_mintpy_isce2(
    mintpy_work_dir: str,
    stack_work_dir: str,
    conda_env: str = "isce2",
    mintpy_config: str = "",
    python_bin: str | None = None,
    smallbaseline_bin: str | None = None,
    interaction_mode: str = "interactive",
) -> dict:
    """Launch MintPy asynchronously on an ISCE2/topsStack-style Sentinel workspace.

    Uses prep_isce.py plus smallbaselineApp.py against a completed ISCE2 stack
    directory containing merged/interferograms, merged/geom_reference,
    topsStack baseline text files or baseline rasters, and reference/IW*.xml.
    """
    try:
        interaction_mode = _normalize_interaction_mode(interaction_mode)
    except ValueError as exc:
        return {"error": "invalid_input", "message": str(exc)}

    stack_dir = Path(stack_work_dir)
    if not stack_dir.exists():
        return {"error": "path_not_found", "message": f"stack_work_dir not found: {stack_work_dir!r}"}

    workspace_error = _validate_same_opencode_session_workspace(stack_work_dir, mintpy_work_dir)
    if workspace_error:
        return {"error": "invalid_input", "message": workspace_error}

    try:
        result = run_mintpy_isce2_stack(
            mintpy_work_dir=mintpy_work_dir,
            stack_work_dir=stack_work_dir,
            conda_env=conda_env,
            mintpy_config=mintpy_config or None,
            python_bin=python_bin,
            smallbaseline_bin=smallbaseline_bin,
        )
    except FileNotFoundError as exc:
        return {"error": "path_not_found", "message": str(exc)}
    except Exception as exc:
        return {"error": "launch_failed", "message": str(exc)}

    job_id = result["job_id"]
    isce2_mintpy_response: dict = {
        "job_id": job_id,
        "pid": result["pid"],
        "status": result["status"],
        "interaction_mode": interaction_mode,
        "log_path": result["log_path"],
        "submitted_at": result["submitted_at"],
        "command": shlex.join(result.get("command", [])) if result.get("command") else "",
        "mintpy_config": result.get("mintpy_config", ""),
        "progress_hint": (
            f"Poll via insar_get_job(job_id='{job_id}', work_dir='{mintpy_work_dir}'); "
            "if the job fails, call the same tool with include_logs=True."
        ),
        "poll": f"insar_get_job(job_id='{job_id}', work_dir='{mintpy_work_dir}')",
        "work_dir": mintpy_work_dir,
        "stack_work_dir": stack_work_dir,
    }
    # Warn if mintpy_work_dir is too shallow for run-root layout
    _depth_warn = _check_output_dir_depth(mintpy_work_dir, Path(mintpy_work_dir).parent.parent, "mintpy")
    if _depth_warn:
        isce2_mintpy_response["layout_warning"] = (
            _depth_warn + " Recommended: <workspace>/<task_id>/outputs/<run_id>/mintpy"
        )
    return isce2_mintpy_response


@mcp.tool()
def insar_plot_baseline(
    network_dir: str,
    pair_list: str = "",
    title: str = "ISCE3 Spatiotemporal Baseline Network",
    interaction_mode: str = "interactive",
) -> dict:
    """Generate a spatiotemporal baseline network plot and CSV files.

    Reads GUNW products from the interferogram network directory produced by
    insar_prepare_network.  Outputs PNG, PDF, and two CSV files.

    Args:
        network_dir: Network output directory containing runs/ and pair_lists/.
        pair_list:   Path to a pair-list file (YYYYMMDD_YYYYMMDD per line).
                     Leave empty to use pair_lists/pairs_selected.txt.
        title:       Figure title.
    """
    try:
        interaction_mode = _normalize_interaction_mode(interaction_mode)
    except ValueError as exc:
        return {"error": "invalid_input", "message": str(exc)}

    if not Path(network_dir).exists():
        return {
            "error": "path_not_found",
            "message": f"network_dir not found: {network_dir!r}",
        }

    pair_list_arg: str | None = pair_list if pair_list.strip() else None
    if pair_list_arg is not None and not Path(pair_list_arg).exists():
        return {
            "error": "path_not_found",
            "message": f"pair_list not found: {pair_list_arg!r}",
        }

    try:
        result = plot_baseline_network(
            network_dir=network_dir,
            pair_list=pair_list_arg,
            title=title,
        )
    except FileNotFoundError as exc:
        return {"error": "path_not_found", "message": str(exc)}
    except RuntimeError as exc:
        return {"error": "dependency_missing", "message": str(exc)}
    except Exception as exc:
        return {"error": "plot_failed", "message": str(exc)}

    response = {
        "png_path": result["png_path"],
        "pdf_path": result["pdf_path"],
        "pair_csv": result["pair_csv"],
        "scene_csv": result["scene_csv"],
        "n_pairs": result["n_pairs"],
    }
    response.update(
        _prepare_handoff(
            interaction_mode=interaction_mode,
            handoff_reason=(
                "Review the baseline plot and CSV summaries before proceeding to MintPy. "
                "If pair selection needs adjustment, return to network preparation."
            ),
            review_artifacts=[
                result["png_path"],
                result["pdf_path"],
                result["pair_csv"],
                result["scene_csv"],
            ],
            next_recommended_action=(
                "If accepted, call insar_run_mintpy(...) with the same interaction_mode."
            ),
        )
    )
    return response


@mcp.tool()
def insar_download_rslc(
    urls: list[str],
    output_dir: str = "",
    bbox: list[float] | None = None,
    aoi_path: str = "",
    freq: str = "A",
    margin: int = 20,
    n_workers: int = 8,
    chunk_rows: int = 256,
    proxy: str | None = None,
    workspace_root: str = "",
    task_id: str = "",
    run_id: str = "",
    confirm: bool = False,
) -> dict:
    """Download and bbox-crop NISAR RSLC files from NASA Earthdata (ASF).

    Performs remote cropping via HDF5 byte-range requests — only the pixels
    inside the bbox are downloaded, saving bandwidth and disk space.
    By default the download process inherits the current system proxy settings.
    Pass proxy when you want a temporary override for the download process only.
    Authentication uses ~/.netrc (urs.earthdata.nasa.gov).

    Args:
        urls:       List of remote .h5 RSLC URLs from ASF EarthData.
        output_dir: Local directory to write cropped files.
        bbox:       Optional [min_lon, min_lat, max_lon, max_lat] in decimal degrees.
        aoi_path:   Optional path to an AOI file; mutually exclusive with bbox.
        freq:       NISAR frequency band: 'A' (L-band) or 'B'.
        margin:     Extra pixel margin around the bbox crop window (default 20).
        n_workers:  Parallel download threads per file (default 8).
        chunk_rows: Azimuth chunk size per thread (default 256).
        proxy:      Optional HTTP proxy URL, e.g. "http://10.0.0.1:7890".
                    If omitted, the download process inherits current system
                    proxy settings. If provided, it is applied only to this
                    download process.
        workspace_root: Top-level workspace root for task-level job tracking.
        task_id:    Workflow task_id for task-level job tracking.
        run_id:     Optional run identifier used to derive output_dir if omitted.
        confirm:    Set to True to proceed with a full-frame download when
                    neither bbox nor aoi_path is provided. Default False.

    Returns:
        {
            "ok": [{"url": ..., "path": ..., "size_mb": ...}, ...],
            "failed": [{"url": ..., "error": ...}, ...],
            "output_dir": str,
        }
    """
    full_frame = bbox is None and not aoi_path.strip()
    if full_frame and not confirm:
        return {
            "status": "confirmation_required",
            "message": (
                "No AOI or bbox provided — this will download the full frame "
                "for each scene (potentially 10+ GB per file). "
                "Pass confirm=True to proceed."
            ),
            "hint": "insar_download_rslc(..., confirm=True)",
        }

    resolved_bbox: tuple[float, float, float, float] | None
    if full_frame:
        resolved_bbox = None
    else:
        try:
            resolved_bbox = _resolve_bbox_input(bbox=bbox, aoi_path=aoi_path)
        except FileNotFoundError as exc:
            return {"error": "path_not_found", "message": str(exc)}
        except ValueError as exc:
            return {"error": "invalid_input", "message": str(exc)}
        except Exception as exc:
            return {"error": "bbox_failed", "message": str(exc)}

    h5_urls = [u for u in urls if u.endswith(".h5") and "RSLC" in u]
    if not h5_urls:
        return {"error": "invalid_input", "message": "No RSLC .h5 URLs found in the provided list"}

    if not output_dir.strip():
        if workspace_root.strip() and task_id.strip():
            _rid = _resolve_task_run_id(workspace_root, task_id, run_id)
            layout = RunLayout(workspace_root=workspace_root, task_id=task_id, run_id=_rid or None)
            output_dir = str(layout.run_root / "rslc")
        else:
            return {
                "error": "missing_input",
                "message": "Either output_dir or both workspace_root and task_id must be provided.",
            }
    output_dir_path = Path(output_dir).expanduser().resolve()
    output_dir = str(output_dir_path)
    job_context = _task_job_context(workspace_root=workspace_root, task_id=task_id, path=output_dir_path)
    if job_context is None:
        return {
            "error": "missing_task_context",
            "message": "Background RSLC downloads must be associated with <workspace>/<task_id>; provide workspace_root and task_id or an output_dir under outputs/<run_id>.",
        }

    params = {
        "urls": h5_urls,
        "bbox": list(resolved_bbox) if resolved_bbox is not None else None,
        "output_dir": output_dir,
        "freq": freq,
        "margin": margin,
        "n_workers": n_workers,
        "chunk_rows": chunk_rows,
        "proxy": proxy,
    }
    dl_job = DownloadJob(
        output_dir=output_dir,
        n_files=len(h5_urls),
        task_id=job_context.get("task_id"),
        run_id=job_context.get("run_id"),
        run_root=job_context.get("run_root"),
        tool_name="insar_download_rslc",
        job_type="rslc_download",
    )
    job_id = dl_job.job_id
    logs_dir = _run_root_logs_dir(output_dir_path) or (output_dir_path / "logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path_obj = logs_dir / f"nisar_download_{job_id}.log"
    params_path = logs_dir / f"nisar_download_{job_id}_params.json"
    log_path_obj.touch()
    params_path.write_text(json.dumps(params, indent=2, ensure_ascii=False), encoding="utf-8")
    log_path = str(log_path_obj)
    params_file = str(params_path)
    runner_file = str(logs_dir / f"nisar_download_{job_id}_run.py")
    dl_job.log_path = log_path
    dl_job.params_path = params_file

    src_dir = str(Path(__file__).resolve().parent.parent.parent)
    runner_script = f"""\
import sys, json, traceback
sys.path.insert(0, {repr(src_dir)})
from insar_agent.engines.isce3.download import download_rslc_stack

with open({repr(params_file)}) as _f:
    _p = json.load(_f)
if _p["bbox"] is not None:
    _p["bbox"] = tuple(_p["bbox"])
_p["on_progress"] = lambda msg: (print(msg, flush=True))

try:
    _result = download_rslc_stack(**_p)
    print(json.dumps({{"status": "done", "result": _result}}), flush=True)
except Exception as _e:
    print(json.dumps({{"status": "failed", "error": str(_e), "traceback": traceback.format_exc()}}), flush=True)
"""
    with open(runner_file, "w") as f:
        f.write(runner_script)

    try:
        with open(log_path, "w") as log_file:
            proc = subprocess.Popen(
                [sys.executable, runner_file],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except Exception as exc:
        return {"error": "launch_failed", "message": str(exc)}

    dl_job.pid = proc.pid
    dl_job.save(Path(job_context["jobs_dir"]))

    return {
        "job_id": job_id,
        "status": "running",
        "pid": proc.pid,
        "n_files": len(h5_urls),
        "output_dir": output_dir,
        "log_path": log_path,
        "params_path": params_file,
        "workspace_root": job_context.get("workspace_root"),
        "task_id": job_context.get("task_id"),
        "run_id": job_context.get("run_id"),
        "run_root": job_context.get("run_root"),
        "poll": _task_job_poll(job_id, job_context),
    }


def _find_isce2_gdal2isce_xml() -> Path | None:
    return next(
        (
            path
            for path in (Path.home() / "miniconda3" / "envs" / "isce2" / "lib").glob(
                "python*/site-packages/isce/applications/gdal2isce_xml.py"
            )
        ),
        None,
    )


def _ensure_isce2_dem_xml(dem_path: Path, log_path: Path) -> str | None:
    xml_path = dem_path.with_name(dem_path.name + ".xml")
    if xml_path.exists():
        return str(xml_path)

    script = _find_isce2_gdal2isce_xml()
    if script is None:
        _append_log(log_path, "ISCE2 gdal2isce_xml.py not found; DEM XML sidecar was not generated.")
        return None

    command = [
        "conda",
        "run",
        "-n",
        "isce2",
        "python",
        str(script),
        "-i",
        str(dem_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=120, env=_conda_safe_env())
    if result.stdout.strip():
        _append_log(log_path, result.stdout.strip())
    if result.stderr.strip():
        _append_log(log_path, result.stderr.strip())
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "ISCE2 DEM XML generation failed"
        raise RuntimeError(message)
    if not xml_path.exists():
        raise RuntimeError(f"ISCE2 DEM XML generation did not create {xml_path}")
    return str(xml_path)


@mcp.tool()
def insar_download_dem(
    output_path: str = "",
    bbox: list[float] | None = None,
    aoi_path: str = "",
    source: str = "copernicus_30",
    margin_deg: float = 0.1,
    proxy: str | None = None,
    backend: str = "general",
    dem_type: str | None = None,
    workspace_root: str = "",
    task_id: str = "",
    run_id: str = "",
    background: bool = False,
) -> dict:
    """Download a DEM covering the given bbox or AOI file.

    Args:
        output_path: Destination path for the downloaded DEM.  When omitted,
            defaults under ``<workspace_root>/<task_id>/outputs/<run_id>/dem/``
            if workspace_root and task_id are provided.
        workspace_root: Top-level workspace root.  Used only to derive the
            default output_path when output_path is omitted.
        task_id: Workflow task_id (e.g. ``"d-insar-isce3"``).  Used only to
            derive the default output_path when output_path is omitted.
        run_id: Optional run identifier used with workspace_root/task_id.
        background: If true, launch the DEM download as a background job and poll with insar_get_job.
    """
    if not output_path.strip():
        if workspace_root.strip() and task_id.strip():
            _rid = _resolve_task_run_id(workspace_root, task_id, run_id)
            layout = RunLayout(workspace_root=workspace_root, task_id=task_id, run_id=_rid or None)
            output_path = str(layout.dem_dir / f"{source}_dem.tif")
            workspace_root = str(layout.workspace_root)
            task_id = layout.task_id
            run_id = layout.run_id
        else:
            return {
                "error": "missing_input",
                "message": "Either output_path or both workspace_root and task_id must be provided.",
            }
    else:
        output_path, workspace_root, task_id, run_id = _honor_output_path(
            output_path,
            workspace_root=workspace_root,
            task_id=task_id,
            run_id=run_id,
        )

    try:
        resolved_bbox = _resolve_bbox_input(bbox=bbox, aoi_path=aoi_path)
    except FileNotFoundError as exc:
        return {"error": "path_not_found", "message": str(exc)}
    except ValueError as exc:
        return {"error": "invalid_input", "message": str(exc)}
    except Exception as exc:
        return {"error": "bbox_failed", "message": str(exc)}

    if background:
        return _launch_dem_download_background({
            "output_path": output_path,
            "bbox": list(resolved_bbox),
            "aoi_path": "",
            "source": source,
            "margin_deg": margin_deg,
            "proxy": proxy,
            "backend": backend,
            "dem_type": dem_type,
            "workspace_root": workspace_root,
            "task_id": task_id,
            "run_id": run_id,
        })

    params = {
        "output_path": output_path,
        "bbox": list(bbox) if bbox is not None else None,
        "aoi_path": aoi_path,
        "source": source,
        "margin_deg": margin_deg,
        "proxy": proxy,
        "backend": backend,
        "dem_type": dem_type,
        "run_id": run_id,
    }
    _, log_path, params_path = _prepare_tool_log(
        [output_path, aoi_path],
        "sentinel_dem",
        params,
        fallback_root=Path(output_path).expanduser().parent,
    )
    messages: list[str] = []
    if backend == "isce2":
        dem_script = next(
            (
                path
                for path in (Path.home() / "miniconda3" / "envs" / "isce2" / "lib").glob(
                    "python*/site-packages/isce/applications/dem.py"
                )
            ),
            None,
        )
        if dem_script is None:
            return {
                "error": "path_not_found",
                "message": "ISCE2 dem.py not found in the isce2 conda environment",
                "log_path": str(log_path),
                "params_path": str(params_path),
            }
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        west, south, east, north = resolved_bbox
        bbox_args = [
            str(math.floor(south)),
            str(math.ceil(north)),
            str(math.floor(west)),
            str(math.ceil(east)),
        ]
        isce2_dem_type = dem_type or (source if source in {"version2", "version3", "nasadem"} else "version3")
        command = [
            "conda",
            "run",
            "-n",
            "isce2",
            "python",
            str(dem_script),
            "-a",
            "stitch",
            "-b",
            *bbox_args,
            "-d",
            str(output.parent),
            "-o",
            output.name,
            "-t",
            isce2_dem_type,
            "-s",
            "1",
            "-r",
        ]
        # Build subprocess env: bypass proxy for NASA EarthData to avoid SSL inspection issues.
        # Includes both the legacy USGS host and the new LP DAAC Earthdata Cloud host.
        isce2_env = _conda_safe_env()
        nasa_hosts = [
            "e4ftl01.cr.usgs.gov",
            "data.lpdaac.earthdatacloud.nasa.gov",
            "urs.earthdata.nasa.gov",
        ]
        existing_no_proxy = isce2_env.get("no_proxy", isce2_env.get("NO_PROXY", ""))
        to_add = [h for h in nasa_hosts if h not in existing_no_proxy]
        if to_add:
            merged = ",".join(filter(None, [existing_no_proxy] + to_add))
            isce2_env["no_proxy"] = merged
            isce2_env["NO_PROXY"] = merged

        attempts = 3
        result = None
        for attempt in range(1, attempts + 1):
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=600, env=isce2_env)
            except FileNotFoundError as exc:
                _append_log(log_path, str(exc))
                return {"error": "path_not_found", "message": str(exc), "log_path": str(log_path), "params_path": str(params_path)}
            except Exception as exc:
                _append_log(log_path, str(exc))
                return {"error": "download_failed", "message": str(exc), "log_path": str(log_path), "params_path": str(params_path)}

            attempt_messages: list[str] = []
            if result.stdout.strip():
                attempt_messages.extend(line for line in result.stdout.splitlines() if line.strip())
            if result.stderr.strip():
                attempt_messages.extend(line for line in result.stderr.splitlines() if line.strip())
            messages.extend(attempt_messages)
            _append_log(log_path, f"attempt {attempt}/{attempts}")
            for line in attempt_messages:
                _append_log(log_path, line)

            if result.returncode == 0 and output.exists():
                break
            if attempt < attempts:
                time.sleep(1)

        assert result is not None
        if result.returncode != 0:
            return {
                "error": "download_failed",
                "message": result.stderr.strip() or result.stdout.strip() or "ISCE2 DEM download failed",
                "backend": backend,
                "command": command,
                "log": messages,
                "log_path": str(log_path),
                "params_path": str(params_path),
            }
        if not output.exists():
            return {
                "error": "download_failed",
                "message": f"ISCE2 DEM backend did not create output: {output}",
                "backend": backend,
                "command": command,
                "log": messages,
                "log_path": str(log_path),
                "params_path": str(params_path),
            }

        return _with_task_root_guard(
            {
                "output_path": str(output),
                "source": isce2_dem_type,
                "bbox": list(resolved_bbox),
                "backend": backend,
                "command": command,
                "log": messages,
                "log_path": str(log_path),
                "params_path": str(params_path),
            },
            workspace_root=workspace_root,
            task_id=task_id,
        )

    try:
        result = download_dem(
            output_path=output_path,
            bbox=resolved_bbox,
            source=source,
            margin_deg=margin_deg,
            on_progress=lambda msg: messages.append(msg),
            proxy=proxy,
        )
    except FileNotFoundError as exc:
        _append_log(log_path, str(exc))
        return {"error": "path_not_found", "message": str(exc), "log_path": str(log_path), "params_path": str(params_path)}
    except ValueError as exc:
        _append_log(log_path, str(exc))
        return {"error": "invalid_input", "message": str(exc), "log_path": str(log_path), "params_path": str(params_path)}
    except RuntimeError as exc:
        _append_log(log_path, str(exc))
        return {"error": "download_failed", "message": str(exc), "log_path": str(log_path), "params_path": str(params_path)}
    except Exception as exc:
        _append_log(log_path, str(exc))
        return {"error": "download_failed", "message": str(exc), "log_path": str(log_path), "params_path": str(params_path)}

    result["backend"] = backend
    result["log"] = messages
    for line in messages:
        _append_log(log_path, line)
    try:
        isce_xml_path = _ensure_isce2_dem_xml(Path(str(result["output_path"])), log_path)
    except RuntimeError as exc:
        _append_log(log_path, str(exc))
        return {"error": "download_failed", "message": str(exc), "log_path": str(log_path), "params_path": str(params_path)}
    if isce_xml_path is not None:
        result["isce_xml_path"] = isce_xml_path
    result["log_path"] = str(log_path)
    result["params_path"] = str(params_path)
    return _with_task_root_guard(result, workspace_root=workspace_root, task_id=task_id)


@mcp.tool()
def insar_prepare_sentinel_data(
    project_root: str = "",
    workspace_root: str = "",
    task_id: str = "",
    run_id: str = "",
    mode: str = "auto",
    aoi_path: str | None = None,
    bbox: list[float] | None = None,
    dem_path: str | None = None,
    dem_output_path: str | None = None,
    download_dem: bool = False,
    dem_backend: str = "general",
    dem_type: str | None = None,
    download_orbits: bool = False,
    orbit_dir: str | None = None,
    orbit_username: str | None = None,
    orbit_password: str | None = None,
    orbit_token_file: str | None = None,
    source_paths: list[str] | None = None,
    burst_manifest: str | None = None,
    include_pair: bool = True,
    include_stack: bool = True,
    resume: bool = True,
    validate_isce2_import: bool = False,
    background: bool = False,
) -> dict:
    """
    Organize Sentinel-1 SAFE inputs into grouped SAFE paths for later ISCE2 use.

    This tool only prepares grouped SAFE outputs. It can organize existing
    SAFE/ZIP inputs or synthesize lightweight SAFE directories from local burst
    files. It can also optionally prepare DEM and Sentinel-1 orbit files for
    downstream ISCE2 workflows. Set validate_isce2_import=True to run an
    import-only Sentinel1_TOPS validation for each prepared SAFE.

    Args:
        project_root: Output directory for prepared SAFE data.  When omitted,
            defaults under ``<workspace_root>/<task_id>/outputs/<run_id>/prep``
            if workspace_root and task_id are provided.
        workspace_root: Top-level workspace root.  Used only to derive the
            default project_root when project_root is omitted.
        task_id: Workflow task_id (e.g. ``"d-insar-isce2"``).  Used only to
            derive the default project_root when project_root is omitted.
        run_id: Optional run identifier used with workspace_root/task_id.
    """
    if not project_root.strip():
        if workspace_root.strip() and task_id.strip():
            _rid = _resolve_task_run_id(workspace_root, task_id, run_id)
            layout = RunLayout(workspace_root=workspace_root, task_id=task_id, run_id=_rid or None)
            project_root = str(layout.run_root / "prep")
            workspace_root = str(layout.workspace_root)
            task_id = layout.task_id
            run_id = layout.run_id
        else:
            return {
                "error": "missing_input",
                "message": "Either project_root or both workspace_root and task_id must be provided.",
            }
    else:
        project_root, workspace_root, task_id, run_id = _honor_output_path(
            project_root,
            workspace_root=workspace_root,
            task_id=task_id,
            run_id=run_id,
        )

    if dem_output_path is not None and dem_output_path.strip():
        dem_output_path, workspace_root, task_id, run_id = _honor_output_path(
            dem_output_path,
            workspace_root=workspace_root,
            task_id=task_id,
            run_id=run_id,
        )

    params = {
        "project_root": project_root,
        "workspace_root": workspace_root,
        "task_id": task_id,
        "run_id": run_id,
        "mode": mode,
        "aoi_path": aoi_path,
        "bbox": bbox,
        "dem_path": dem_path,
        "dem_output_path": dem_output_path,
        "download_dem": download_dem,
        "dem_backend": dem_backend,
        "dem_type": dem_type,
        "download_orbits": download_orbits,
        "orbit_dir": orbit_dir,
        "orbit_username": orbit_username,
        "orbit_password": orbit_password,
        "orbit_token_file": orbit_token_file,
        "source_paths": source_paths,
        "burst_manifest": burst_manifest,
        "include_pair": include_pair,
        "include_stack": include_stack,
        "resume": resume,
        "validate_isce2_import": validate_isce2_import,
    }
    if background:
        return _launch_sentinel_prepare_background(params)

    try:
        result = prepare_sentinel_data(
            project_root=project_root,
            mode=mode,
            aoi_path=aoi_path,
            bbox=bbox,
            dem_path=dem_path,
            dem_output_path=dem_output_path,
            download_dem=download_dem,
            dem_backend=dem_backend,
            dem_type=dem_type,
            download_orbits=download_orbits,
            orbit_dir=orbit_dir,
            orbit_username=orbit_username,
            orbit_password=orbit_password,
            orbit_token_file=orbit_token_file,
            source_paths=source_paths,
            burst_manifest=burst_manifest,
            include_pair=include_pair,
            include_stack=include_stack,
            resume=resume,
            validate_isce2_import=validate_isce2_import,
            dem_downloader=insar_download_dem,
        )
        return _with_task_root_guard(result, workspace_root=workspace_root, task_id=task_id)
    except FileNotFoundError as exc:
        return {"error": "path_not_found", "message": str(exc)}
    except FileExistsError as exc:
        return {"error": "target_exists", "message": str(exc)}
    except ValueError as exc:
        return {"error": "invalid_input", "message": str(exc)}
    except Exception as exc:
        return {"error": "prepare_failed", "message": str(exc)}


# ── CLI / entry points ──────────────────────────────

def build_server_description() -> dict:
    """Return server metadata aligned with the active FastMCP surface."""
    return {
        "server_name": "insar-mcp-server",
        "transport": "stdio",
        "status": "active",
        "engines": ["isce3", "isce2"],
        "tools": [
            "insar_discover",
            "insar_get_project",
            "insar_create_project",
            "insar_get_runconfig",
            "insar_set_runconfig_value",
            "insar_set_processing_param",
            "insar_describe_rslc",
            "insar_run_workflow",
            "insar_get_job",
            "insar_list_outputs",
            "insar_prepare_stack",
            "insar_prepare_network",
            "insar_run_batch",
            "insar_download_rslc",
            "insar_download_dem",
            "insar_export_geotiff",
            "insar_run_mintpy",
            "insar_plot_baseline",
            "insar_download_scene",
            "insar_describe_s1",
            "insar_prepare_sentinel_data",
            "insar_check_env",
            "insar_export_runconfig",
            "insar_run_mintpy_isce2",
        ],
    }


def build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="insar-mcp-server")
    parser.add_argument("--describe", action="store_true", help="Print server metadata as JSON")
    parser.add_argument("--stdio", action="store_true", help="Start stdio MCP server (default)")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_cli()
    args = parser.parse_args(argv)

    if args.describe:
        print(json.dumps(build_server_description(), indent=2))
        return

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
