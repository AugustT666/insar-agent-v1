from __future__ import annotations

import argparse
import json
import os
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
from insar_agent.engines.isce3.baseline import plot_baseline_network
from insar_agent.engines.isce3.bbox import union_bbox
from insar_agent.engines.isce3.geotiff import export_geotiff
from insar_agent.engines.isce3.mintpy import get_mintpy_status, run_mintpy
from insar_agent.engines.isce3.network import prepare_network
from insar_agent.engines.isce3.runner import build_workflow_command
from insar_agent.engines.isce3.stack import prepare_stack
from insar_agent.engines.isce3.validator import validate_runconfig

_ADAPTER = ISCE3Adapter()
_ENGINES = {_ADAPTER.name: _ADAPTER}

mcp = FastMCP("insar-mcp-server")

# Path to the external agent guide — single source of truth for AI constraints.
# Stored in docs/agent-guide.md so it can be edited without touching server code.
_GUIDE_PATH = Path(__file__).resolve().parent.parent.parent.parent / "docs" / "agent-guide.md"


# ── Resources ──────────────────────────────────────────────────────────────────

@mcp.resource("insar://workflow-guide")
def get_workflow_guide() -> str:
    """Workflow constraints and step-by-step guide for ISCE3 InSAR processing."""
    try:
        return _GUIDE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "# Agent guide not found — see docs/agent-guide.md"


@mcp.resource("insar://allowed-fields/{workflow}")
def get_allowed_fields(workflow: str) -> str:
    """List the fields that may be set via insar_set_runconfig_value for a workflow."""
    from insar_agent.engines.isce3.defaults import ALLOWED_SET_FIELDS, REQUIRED_PATH_FIELDS
    allowed = ALLOWED_SET_FIELDS.get(workflow)
    if allowed is None:
        return f"Unknown workflow: {workflow!r}. Available: {list(ALLOWED_SET_FIELDS)}"
    required = REQUIRED_PATH_FIELDS.get(workflow, [])
    lines = [f"# Settable fields for workflow '{workflow}'", "",
             "## Required (must be set before insar_validate_runconfig passes)"]
    lines += [f"  {f}" for f in required]
    optional = [f for f in allowed if f not in required]
    if optional:
        lines += ["", "## Optional"]
        lines += [f"  {f}" for f in optional]
    lines += ["", "All other fields are core processing parameters and cannot be changed via MCP."]
    return "\n".join(lines)


# ── Prompts ────────────────────────────────────────────────────────────────────

@mcp.prompt()
def process_insar_pair(
    reference_rslc: str = "",
    secondary_rslc: str = "",
    dem: str = "",
    output_dir: str = "",
    conda_env: str = "isce3",
) -> str:
    """
    Guided prompt for processing a single RSLC pair with ISCE3 InSAR workflow.

    Provides step-by-step instructions pre-filled with the user's data paths.
    Call with empty strings to get a generic template.
    """
    ref = reference_rslc or "/path/to/reference_rslc.h5"
    sec = secondary_rslc or "/path/to/secondary_rslc.h5"
    dem_p = dem or "/path/to/dem.tif"
    out = output_dir or "/path/to/workspace"
    env = conda_env or "isce3"

    return f"""\
Process a NISAR RSLC pair using the insar-agent MCP tools. Follow these steps exactly.

## Inputs
- Reference RSLC : {ref}
- Secondary RSLC : {sec}
- DEM            : {dem_p}
- Workspace      : {out}
- Conda env      : {env}

## Steps

1. Create project:
   insar_create_project(engine="isce3", workflow="insar",
       workspace_root="{out}", conda_env="{env}")
   → save the returned project_id

2. Set required path fields (call insar_set_runconfig_value once per field):
   - runconfig.groups.input_file_group.reference_rslc_file  = "{ref}"
   - runconfig.groups.input_file_group.secondary_rslc_file  = "{sec}"
   - runconfig.groups.dynamic_ancillary_file_group.dem_file = "{dem_p}"
   - runconfig.groups.product_path_group.product_path       = "{out}/outputs"
   - runconfig.groups.product_path_group.scratch_path       = "{out}/scratch"
   - runconfig.groups.product_path_group.sas_output_file    = "GUNW_product.h5"

3. Validate:
   insar_validate_runconfig(project_id)
   → if valid=false, fix the reported errors and validate again before proceeding

4. Export runconfig to disk:
   insar_export_runconfig(project_id)

5. Launch workflow:
   insar_run_workflow(project_id)
   → returns job_id

6. Poll until done:
   insar_get_job_status(job_id, project_id)
   → repeat until status is 'done' or 'failed'

7. On failure — read logs:
   insar_get_job_logs(job_id, project_id, tail=100)

8. On success — list products:
   insar_list_outputs(job_id, project_id)

## Constraints reminder
- Do NOT attempt to set core processing parameters (multilook, filtering, etc.)
- Do NOT skip validate or export steps
- Do NOT modify the runconfig YAML manually for path fields — use insar_set_runconfig_value
"""


@mcp.prompt()
def process_insar_batch(
    data_dir: str = "",
    base_runconfig: str = "",
    dem: str = "",
    output_dir: str = "",
    network_mode: str = "tbase",
    max_temporal_baseline_days: int = 36,
) -> str:
    """
    Guided prompt for batch ISCE3 stack + interferogram network preparation.

    Covers insar_prepare_stack and insar_prepare_network (wangshuai two-layer workflow).
    """
    dd = data_dir or "/path/to/rslc_dir"
    rc = base_runconfig or "/path/to/insar_nisar.yaml"
    dm = dem or "/path/to/dem.tif"
    out = output_dir or "/path/to/work"

    return f"""\
Prepare a batch ISCE3 interferogram network for MintPy time-series analysis.
This is a two-layer workflow; the MCP tools generate runconfigs and runner scripts —
the actual ISCE3 execution must be triggered by the user from the terminal.

## Inputs
- RSLC directory  : {dd}
- Template config : {rc}
- DEM             : {dm}
- Work directory  : {out}
- Network mode    : {network_mode}  (tbase = temporal baseline threshold, conn = fixed neighbors)

## Step 1 — Single-reference stack (registration baseline)

Call:
  insar_prepare_stack(
      data_dir="{dd}",
      base_runconfig="{rc}",
      dem="{dm}",
      output_dir="{out}/isce3_stack",
      reference="auto"   # uses earliest acquisition date
  )

Then execute in terminal:
  bash {out}/isce3_stack/run_parallel.sh {out}/isce3_stack <num_parallel_jobs>

## Step 2 — Interferogram network

Call:
  insar_prepare_network(
      data_dir="{dd}",
      base_runconfig="{rc}",
      dem="{dm}",
      output_dir="{out}/isce3_network",
      network_mode="{network_mode}",
      max_temporal_baseline_days={max_temporal_baseline_days}
  )

Then execute in terminal:
  bash {out}/isce3_network/run_parallel.sh {out}/isce3_network <num_parallel_jobs>

## What the tools produce

insar_prepare_stack →
  {out}/isce3_stack/runconfigs/         one YAML per secondary scene
  {out}/isce3_stack/run_parallel.sh     parallel batch runner
  {out}/isce3_stack/stack_manifest.csv  reference/secondary/runconfig index
  {out}/isce3_stack/reference_date.txt  selected reference date

insar_prepare_network →
  {out}/isce3_network/runconfigs/                    one YAML per pair
  {out}/isce3_network/run_parallel.sh               parallel batch runner
  {out}/isce3_network/pair_lists/pairs_selected.txt  pair list
  {out}/isce3_network/stack_manifest.csv

## After execution
The GUNW products land in:
  {out}/isce3_network/runs/<date1>_<date2>/products/*.h5

These are the inputs for MintPy time-series analysis (future insar_run_mintpy tool).

## Constraints reminder
- reference="auto" selects the earliest acquisition to avoid negative temporal baselines
- If insar_prepare_stack/network returns error: invalid_input, check that all RSLC
  filenames contain _YYYYMMDDTHHMMSS_ date stamps
- Do not hand-edit generated runconfigs — re-run the prepare tool with corrected inputs
"""


# ── helpers ────────────────────────────────────────────────────────────────────

def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _read_log_tail(log_path: str | None, n: int = 20) -> str:
    """Return the last *n* lines of a log file, or '' on any error."""
    if not log_path:
        return ""
    try:
        lines = Path(log_path).read_text(errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except Exception:
        return ""


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

    required = ALLOWED_SET_FIELDS.get(workflow, [])
    return {
        "project_id": project.project_id,
        "name": project.name,
        "engine": project.engine,
        "workflow": project.workflow,
        "workspace_root": project.workspace_root,
        "conda_env": project.conda_env,
        "created_at": project.created_at,
        "required_fields": required,
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
    valid = len(errors) == 0
    return {
        "project_id": project_id,
        "valid": valid,
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
            proc = subprocess.Popen(
                command,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                cwd=project.workspace_root,
            )
        job.pid = proc.pid
        job.save(project.jobs_dir())
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
        "pid": proc.pid,
        "submitted_at": job.submitted_at,
        "log_path": log_path,
        "dry_run": False,
        "poll": f"insar_get_job_status(job_id='{job.job_id}', project_id='{project_id}')",
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

    # PID-based liveness check: update status if process has exited
    if job.status == "running" and job.pid is not None:
        alive = True
        try:
            os.kill(job.pid, 0)
            # os.kill(pid, 0) succeeds for zombie processes too — check /proc
            state_line = next(
                (ln for ln in Path(f"/proc/{job.pid}/status").read_text().splitlines()
                 if ln.startswith("State:")),
                "",
            )
            if "Z" in state_line:
                alive = False
        except (ProcessLookupError, FileNotFoundError):
            alive = False
        if not alive:
            log_tail = _read_log_tail(job.log_path)
            log_lower = log_tail.lower()
            failed = (
                "error:" in log_lower
                or "traceback" in log_lower
                or "exception:" in log_lower
                or "critical:" in log_lower
            )
            job.status = "failed" if failed else "done"
            job.finished_at = _utc_now()
            job.exit_code = 1 if failed else 0
            job.save(project.jobs_dir())

    return {
        "job_id": job.job_id,
        "project_id": job.project_id,
        "status": job.status,
        "pid": job.pid,
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

    return {
        "job_id": job_id,
        "status": job.status,
        "outputs": artifacts,
    }


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
        result = prepare_stack(
            data_dir=data_dir,
            base_runconfig=base_runconfig,
            dem=dem,
            output_dir=output_dir,
            reference=reference,
        )
        result["run_command"] = f"bash {result['run_parallel_sh']} {result['output_dir']} <num_jobs>"
        return result
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
        result = prepare_network(
            data_dir=data_dir,
            base_runconfig=base_runconfig,
            dem=dem,
            output_dir=output_dir,
            network_mode=network_mode,
            max_temporal_baseline_days=max_temporal_baseline_days,
            connection_span=connection_span,
            pair_list=pair_list or None,
        )
        result["run_command"] = f"bash {result['run_parallel_sh']} {result['output_dir']} <num_jobs>"
        result["gunw_pattern"] = f"{result['output_dir']}/runs/*/products/*.h5"
        return result
    except FileNotFoundError as exc:
        return {"error": "path_not_found", "message": str(exc)}
    except ValueError as exc:
        return {"error": "invalid_input", "message": str(exc)}


# ── Group 6: Utilities (M5) ───────────────────────────────────────────────────

@mcp.tool()
def insar_extract_bbox(rslc_paths: list[str]) -> dict:
    """
    Extract the union bounding box from one or more NISAR RSLC HDF5 files.

    Reads the boundingPolygon field from each file and returns the combined
    geographic extent. Use this before downloading a DEM to ensure coverage.

    Args:
        rslc_paths: List of absolute paths to NISAR RSLC .h5 files.
    """
    if not rslc_paths:
        return {"error": "invalid_input", "message": "rslc_paths must not be empty"}

    missing = [p for p in rslc_paths if not Path(p).exists()]
    if missing:
        return {"error": "path_not_found", "message": f"Files not found: {missing}"}

    try:
        bbox = union_bbox(rslc_paths)
    except Exception as exc:
        return {"error": "bbox_failed", "message": str(exc)}

    return {
        "min_lon": bbox["min_lon"],
        "min_lat": bbox["min_lat"],
        "max_lon": bbox["max_lon"],
        "max_lat": bbox["max_lat"],
        "n_files": len(rslc_paths),
    }


@mcp.tool()
def insar_export_geotiff(h5_path: str, output_dir: str) -> dict:
    """
    Convert a NISAR GUNW HDF5 product to GeoTIFF + PNG browse images.

    Iterates all spatial datasets in the HDF5 file and writes one GeoTIFF and
    one colour-mapped PNG per dataset under <output_dir>/browse/.

    Requires h5py, numpy, and GDAL — must be run inside the isce3 conda environment.

    Args:
        h5_path: Absolute path to a NISAR GUNW .h5 output file.
        output_dir: Directory where browse/ subdirectory will be created.
    """
    if not Path(h5_path).exists():
        return {"error": "path_not_found", "message": f"File not found: {h5_path!r}"}

    try:
        result = export_geotiff(h5_path=h5_path, output_dir=output_dir)
    except RuntimeError as exc:
        return {"error": "dependency_missing", "message": str(exc)}
    except Exception as exc:
        return {"error": "export_failed", "message": str(exc)}

    return {
        "output_dir": result["output_dir"],
        "n_files": len(result["files"]),
        "files": result["files"],
        "skipped": result["skipped"],
    }


# ── Group 7: M6 MintPy ─────────────────────────────────────────────────────────

@mcp.tool()
def insar_run_mintpy(
    mintpy_work_dir: str,
    gunw_glob: str,
    mintpy_config: str,
    dem_path: str,
    conda_env: str,
) -> dict:
    """Launch MintPy time-series processing asynchronously.

    Wraps run_mintpy_nisar_stack.sh inside the given conda environment.
    stdout and stderr are written to <mintpy_work_dir>/logs/<job_id>.log.

    Args:
        mintpy_work_dir: Output directory for MintPy results.
        gunw_glob:       Shell glob pattern matching GUNW .h5 files,
                         e.g. /path/to/network/runs/*/products/*.h5
        mintpy_config:   Path to MintPy smallbaselineApp config (.cfg or .txt).
        dem_path:        Path to the DEM GeoTIFF used during preprocessing.
        conda_env:       Conda environment that contains MintPy and GDAL.
    """
    if not gunw_glob.strip():
        return {"error": "invalid_input", "message": "gunw_glob must not be empty"}

    for label, path in [("mintpy_config", mintpy_config), ("dem_path", dem_path)]:
        if not Path(path).exists():
            return {
                "error": "path_not_found",
                "message": f"{label} not found: {path!r}",
            }

    try:
        result = run_mintpy(
            mintpy_work_dir=mintpy_work_dir,
            gunw_glob=gunw_glob,
            mintpy_config=mintpy_config,
            dem_path=dem_path,
            conda_env=conda_env,
        )
    except FileNotFoundError as exc:
        return {"error": "path_not_found", "message": str(exc)}
    except Exception as exc:
        return {"error": "launch_failed", "message": str(exc)}

    job_id = result["job_id"]
    return {
        "job_id": job_id,
        "pid": result["pid"],
        "status": result["status"],
        "log_path": result["log_path"],
        "submitted_at": result["submitted_at"],
        "poll": (
            f"insar_get_mintpy_status("
            f"job_id='{job_id}', "
            f"mintpy_work_dir='{mintpy_work_dir}')"
        ),
    }


@mcp.tool()
def insar_get_mintpy_status(job_id: str, mintpy_work_dir: str) -> dict:
    """Return the current status of a MintPy job launched by insar_run_mintpy.

    Checks whether the process is still running.  If the process has exited,
    the job status is updated to 'done' or 'failed' by inspecting the log tail.

    Args:
        job_id:          UUID returned by insar_run_mintpy.
        mintpy_work_dir: Same directory passed to insar_run_mintpy.
    """
    if not Path(mintpy_work_dir).exists():
        return {
            "error": "path_not_found",
            "message": f"mintpy_work_dir not found: {mintpy_work_dir!r}",
        }

    try:
        data = get_mintpy_status(job_id=job_id, mintpy_work_dir=mintpy_work_dir)
    except FileNotFoundError:
        return {
            "error": "job_not_found",
            "message": f"No job with id {job_id!r} in {mintpy_work_dir!r}",
        }
    except Exception as exc:
        return {"error": "status_failed", "message": str(exc)}

    return {
        "job_id": data.get("job_id"),
        "pid": data.get("pid"),
        "status": data.get("status"),
        "log_path": data.get("log_path"),
        "submitted_at": data.get("submitted_at"),
        "finished_at": data.get("finished_at"),
    }


@mcp.tool()
def insar_plot_baseline(
    network_dir: str,
    pair_list: str = "",
    title: str = "ISCE3 Spatiotemporal Baseline Network",
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

    return {
        "png_path": result["png_path"],
        "pdf_path": result["pdf_path"],
        "pair_csv": result["pair_csv"],
        "scene_csv": result["scene_csv"],
        "n_pairs": result["n_pairs"],
    }


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
            "insar_extract_bbox",
            "insar_export_geotiff",
            "insar_run_mintpy",
            "insar_get_mintpy_status",
            "insar_plot_baseline",
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
