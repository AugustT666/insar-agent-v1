from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, UTC
from pathlib import Path

import yaml
from mcp.server.fastmcp import FastMCP

from insar_agent.core.config import set_path, unset_path
from insar_agent.core.jobs import Job
from insar_agent.core.project import Project, new_project
from insar_agent.engines.isce3.adapter import ISCE3Adapter
from insar_agent.engines.isce3.defaults import (
    ALLOWED_SET_FIELDS,
    load_default_runconfig,
)
from insar_agent.engines.isce3.network import prepare_network
from insar_agent.engines.isce3.runner import build_workflow_command
from insar_agent.engines.isce3.stack import prepare_stack
from insar_agent.engines.isce3.validator import validate_runconfig

_ADAPTER = ISCE3Adapter()
_ENGINES = {_ADAPTER.name: _ADAPTER}

mcp = FastMCP("insar-mcp-server")


# ── helpers ────────────────────────────────────────────────────────────────────

def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _engine_error(engine: str) -> dict:
    return {"error": "engine_not_found", "message": f"Engine {engine!r} not recognized. Available: {list(_ENGINES)}"}


def _project_error(project_id: str) -> dict:
    return {"error": "project_not_found", "message": f"Project {project_id!r} not found in registry"}


def _job_error(job_id: str) -> dict:
    return {"error": "job_not_found", "message": f"Job {job_id!r} not found"}


# ── Group 1: Discovery ─────────────────────────────────────────────────────────

@mcp.tool()
def insar_list_engines() -> dict:
    """List available InSAR processing engines on this server."""
    return {
        "engines": [
            {
                "name": adapter.name,
                "available": True,
                "description": "ISCE3 / NISAR science processor",
            }
            for adapter in _ENGINES.values()
        ]
    }


@mcp.tool()
def insar_list_workflows(engine: str) -> dict:
    """List supported workflows for the given engine."""
    if engine not in _ENGINES:
        return _engine_error(engine)
    workflows = _ENGINES[engine].list_workflows()
    return {
        "engine": engine,
        "workflows": [
            {
                "workflow": w.workflow,
                "supports_gpu": w.supports_gpu,
                "description": w.description,
            }
            for w in workflows
        ],
    }


@mcp.tool()
def insar_get_project(project_id: str) -> dict:
    """Return project metadata, runconfig key summary, and latest job status."""
    try:
        project = Project.load(project_id)
    except (KeyError, FileNotFoundError):
        return _project_error(project_id)

    def _leaf_keys(d: dict, prefix: str = "") -> list[str]:
        keys = []
        for k, v in d.items():
            full = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                keys.extend(_leaf_keys(v, full))
            else:
                keys.append(full)
        return keys

    runconfig_keys = _leaf_keys(project.runconfig)

    latest_job = None
    jobs_dir = project.jobs_dir()
    if jobs_dir.exists():
        job_files = sorted(jobs_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
        if job_files:
            data = json.loads(job_files[-1].read_text())
            latest_job = {"job_id": data["job_id"], "status": data["status"]}

    return {
        "project_id": project.project_id,
        "name": project.name,
        "engine": project.engine,
        "workflow": project.workflow,
        "workspace_root": project.workspace_root,
        "conda_env": project.conda_env,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
        "runconfig_keys": runconfig_keys,
        "latest_job": latest_job,
    }


# ── Group 2: Config Management (M1) ───────────────────────────────────────────

@mcp.tool()
def insar_create_project(
    engine: str,
    workflow: str,
    workspace_root: str,
    name: str = "",
    conda_env: str = "",
) -> dict:
    """
    Create a new InSAR processing project.

    Initializes the workspace, loads the default runconfig template for the
    chosen workflow, and registers the project for future lookups.

    Args:
        engine: Engine name, e.g. 'isce3'
        workflow: Workflow name, e.g. 'insar' or 'gslc'
        workspace_root: Absolute path where project files will be written
        name: Human-readable project name (auto-generated if omitted)
        conda_env: Conda environment name for workflow execution (e.g. 'isce3')
    """
    if engine not in _ENGINES:
        return _engine_error(engine)

    workflow_names = {w.workflow for w in _ENGINES[engine].list_workflows()}
    if workflow not in workflow_names:
        return {"error": "workflow_not_found", "message": f"Workflow {workflow!r} not found for engine {engine!r}"}

    ws = Path(workspace_root)
    if not ws.exists():
        try:
            ws.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            return {"error": "workspace_not_writable", "message": str(exc)}
    elif not ws.is_dir():
        return {"error": "workspace_not_writable", "message": f"{workspace_root!r} exists but is not a directory"}

    try:
        default_runconfig = load_default_runconfig(workflow)
    except FileNotFoundError as exc:
        return {"error": "template_not_found", "message": str(exc)}

    project_name = name.strip() or f"{engine}-{workflow}-{ws.name}"
    project = new_project(
        name=project_name,
        engine=engine,
        workflow=workflow,
        workspace_root=str(ws.resolve()),
        conda_env=conda_env.strip() or None,
    )
    project.runconfig = default_runconfig
    project.runconfig_template = default_runconfig

    try:
        project.save()
    except Exception as exc:
        return {"error": "workspace_not_writable", "message": str(exc)}

    return {
        "project_id": project.project_id,
        "name": project.name,
        "engine": project.engine,
        "workflow": project.workflow,
        "workspace_root": project.workspace_root,
        "conda_env": project.conda_env,
        "created_at": project.created_at,
    }


@mcp.tool()
def insar_get_runconfig(project_id: str, format: str = "json") -> dict:
    """
    Return the current runconfig for a project.

    Args:
        project_id: Project UUID
        format: 'json' (default) or 'yaml'
    """
    try:
        project = Project.load(project_id)
    except (KeyError, FileNotFoundError):
        return _project_error(project_id)

    if format == "yaml":
        return {
            "project_id": project_id,
            "format": "yaml",
            "runconfig_yaml": yaml.dump(project.runconfig, default_flow_style=False, allow_unicode=True),
        }
    return {
        "project_id": project_id,
        "format": "json",
        "runconfig": project.runconfig,
    }


@mcp.tool()
def insar_set_runconfig_value(project_id: str, key: str, value: object) -> dict:
    """
    Set a value at a dotted key path within the project runconfig.

    Only path-related fields and a small set of worker flags are allowed.
    Core processing parameters cannot be changed through this tool — they must
    be edited manually in the exported YAML.

    Args:
        project_id: Project UUID
        key: Dotted path, e.g. 'runconfig.groups.input_file_group.reference_rslc_file'
        value: New value (string, number, or boolean)
    """
    try:
        project = Project.load(project_id)
    except (KeyError, FileNotFoundError):
        return _project_error(project_id)

    allowed = ALLOWED_SET_FIELDS.get(project.workflow, [])
    if allowed and key not in allowed:
        return {
            "error": "key_not_allowed",
            "message": (
                f"Key {key!r} is not in the allowed set for workflow {project.workflow!r}. "
                "Core processing parameters must be edited manually in the exported YAML. "
                f"Allowed keys: {allowed}"
            ),
        }

    try:
        set_path(project.runconfig, key, value)
    except (KeyError, TypeError) as exc:
        return {"error": "key_invalid", "message": str(exc)}

    try:
        project.save()
    except Exception as exc:
        return {"error": "save_failed", "message": str(exc)}

    return {
        "project_id": project_id,
        "key": key,
        "value": value,
        "updated_at": project.updated_at,
    }


@mcp.tool()
def insar_unset_runconfig_value(project_id: str, key: str) -> dict:
    """
    Remove a key from the runconfig (restores it to null / template default).

    Args:
        project_id: Project UUID
        key: Dotted path to remove
    """
    try:
        project = Project.load(project_id)
    except (KeyError, FileNotFoundError):
        return _project_error(project_id)

    try:
        unset_path(project.runconfig, key)
    except KeyError:
        return {"error": "key_not_found", "message": f"Key {key!r} not found in runconfig"}

    try:
        project.save()
    except Exception as exc:
        return {"error": "save_failed", "message": str(exc)}

    return {"project_id": project_id, "key": key, "unset": True}


@mcp.tool()
def insar_validate_runconfig(project_id: str) -> dict:
    """
    Validate the current runconfig against required-field rules for the workflow.

    Returns a list of errors. An empty errors list means the runconfig is valid.

    Args:
        project_id: Project UUID
    """
    try:
        project = Project.load(project_id)
    except (KeyError, FileNotFoundError):
        return _project_error(project_id)

    errors = validate_runconfig(project.runconfig, project.workflow)
    return {
        "project_id": project_id,
        "valid": len(errors) == 0,
        "errors": errors,
    }


@mcp.tool()
def insar_export_runconfig(project_id: str, output_dir: str = "") -> dict:
    """
    Render the current runconfig as a YAML file on disk.

    The exported file can be used directly with ISCE3 or reviewed by the user.

    Args:
        project_id: Project UUID
        output_dir: Directory to write YAML into (default: workspace_root/configs/)
    """
    try:
        project = Project.load(project_id)
    except (KeyError, FileNotFoundError):
        return _project_error(project_id)

    dest_dir = Path(output_dir.strip()) if output_dir.strip() else project.configs_dir()
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return {"error": "output_dir_not_writable", "message": str(exc)}

    yaml_path = dest_dir / "runconfig.yaml"
    try:
        yaml_path.write_text(
            yaml.dump(project.runconfig, default_flow_style=False, allow_unicode=True)
        )
    except Exception as exc:
        return {"error": "output_dir_not_writable", "message": str(exc)}

    exported_at = _utc_now()
    project.runconfig_exported_path = str(yaml_path)
    project.save()

    return {
        "project_id": project_id,
        "yaml_path": str(yaml_path),
        "exported_at": exported_at,
    }


# ── Group 3: Execution (M2) ────────────────────────────────────────────────────

@mcp.tool()
def insar_run_workflow(project_id: str, dry_run: bool = False) -> dict:
    """
    Launch the ISCE3 NISAR workflow using the current exported runconfig.

    The runconfig must be exported first via insar_export_runconfig.
    Execution happens inside the project's configured conda environment.

    Args:
        project_id: Project UUID
        dry_run: If true, return the command without executing it
    """
    try:
        project = Project.load(project_id)
    except (KeyError, FileNotFoundError):
        return _project_error(project_id)

    if not project.runconfig_exported_path:
        return {
            "error": "runconfig_not_exported",
            "message": "Call insar_export_runconfig first to write the runconfig YAML to disk",
        }

    runconfig_path = project.runconfig_exported_path
    if not Path(runconfig_path).exists():
        return {
            "error": "runconfig_not_exported",
            "message": f"Exported runconfig not found at {runconfig_path!r}. Call insar_export_runconfig again.",
        }

    errors = validate_runconfig(project.runconfig, project.workflow)
    if errors:
        return {
            "error": "runconfig_invalid",
            "message": "Runconfig has validation errors. Call insar_validate_runconfig to see details.",
            "errors": errors,
        }

    command = build_workflow_command(
        workflow=project.workflow,
        runconfig_path=runconfig_path,
        conda_env=project.conda_env,
    )

    job = Job(
        project_id=project.project_id,
        engine=project.engine,
        workflow=project.workflow,
        command=command,
        runconfig_path=runconfig_path,
    )
    log_path = str(project.logs_dir() / f"{job.job_id}.log")
    job.log_path = log_path

    if dry_run:
        return {
            "job_id": job.job_id,
            "project_id": project_id,
            "command": command,
            "status": "dry_run",
            "dry_run": True,
        }

    project.logs_dir().mkdir(parents=True, exist_ok=True)
    project.outputs_dir().mkdir(parents=True, exist_ok=True)

    job.started_at = _utc_now()
    job.status = "running"
    job.save(project.jobs_dir())

    try:
        with open(log_path, "w") as log_file:
            subprocess.Popen(
                command,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                cwd=project.workspace_root,
            )
    except Exception as exc:
        job.status = "failed"
        job.finished_at = _utc_now()
        job.exit_code = -1
        job.save(project.jobs_dir())
        return {"error": "launch_failed", "message": str(exc)}

    return {
        "job_id": job.job_id,
        "project_id": project_id,
        "command": command,
        "status": "running",
        "submitted_at": job.submitted_at,
        "log_path": log_path,
        "dry_run": False,
    }


@mcp.tool()
def insar_get_job_status(job_id: str, project_id: str) -> dict:
    """
    Return the current state of a job.

    Args:
        job_id: Job UUID
        project_id: Parent project UUID (needed to locate the job file)
    """
    try:
        project = Project.load(project_id)
    except (KeyError, FileNotFoundError):
        return _project_error(project_id)

    try:
        job = Job.load(job_id, project.jobs_dir())
    except FileNotFoundError:
        return _job_error(job_id)

    return {
        "job_id": job.job_id,
        "project_id": job.project_id,
        "status": job.status,
        "exit_code": job.exit_code,
        "submitted_at": job.submitted_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "log_path": job.log_path,
        "runconfig_path": job.runconfig_path,
    }


@mcp.tool()
def insar_get_job_logs(job_id: str, project_id: str, tail: int = 0) -> dict:
    """
    Return the job log content.

    Args:
        job_id: Job UUID
        project_id: Parent project UUID
        tail: Number of lines from the end (0 = full log)
    """
    try:
        project = Project.load(project_id)
    except (KeyError, FileNotFoundError):
        return _project_error(project_id)

    try:
        job = Job.load(job_id, project.jobs_dir())
    except FileNotFoundError:
        return _job_error(job_id)

    if not job.log_path or not Path(job.log_path).exists():
        return {"error": "log_not_available", "message": "Log file not found — job may not have started yet"}

    log_text = Path(job.log_path).read_text(errors="replace")
    lines = log_text.splitlines()
    if tail > 0:
        lines = lines[-tail:]

    return {
        "job_id": job_id,
        "log_path": job.log_path,
        "lines": len(lines),
        "content": "\n".join(lines),
    }


# ── Group 4: Outputs (M3) ──────────────────────────────────────────────────────

@mcp.tool()
def insar_list_outputs(job_id: str, project_id: str) -> dict:
    """
    List output files produced by a completed job.

    Args:
        job_id: Job UUID
        project_id: Parent project UUID
    """
    try:
        project = Project.load(project_id)
    except (KeyError, FileNotFoundError):
        return _project_error(project_id)

    try:
        job = Job.load(job_id, project.jobs_dir())
    except FileNotFoundError:
        return _job_error(job_id)

    if job.status not in ("done", "failed"):
        return {
            "error": "job_not_done",
            "message": f"Job status is {job.status!r}; wait for completion before listing outputs",
        }

    _TYPE_MAP = {
        ".h5": ("hdf5", "NISAR science product", "h5py / QGIS"),
        ".hdf5": ("hdf5", "NISAR science product", "h5py / QGIS"),
        ".tif": ("geotiff", "Exported raster product", "QGIS / GDAL"),
        ".tiff": ("geotiff", "Exported raster product", "QGIS / GDAL"),
        ".png": ("preview", "Preview image", "any image viewer"),
        ".log": ("log", "Workflow execution log", "text editor"),
        ".yaml": ("yaml", "Exported runconfig", "text editor"),
    }

    outputs_dir = project.outputs_dir() / job_id
    artifacts = []
    if outputs_dir.exists():
        for f in sorted(outputs_dir.rglob("*")):
            if f.is_file():
                ext = f.suffix.lower()
                artifact_type, description, viewer = _TYPE_MAP.get(ext, ("other", "Output file", ""))
                artifacts.append({
                    "path": str(f),
                    "artifact_type": artifact_type,
                    "description": description,
                    "recommended_viewer": viewer,
                })

    return {"job_id": job_id, "outputs": artifacts}


# ── Group 5: Stack / Network (M4) ─────────────────────────────────────────────

@mcp.tool()
def insar_prepare_stack(
    data_dir: str,
    base_runconfig: str,
    dem: str,
    output_dir: str,
    reference: str = "auto",
) -> dict:
    """
    Generate single-reference ISCE3 stack runconfigs from a directory of RSLC files.

    Scans data_dir for NISAR RSLC .h5 files, selects a reference scene, and
    produces one runconfig per secondary scene together with batch runner scripts
    (run_all.sh, run_parallel.sh) and a stack_manifest.csv.

    Args:
        data_dir: Directory containing RSLC .h5 files (all are used).
        base_runconfig: Path to a template ISCE3 runconfig YAML (e.g. tests/fixtures/insar_nisar.yaml).
        dem: Path to the DEM file to inject into each runconfig.
        output_dir: Directory where runconfigs and runner scripts will be written.
        reference: Reference scene selector — 'auto' (earliest date), a YYYYMMDD
                   string, or an absolute RSLC file path.
    """
    try:
        return prepare_stack(
            data_dir=data_dir,
            base_runconfig=base_runconfig,
            dem=dem,
            output_dir=output_dir,
            reference=reference,
        )
    except FileNotFoundError as exc:
        return {"error": "path_not_found", "message": str(exc)}
    except ValueError as exc:
        return {"error": "invalid_input", "message": str(exc)}


@mcp.tool()
def insar_prepare_network(
    data_dir: str,
    base_runconfig: str,
    dem: str,
    output_dir: str,
    network_mode: str = "tbase",
    max_temporal_baseline_days: int = 36,
    connection_span: int = 3,
    pair_list: str = "",
) -> dict:
    """
    Generate ISCE3 runconfigs for an interferogram network from a directory of RSLC files.

    Scans data_dir for NISAR RSLC .h5 files, builds an interferogram pair list
    according to the chosen network strategy, and produces one runconfig per pair
    together with batch runner scripts (run_all.sh, run_parallel.sh) and pair
    list manifests.

    Args:
        data_dir: Directory containing RSLC .h5 files.
        base_runconfig: Path to a template ISCE3 runconfig YAML.
        dem: Path to the DEM file.
        output_dir: Directory where runconfigs and runner scripts will be written.
        network_mode: 'tbase' — connect pairs within a temporal baseline threshold
                      (uses max_temporal_baseline_days); 'conn' — connect each date
                      to the next N dates (uses connection_span).
        max_temporal_baseline_days: Maximum temporal baseline in days (tbase mode only).
        connection_span: Number of forward neighbors per date (conn mode only).
        pair_list: Optional path to a file listing YYYYMMDD_YYYYMMDD pairs, one per
                   line. When provided, network_mode/span/threshold are ignored.
    """
    try:
        return prepare_network(
            data_dir=data_dir,
            base_runconfig=base_runconfig,
            dem=dem,
            output_dir=output_dir,
            network_mode=network_mode,
            max_temporal_baseline_days=max_temporal_baseline_days,
            connection_span=connection_span,
            pair_list=pair_list or None,
        )
    except FileNotFoundError as exc:
        return {"error": "path_not_found", "message": str(exc)}
    except ValueError as exc:
        return {"error": "invalid_input", "message": str(exc)}


# ── CLI entry point ────────────────────────────────────────────────────────────

def build_server_description() -> dict:
    """Return server metadata (kept for backward compat with smoke tests)."""
    return {
        "server_name": "insar-mcp-server",
        "transport": "stdio",
        "status": "active",
        "engines": ["isce3"],
        "tools": [
            "insar_list_engines",
            "insar_list_workflows",
            "insar_get_project",
            "insar_create_project",
            "insar_get_runconfig",
            "insar_set_runconfig_value",
            "insar_unset_runconfig_value",
            "insar_validate_runconfig",
            "insar_export_runconfig",
            "insar_run_workflow",
            "insar_get_job_status",
            "insar_get_job_logs",
            "insar_list_outputs",
            "insar_prepare_stack",
            "insar_prepare_network",
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
