from __future__ import annotations

import argparse
import json
import math
import os
import shlex
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
from datetime import datetime, UTC
from pathlib import Path

import yaml
from mcp.server.fastmcp import FastMCP

from insar_agent.core.config import set_path, unset_path
from insar_agent.core.jobs import BatchJob, DownloadJob, Job
from insar_agent.core.project import Project, new_project, resolve_plugin_logs_dir
from insar_agent.engines.isce3.adapter import ISCE3Adapter
from insar_agent.engines.isce3.defaults import (
    ALLOWED_SET_FIELDS as ISCE3_ALLOWED_SET_FIELDS,
    REQUIRED_PATH_FIELDS,
    get_default_runconfig_template_path,
    get_processing_param_keys,
    load_default_runconfig,
    load_processing_params,
)
from insar_agent.engines.isce2.defaults import (
    ALLOWED_SET_FIELDS as ISCE2_ALLOWED_SET_FIELDS,
)

from insar_agent.engines.isce3.baseline import plot_baseline_network
from insar_agent.engines.isce3.bbox import union_bbox
from insar_agent.engines.isce3.aoi import resolve_aoi_bbox
from insar_agent.engines.isce3.dem import download_dem
from insar_agent.engines.isce3.geotiff import export_geotiff
from insar_agent.engines.isce3.mintpy import get_mintpy_status, run_mintpy
from insar_agent.engines.isce3.network import prepare_network
from insar_agent.engines.isce3.rslc_metadata import describe_rslc_pair
from insar_agent.engines.isce3.runner import build_workflow_command
from insar_agent.engines.isce3.stack import prepare_stack
from insar_agent.engines.isce3.validator import validate_runconfig
from insar_agent.engines.isce2.adapter import ISCE2Adapter
from insar_agent.engines.isce2.defaults import (
    REQUIRED_PARAM_FIELDS as ISCE2_REQUIRED_PARAM_FIELDS,
    get_processing_param_keys as isce2_get_processing_param_keys,
    load_default_params as isce2_load_default_params,
    load_processing_params as isce2_load_processing_params,
)
from insar_agent.engines.isce2.runner import build_topsapp_xml, build_workflow_command as isce2_build_workflow_command
from insar_agent.engines.isce2.mintpy import run_mintpy_isce2_stack
from insar_agent.engines.isce2.sentinel_prep import _read_safe_metadata, prepare_sentinel_data
from insar_agent.engines.isce2.stack import build_stack_command as isce2_build_stack_command
from insar_agent.engines.isce2.validator import validate_params as isce2_validate_params

ENGINE_ALLOWED_FIELDS: dict[str, dict[str, list[str]]] = {
    "isce3": ISCE3_ALLOWED_SET_FIELDS,
    "isce2": ISCE2_ALLOWED_SET_FIELDS,
}

_ADAPTER = ISCE3Adapter()
_ISCE2_ADAPTER = ISCE2Adapter()
_ENGINES = {_ADAPTER.name: _ADAPTER, _ISCE2_ADAPTER.name: _ISCE2_ADAPTER}

mcp = FastMCP("insar-mcp-server")

_CONDA_SAFE_DEFAULTS = {
    "_CONDA_SET_GEOTIFF_CSV": "",
}


def _conda_safe_env(overrides: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    for key, value in _CONDA_SAFE_DEFAULTS.items():
        env.setdefault(key, value)
    if overrides:
        env.update(overrides)
    return env


# Path to the external agent guide — single source of truth for AI constraints.
# Stored in docs/agent-guide.md so it can be edited without touching server code.
_GUIDE_PATH = Path(__file__).resolve().parent.parent.parent.parent / "docs" / "agent-guide.md"


def _ensure_logging_group(runconfig: dict, workspace_root: str) -> None:
    """Backfill the ISCE3 logging block required by official workflows."""
    groups = runconfig.setdefault("runconfig", {}).setdefault("groups", {})
    logging_cfg = groups.setdefault("logging", {})
    if not logging_cfg.get("path"):
        logging_cfg["path"] = str(resolve_plugin_logs_dir(workspace_root, workspace_root=workspace_root) / "insar_workflow.log")
    logging_cfg.setdefault("write_mode", "w")


def _ensure_project_logging(project: Project) -> None:
    """Ensure both live and template runconfigs carry a writable logging path."""
    _ensure_logging_group(project.runconfig, project.workspace_root)
    if project.runconfig_template:
        _ensure_logging_group(project.runconfig_template, project.workspace_root)


def _prepare_tool_log(paths: list[str | Path | None], prefix: str, params: dict, *, fallback_root: str | Path | None = None) -> tuple[str, Path, Path]:
    job_id = uuid.uuid4().hex[:12]
    logs_dir = resolve_plugin_logs_dir(*paths, fallback_root=fallback_root)
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"{prefix}_{job_id}.log"
    params_path = logs_dir / f"{prefix}_{job_id}_params.json"
    log_path.touch()
    params_path.write_text(json.dumps(params, indent=2, ensure_ascii=False), encoding="utf-8")
    return job_id, log_path, params_path


def _append_log(log_path: Path, message: str) -> None:
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(f"{message}\n")


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
             "## Required (must be set before insar_run_workflow can launch successfully)"]
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

2.5. Optional parameter tuning:
   If the user asks about multilook, filtering, unwrapping, ionosphere/troposphere
   corrections, or provides study-area characteristics, enter the param-advisor
   skill here with engine=isce3 (after paths are set, before validation). That skill
   starts by calling insar_describe_rslc(...) to build a metadata-first evidence
   profile, then delegates recommendation generation to the project-level subagent
   defined in .claude/agents/param-advisor.md. The subagent may consult the
   engine-specific reference asset at .claude/agents/references/param-advisor-isce{{engine}}.md
   and may use automatic external search only when local evidence is insufficient.
   The main agent may only apply whitelist-controlled parameters via
   insar_set_processing_param after the subagent returns and the user confirms the plan.

3. Launch workflow:
   insar_run_workflow(project_id)
   → auto-validates, exports the YAML, and returns job_id + poll hint

4. Poll until done:
   insar_get_job(job_id, project_id)
   → repeat until status is 'done' or 'failed'

5. On failure — read logs inline:
   insar_get_job(job_id, project_id, include_logs=True)

6. On success — list products:
   insar_list_outputs(job_id, project_id)

## Constraints reminder
- Path fields must go through insar_set_runconfig_value
- Whitelist-controlled processing parameters should flow through param-advisor (engine=isce3)
- For skill-aware clients, parameter advice should come from param-advisor plus its project-level subagent
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
    rc = base_runconfig or str(get_default_runconfig_template_path("insar"))
    dm = dem or "/path/to/dem.tif"
    out = output_dir or "/path/to/work"

    return f"""\
Prepare a batch ISCE3 interferogram network for MintPy time-series analysis.
This is a two-layer workflow; the MCP tools generate runconfigs and runner scripts.
Execution can either be started through insar_run_batch or by running the generated
shell script manually from the terminal.
Default to interaction_mode="interactive" and tell advanced users they can switch
to interaction_mode="auto" for minimal interruptions.

## Inputs
- RSLC directory  : {dd}
- Template config : {rc}
  Omit base_runconfig to use the built-in default `insar` template.
- DEM             : {dm}
- Work directory  : {out}
- Network mode    : {network_mode}  (tbase = temporal baseline threshold, conn = fixed neighbors)

## Optional parameter tuning before Step 1

If the user wants to tune multilook, filtering, unwrapping, or geocode output spacing,
enter param-advisor first using a temporary insar project and engine=isce3. That skill
must delegate recommendation generation to the project-level subagent defined in
.claude/agents/param-advisor.md after calling insar_describe_rslc(...) to build a
local metadata summary. The subagent may consult the engine-specific reference asset at
.claude/agents/references/param-advisor-isce{{engine}}.md and may use automatic external
search only when that evidence is insufficient, and the final recommendation must show
provenance so the user can decide what to trust.
Export the tuned YAML and pass that file as base_runconfig for both stack and
network preparation.

## Step 1 — Single-reference stack (registration baseline)

Call:
  insar_prepare_stack(
      data_dir="{dd}",
      base_runconfig="{rc}",
      dem="{dm}",
      output_dir="{out}/isce3_stack",
      reference="auto",   # uses earliest acquisition date
      interaction_mode="interactive"
  )

Then either:
  insar_run_batch(batch_dir="{out}/isce3_stack", max_jobs=<num_parallel_jobs>,
                  execution_mode="parallel", interaction_mode="interactive")

Or execute in terminal:
  bash {out}/isce3_stack/run_parallel.sh {out}/isce3_stack <num_parallel_jobs>

When using insar_run_batch, poll with:
  insar_get_job(job_id="<returned_job_id>", batch_dir="{out}/isce3_stack")

## Step 2 — Interferogram network

Call:
  insar_prepare_network(
      data_dir="{dd}",
      base_runconfig="{rc}",
      dem="{dm}",
      output_dir="{out}/isce3_network",
      network_mode="{network_mode}",
      max_temporal_baseline_days={max_temporal_baseline_days},
      interaction_mode="interactive"
  )

Then either:
  insar_run_batch(batch_dir="{out}/isce3_network", max_jobs=<num_parallel_jobs>,
                  execution_mode="parallel", interaction_mode="interactive")

Or execute in terminal:
  bash {out}/isce3_network/run_parallel.sh {out}/isce3_network <num_parallel_jobs>

When using insar_run_batch, poll with:
  insar_get_job(job_id="<returned_job_id>", batch_dir="{out}/isce3_network")

## What the tools produce

insar_prepare_stack →
  {out}/isce3_stack/runconfigs/         one YAML per secondary scene
  {out}/isce3_stack/run_parallel.sh     parallel batch runner
  {out}/isce3_stack/run_all.sh          serial batch runner
  {out}/isce3_stack/stack_manifest.csv  reference/secondary/runconfig index
  {out}/isce3_stack/reference_date.txt  selected reference date

insar_prepare_network →
  {out}/isce3_network/runconfigs/                    one YAML per pair
  {out}/isce3_network/run_parallel.sh               parallel batch runner
  {out}/isce3_network/run_all.sh                    serial batch runner
  {out}/isce3_network/pair_lists/pairs_selected.txt  pair list
  {out}/isce3_network/stack_manifest.csv

## After execution
The GUNW products land in:
  {out}/isce3_network/runs/<date1>_<date2>/products/*.h5

These are the inputs for MintPy time-series analysis via insar_run_mintpy.
In interactive mode, stop at prepare/baseline checkpoints whenever the tool
returns handoff_required=true so the user can review intermediate products.

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


def _read_exit_code(exit_code_path: str | None) -> int | None:
    """Read a persisted process exit code, or return None if unavailable."""
    if not exit_code_path:
        return None
    try:
        return int(Path(exit_code_path).read_text().strip())
    except Exception:
        return None


def _normalize_interaction_mode(interaction_mode: str) -> str:
    mode = (interaction_mode or "interactive").strip().lower()
    if mode not in {"interactive", "auto"}:
        raise ValueError(
            f"Unsupported interaction_mode: {interaction_mode!r}. Use 'interactive' or 'auto'."
        )
    return mode


def _prepare_handoff(
    *,
    interaction_mode: str,
    handoff_reason: str,
    review_artifacts: list[str],
    next_recommended_action: str,
) -> dict[str, object]:
    return {
        "interaction_mode": interaction_mode,
        "handoff_required": interaction_mode == "interactive",
        "handoff_reason": handoff_reason,
        "review_artifacts": review_artifacts,
        "next_recommended_action": next_recommended_action,
    }


def _finalize_job_status_from_artifacts(job: Job, jobs_dir: Path) -> None:
    """Update a finished workflow job using persisted exit code or log fallback."""
    exit_code = _read_exit_code(job.exit_code_path)
    if exit_code is not None:
        job.status = "done" if exit_code == 0 else "failed"
        job.exit_code = exit_code
    else:
        log_tail = _read_log_tail(job.log_path)
        log_lower = log_tail.lower()
        failed = (
            "error:" in log_lower
            or "traceback" in log_lower
            or "exception:" in log_lower
            or "critical:" in log_lower
        )
        job.status = "failed" if failed else "done"
        job.exit_code = 1 if failed else 0
    job.finished_at = _utc_now()
    job.save(jobs_dir)


def _safe_get_path(runconfig: dict, key: str) -> object:
    from insar_agent.core.config import get_path

    try:
        return get_path(runconfig, key)
    except KeyError:
        return None


def _engine_error(engine: str) -> dict:
    return {"error": "engine_not_found", "message": f"Engine {engine!r} not recognized. Available: {list(_ENGINES)}"}


def _project_error(project_id: str) -> dict:
    return {"error": "project_not_found", "message": f"Project {project_id!r} not found in registry"}


def _job_error(job_id: str) -> dict:
    return {"error": "job_not_found", "message": f"Job {job_id!r} not found"}


_VAGUE_JUSTIFICATIONS = {
    "better performance",
    "optimize",
    "optimization",
    "improve quality",
    "test",
}


def _validate_processing_param_type(value: object, meta: dict) -> dict | None:
    expected_type = meta.get("type")
    allow_null = meta.get("allow_null", meta.get("default") is None)
    if value is None:
        if allow_null:
            return None
        return {
            "error": "invalid_type",
            "message": f"Key {meta['key']!r} does not allow null values.",
        }

    type_checks = {
        "int": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "float": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "str": lambda item: isinstance(item, str),
        "bool": lambda item: isinstance(item, bool),
        "list": lambda item: isinstance(item, list),
    }
    checker = type_checks.get(expected_type)
    if checker and not checker(value):
        return {
            "error": "invalid_type",
            "message": f"Value {value!r} must have type {expected_type} for key {meta['key']!r}.",
        }
    return None


def _validate_processing_param_structure(value: object, meta: dict) -> dict | None:
    if value is None:
        return None

    list_shape = meta.get("list_shape")
    if list_shape is not None:
        if not isinstance(value, list):
            return {
                "error": "invalid_input",
                "message": f"Value for key {meta['key']!r} must be a list.",
            }
        length = list_shape.get("length")
        if length is not None and len(value) != length:
            return {
                "error": "invalid_input",
                "message": f"Value {value!r} must contain exactly {length} items for key {meta['key']!r}.",
            }
        item_type = list_shape.get("item_type")
        valid_range = list_shape.get("valid_range")
        for item in value:
            if item_type == "int" and not (isinstance(item, int) and not isinstance(item, bool)):
                return {
                    "error": "invalid_input",
                    "message": f"List items for key {meta['key']!r} must be integers.",
                }
            if valid_range is not None:
                lo, hi = valid_range
                if not (lo <= item <= hi):
                    return {
                        "error": "invalid_input",
                        "message": f"List item {item!r} is outside valid_range {valid_range} for key {meta['key']!r}.",
                    }
    return None


# ── Group 1: Discovery ─────────────────────────────────────────────────────────

@mcp.tool()
def insar_discover(engine: str = "") -> dict:
    """Discover available engines or workflows.

    Args:
        engine: Leave empty to list all engines. Provide an engine name (e.g.
                'isce3') to list its supported workflows.
    """
    if not engine:
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


# Kept for backwards compatibility / direct import in tests (not MCP tools).
def insar_list_engines() -> dict:
    """List available InSAR processing engines. Use insar_discover() instead."""
    return insar_discover()


def insar_list_workflows(engine: str) -> dict:
    """List workflows for an engine. Use insar_discover(engine) instead."""
    return insar_discover(engine=engine)


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

    # ISCE2 uses a flat param dict instead of a nested YAML runconfig
    if engine == "isce2":
        try:
            default_params = isce2_load_default_params(workflow)
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
        project.runconfig = default_params
        project.runconfig_template = default_params

        try:
            project.save()
        except Exception as exc:
            return {"error": "workspace_not_writable", "message": str(exc)}

        required = ISCE2_REQUIRED_PARAM_FIELDS.get(workflow, [])
        return {
            "project_id": project.project_id,
            "name": project.name,
            "engine": project.engine,
            "workflow": project.workflow,
            "workspace_root": project.workspace_root,
            "conda_env": project.conda_env,
            "created_at": project.created_at,
            "required_fields": required,
            "guidance": (
                "Set required path fields with insar_set_processing_param. "
                "Use insar_describe_s1 to inspect scene metadata (orbit, polarization, coverage). "
                "If you need to tune looks, filtering, ESD/coregistration, unwrapping, or stack connections, "
                "enter the param-advisor skill with engine=isce2 before validate/run. That skill must call "
                "insar_describe_s1, then delegate recommendation generation to the project-level subagent "
                "defined in .claude/agents/param-advisor.md before applying changes via "
                "insar_set_processing_param. "
                "For S1 time-series (workflow='stack'), set slc_dir to the directory containing "
                "all S1 SAFE/ZIP files, then call insar_run_workflow to run stackSentinel.py."
            ),
        }

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
    _ensure_project_logging(project)

    try:
        project.save()
    except Exception as exc:
        return {"error": "workspace_not_writable", "message": str(exc)}

    required = REQUIRED_PATH_FIELDS.get(workflow, [])
    return {
        "project_id": project.project_id,
        "name": project.name,
        "engine": project.engine,
        "workflow": project.workflow,
        "workspace_root": project.workspace_root,
        "conda_env": project.conda_env,
        "created_at": project.created_at,
        "required_fields": required,
        "guidance": (
            "Set required path fields with insar_set_runconfig_value. "
            "Use insar_describe_rslc to build a metadata summary before parameter tuning. "
            "If you need to tune multilook, filtering, unwrapping, or atmospheric corrections, "
            "enter the param-advisor skill with engine=isce3 before validate/export/run. That skill must "
            "call insar_describe_rslc, then delegate recommendation generation to the "
            "project-level subagent defined in .claude/agents/param-advisor.md before "
            "applying changes via insar_set_processing_param. The subagent may consult the "
            "engine-specific reference asset at .claude/agents/references/param-advisor-isce{engine}.md and may use automatic "
            "external search only when local evidence is insufficient, and the user remains "
            "responsible for accepting or rejecting those sources."
        ),
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
    Set or remove a value at a dotted key path within the project runconfig.

    Only path-related fields and a small set of worker flags are allowed.
    Core processing parameters cannot be changed through this tool. Use
    param-advisor (engine-selected) + insar_set_processing_param for whitelist-controlled
    tuning; all other processing keys remain locked.

    Pass value=None to remove the key (restore to template default).

    Args:
        project_id: Project UUID
        key: Dotted path, e.g. 'runconfig.groups.input_file_group.reference_rslc_file'
        value: New value (string, number, boolean) or None to remove the key
    """
    try:
        project = Project.load(project_id)
    except (KeyError, FileNotFoundError):
        return _project_error(project_id)

    if value is None:
        # Unset the key
        try:
            unset_path(project.runconfig, key)
        except KeyError:
            return {"error": "key_not_found", "message": f"Key {key!r} not found in runconfig"}
        try:
            project.save()
        except Exception as exc:
            return {"error": "save_failed", "message": str(exc)}
        return {"project_id": project_id, "key": key, "unset": True}

    engine_allowed = ENGINE_ALLOWED_FIELDS.get(project.engine, {})
    allowed = engine_allowed.get(project.workflow, [])
    if allowed and key not in allowed:
        return {
            "error": "key_not_allowed",
            "message": (
                f"Key {key!r} is not in the allowed set for engine {project.engine!r}, "
                f"workflow {project.workflow!r}. "
                "Use insar_set_processing_param for whitelist-controlled processing keys. "
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
def insar_set_processing_param(
    project_id: str,
    key: str,
    value: object,
    justification: str,
) -> dict:
    """
    Set a core processing parameter in the project runconfig.

    Unlike insar_set_runconfig_value (path fields only), this tool modifies
    ISCE3 algorithm parameters such as multilook factors, phase unwrapping
    settings, and correction toggles. Only keys listed in the processing
    parameter registry (assets/processing_params_insar.yaml) are allowed.

    Must be called by the param-advisor skill after its project-level
    subagent has produced an explicit recommendation package, with a specific
    justification for each change relative to the default template.

    After applying all parameters, call insar_get_runconfig(format='yaml') to
    show the full runconfig and wait for user confirmation before proceeding to
    insar_run_workflow.

    Args:
        project_id: Project UUID
        key: Dotted path from the processing parameter registry
        value: New value (int, float, str, bool, or list)
        justification: Reason for this change relative to the default template.
                       Must be specific (e.g. "城市L波段高相干，减少多视以保留分辨率").
                       Empty or vague strings are rejected.
    """
    if not justification or not justification.strip():
        return {
            "error": "justification_required",
            "message": "justification must not be empty. Provide a specific reason for this parameter change.",
        }
    if justification.strip().lower() in _VAGUE_JUSTIFICATIONS:
        return {
            "error": "justification_required",
            "message": "justification is too vague. Tie the change to scene characteristics, data quality, or processing goals.",
        }

    try:
        project = Project.load(project_id)
    except (KeyError, FileNotFoundError):
        return _project_error(project_id)

    # Dispatch to engine-specific param registry
    if project.engine == "isce2":
        allowed_keys = isce2_get_processing_param_keys(project.workflow)
        if key not in allowed_keys:
            return {
                "error": "key_not_allowed",
                "message": (
                    f"Key {key!r} is not in the ISCE2 processing parameter registry for "
                    f"workflow {project.workflow!r}. "
                    f"Allowed keys: {allowed_keys}"
                ),
            }
        params_meta = {p["key"]: p for p in isce2_load_processing_params(project.workflow)}
        meta = params_meta[key]
        old_value = project.runconfig.get(key)

        valid_values = meta.get("valid_values")
        valid_range = meta.get("valid_range")

        type_error = _validate_processing_param_type(value, meta)
        if type_error is not None:
            return type_error

        structure_error = _validate_processing_param_structure(value, meta)
        if structure_error is not None:
            return structure_error

        if valid_values is not None and value not in valid_values:
            return {
                "error": "value_not_allowed",
                "message": f"Value {value!r} is not in valid_values {valid_values} for key {key!r}.",
            }
        if valid_range is not None and value is not None:
            lo, hi = valid_range
            try:
                if not (lo <= value <= hi):
                    return {
                        "error": "value_out_of_range",
                        "message": f"Value {value!r} is outside valid_range {valid_range} for key {key!r}.",
                    }
            except TypeError:
                pass

        project.runconfig[key] = value
        try:
            project.save()
        except Exception as exc:
            return {"error": "save_failed", "message": str(exc)}

        return {
            "project_id": project_id,
            "key": key,
            "label": meta.get("label", key),
            "old_value": old_value,
            "new_value": value,
            "risk_level": meta.get("risk_level", "unknown"),
            "justification": justification.strip(),
            "validated_against": f"isce2/processing_params_{project.workflow}.yaml@{meta.get('label', key)}",
            "updated_at": project.updated_at,
        }

    allowed_keys = get_processing_param_keys(project.workflow)
    if key not in allowed_keys:
        return {
            "error": "key_not_allowed",
            "message": (
                f"Key {key!r} is not in the processing parameter registry for "
                f"workflow {project.workflow!r}. "
                f"Allowed keys: {allowed_keys}"
            ),
        }

    # Capture old value for the return payload
    from insar_agent.core.config import get_path
    try:
        old_value = get_path(project.runconfig, key)
    except KeyError:
        old_value = None

    # Validate value type against registry metadata
    params_meta = {p["key"]: p for p in load_processing_params(project.workflow)}
    meta = params_meta[key]
    valid_values = meta.get("valid_values")
    valid_range = meta.get("valid_range")

    type_error = _validate_processing_param_type(value, meta)
    if type_error is not None:
        return type_error

    structure_error = _validate_processing_param_structure(value, meta)
    if structure_error is not None:
        return structure_error

    if valid_values is not None and value not in valid_values:
        return {
            "error": "value_not_allowed",
            "message": f"Value {value!r} is not in valid_values {valid_values} for key {key!r}.",
        }
    if valid_range is not None and value is not None:
        lo, hi = valid_range
        try:
            if not (lo <= value <= hi):
                return {
                    "error": "value_out_of_range",
                    "message": f"Value {value!r} is outside valid_range {valid_range} for key {key!r}.",
                }
        except TypeError:
            pass  # list or incomparable type — skip range check

    depends_on = meta.get("depends_on", {})
    for dep_key, dep_value in depends_on.items():
        try:
            current_dep = get_path(project.runconfig, dep_key)
        except KeyError:
            current_dep = None
        if current_dep != dep_value:
            return {
                "error": "invalid_input",
                "message": (
                    f"Key {key!r} requires {dep_key!r} to be {dep_value!r}, "
                    f"but current value is {current_dep!r}."
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
        "label": meta.get("label", key),
        "old_value": old_value,
        "new_value": value,
        "risk_level": meta.get("risk_level", "unknown"),
        "justification": justification.strip(),
        "validated_against": f"processing_params_{project.workflow}.yaml@{meta.get('label', key)}",
        "updated_at": project.updated_at,
    }


def insar_unset_runconfig_value(project_id: str, key: str) -> dict:
    """
    Remove a key from the runconfig. Use insar_set_runconfig_value(value=None) instead.

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
    To save a param-tuned snapshot, pass output_dir="<workspace_root>/param_tuned".
    The resulting file (<output_dir>/runconfig.yaml) will be detected automatically
    by insar_run_workflow as a previously-tuned config.

    Args:
        project_id: Project UUID
        output_dir: Directory to write YAML into (default: workspace_root/configs/)
    """
    try:
        project = Project.load(project_id)
    except (KeyError, FileNotFoundError):
        return _project_error(project_id)

    _ensure_project_logging(project)
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

    configs_dir = project.configs_dir()
    configs_dir.mkdir(parents=True, exist_ok=True)

    if project.workflow == "tops":
        # Generate topsApp.xml
        try:
            xml_content = build_topsapp_xml(params)
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
        )

    elif project.workflow == "stack":
        # stackSentinel.py args are passed directly (no config file)
        command = isce2_build_stack_command(
            params=params,
            work_dir=project.workspace_root,
            conda_env=project.conda_env,
        )
        config_path = None

    else:
        return {"error": "workflow_not_found", "message": f"Unknown ISCE2 workflow: {project.workflow!r}"}

    job = Job(
        project_id=project.project_id,
        engine=project.engine,
        workflow=project.workflow,
        command=command,
        runconfig_path=str(config_path) if config_path else "",
    )
    log_path = str(project.logs_dir() / f"{job.job_id}.log")
    exit_code_path = str(project.logs_dir() / f"{job.job_id}.exitcode")
    job.log_path = log_path
    job.exit_code_path = exit_code_path

    if dry_run:
        return {
            "job_id": job.job_id,
            "project_id": project.project_id,
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
        shell_command = (
            f"{shlex.join(command)}; "
            f"status=$?; "
            f"printf '%s' \"$status\" > {shlex.quote(exit_code_path)}; "
            f"exit $status"
        )
        with open(log_path, "w") as log_file:
            proc = subprocess.Popen(
                ["bash", "-lc", shell_command],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                cwd=project.workspace_root,
                env=_conda_safe_env(),
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
        "project_id": project.project_id,
        "command": command,
        "status": "running",
        "pid": proc.pid,
        "submitted_at": job.submitted_at,
        "log_path": log_path,
        "dry_run": False,
        "poll": f"insar_get_job(job_id='{job.job_id}', project_id='{project.project_id}')",
    }


@mcp.tool()
def insar_run_workflow(project_id: str, dry_run: bool = False) -> dict:
    """
    Validate, export, and launch the ISCE3 NISAR workflow.

    Automatically validates the runconfig and writes the YAML to disk before
    launching. No separate validate or export step is needed.
    Execution happens inside the project's configured conda environment.

    Args:
        project_id: Project UUID
        dry_run: If true, validate and export but do not launch the process
    """
    try:
        project = Project.load(project_id)
    except (KeyError, FileNotFoundError):
        return _project_error(project_id)

    # Dispatch to engine-specific run logic
    if project.engine == "isce2":
        return _run_workflow_isce2(project, dry_run)

    _ensure_project_logging(project)
    _param_tuned_path = Path(project.workspace_root) / "param_tuned" / "runconfig.yaml"
    _param_tuned_found = _param_tuned_path.exists()
    # Step 1: validate
    errors = validate_runconfig(project.runconfig, project.workflow)
    if errors:
        return {
            "error": "runconfig_invalid",
            "message": "Runconfig has validation errors — fix them before running.",
            "errors": errors,
        }

    # Step 2: export YAML to configs_dir
    configs_dir = project.configs_dir()
    try:
        configs_dir.mkdir(parents=True, exist_ok=True)
        yaml_path = configs_dir / "runconfig.yaml"
        yaml_path.write_text(
            yaml.dump(project.runconfig, default_flow_style=False, allow_unicode=True)
        )
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

    job = Job(
        project_id=project.project_id,
        engine=project.engine,
        workflow=project.workflow,
        command=command,
        runconfig_path=runconfig_path,
    )
    log_path = str(project.logs_dir() / f"{job.job_id}.log")
    exit_code_path = str(project.logs_dir() / f"{job.job_id}.exitcode")
    job.log_path = log_path
    job.exit_code_path = exit_code_path

    if dry_run:
        return {
            "job_id": job.job_id,
            "project_id": project_id,
            "command": command,
            "status": "dry_run",
            "dry_run": True,
            "param_tuned_found": _param_tuned_found,
            "param_tuned_config": str(_param_tuned_path) if _param_tuned_found else None,
        }

    project.logs_dir().mkdir(parents=True, exist_ok=True)
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
        with open(log_path, "w") as log_file:
            proc = subprocess.Popen(
                ["bash", "-lc", shell_command],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                cwd=project.workspace_root,
                env=_conda_safe_env(),
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
        "poll": f"insar_get_job(job_id='{job.job_id}', project_id='{project_id}')",
        "param_tuned_found": _param_tuned_found,
        "param_tuned_config": str(_param_tuned_path) if _param_tuned_found else None,
    }


@mcp.tool()
def insar_get_job(
    job_id: str,
    project_id: str = "",
    work_dir: str = "",
    batch_dir: str = "",
    output_dir: str = "",
    include_logs: bool = False,
) -> dict:
    """
    Return the current state of any job (ISCE3 workflow, MintPy, batch, or download).

    For ISCE3 workflow jobs: provide project_id.
    For MintPy jobs: provide work_dir (the mintpy_work_dir passed to insar_run_mintpy).
    For batch jobs (insar_run_batch): provide batch_dir (the output_dir of prepare_stack/network).
    For download jobs (insar_download_rslc): provide output_dir.

    Args:
        job_id: Job UUID
        project_id: Parent project UUID (for ISCE3 workflow jobs)
        work_dir: MintPy work directory (for MintPy jobs)
        batch_dir: Batch output directory (for insar_run_batch jobs)
        output_dir: Download output directory (for insar_download_rslc jobs)
        include_logs: If true, include the full log content in the response
    """
    if output_dir:
        if not Path(output_dir).exists():
            return {"error": "path_not_found", "message": f"output_dir not found: {output_dir!r}"}
        try:
            dl_job = DownloadJob.load(job_id, output_dir)
        except FileNotFoundError:
            return {"error": "job_not_found", "message": f"No download job {job_id!r} in {output_dir!r}"}
        except Exception as exc:
            return {"error": "load_failed", "message": str(exc)}

        if dl_job.status == "running" and dl_job.pid is not None:
            alive = True
            try:
                os.kill(dl_job.pid, 0)
                state_line = next(
                    (ln for ln in Path(f"/proc/{dl_job.pid}/status").read_text().splitlines()
                     if ln.startswith("State:")),
                    "",
                )
                if "Z" in state_line:
                    alive = False
            except (ProcessLookupError, FileNotFoundError):
                alive = False
            if not alive:
                log_tail = _read_log_tail(dl_job.log_path) if dl_job.log_path else ""
                log_lower = log_tail.lower()
                failed = (
                    "error:" in log_lower
                    or "traceback" in log_lower
                    or "exception:" in log_lower
                    or "status: failed" in log_lower
                )
                dl_job.status = "failed" if failed else "done"
                dl_job.finished_at = _utc_now()
                dl_job.exit_code = 1 if failed else 0
                dl_job.save()

        result: dict = {
            "job_id": dl_job.job_id,
            "output_dir": dl_job.output_dir,
            "n_files": dl_job.n_files,
            "status": dl_job.status,
            "pid": dl_job.pid,
            "exit_code": dl_job.exit_code,
            "submitted_at": dl_job.submitted_at,
            "finished_at": dl_job.finished_at,
            "log_path": dl_job.log_path,
        }
        if include_logs:
            if dl_job.log_path and Path(dl_job.log_path).exists():
                result["log_content"] = Path(dl_job.log_path).read_text(errors="replace")
            else:
                result["log_content"] = None
        return result

    if batch_dir:
        if not Path(batch_dir).exists():
            return {"error": "path_not_found", "message": f"batch_dir not found: {batch_dir!r}"}
        try:
            batch_job = BatchJob.load(job_id, batch_dir)
        except FileNotFoundError:
            return {"error": "job_not_found", "message": f"No batch job {job_id!r} in {batch_dir!r}"}
        except Exception as exc:
            return {"error": "load_failed", "message": str(exc)}

        # PID liveness check (same pattern as ISCE3 branch)
        if batch_job.status == "running" and batch_job.pid is not None:
            alive = True
            try:
                os.kill(batch_job.pid, 0)
                state_line = next(
                    (ln for ln in Path(f"/proc/{batch_job.pid}/status").read_text().splitlines()
                     if ln.startswith("State:")),
                    "",
                )
                if "Z" in state_line:
                    alive = False
            except (ProcessLookupError, FileNotFoundError):
                alive = False
            if not alive:
                log_tail = _read_log_tail(batch_job.log_path)
                log_lower = log_tail.lower()
                failed = (
                    "error:" in log_lower
                    or "traceback" in log_lower
                    or "exception:" in log_lower
                    or "critical:" in log_lower
                    or "exit 1" in log_lower
                )
                batch_job.status = "failed" if failed else "done"
                batch_job.finished_at = _utc_now()
                batch_job.exit_code = 1 if failed else 0
                batch_job.save()

        result: dict = {
            "job_id": batch_job.job_id,
            "batch_dir": batch_job.batch_dir,
            "batch_type": batch_job.batch_type,
            "num_pairs": batch_job.num_pairs,
            "status": batch_job.status,
            "pid": batch_job.pid,
            "exit_code": batch_job.exit_code,
            "submitted_at": batch_job.submitted_at,
            "started_at": batch_job.started_at,
            "finished_at": batch_job.finished_at,
            "log_path": batch_job.log_path,
        }
        if include_logs:
            if batch_job.log_path and Path(batch_job.log_path).exists():
                result["log_content"] = Path(batch_job.log_path).read_text(errors="replace")
            else:
                result["log_content"] = None
        return result

    if work_dir:
        # MintPy job — delegate to mintpy status checker
        if not Path(work_dir).exists():
            return {"error": "path_not_found", "message": f"work_dir not found: {work_dir!r}"}
        try:
            data = get_mintpy_status(job_id=job_id, mintpy_work_dir=work_dir)
        except FileNotFoundError:
            return {"error": "job_not_found", "message": f"No job {job_id!r} in {work_dir!r}"}
        except Exception as exc:
            return {"error": "status_failed", "message": str(exc)}
        result = {
            "job_id": data.get("job_id"),
            "status": data.get("status"),
            "pid": data.get("pid"),
            "submitted_at": data.get("submitted_at"),
            "finished_at": data.get("finished_at"),
            "log_path": data.get("log_path"),
        }
        if include_logs:
            log_path = str(data.get("log_path", ""))
            if log_path and Path(log_path).exists():
                result["log_content"] = Path(log_path).read_text(errors="replace")
            else:
                result["log_content"] = None
        return result

    # ISCE3 workflow job
    if not project_id:
        return {"error": "missing_param", "message": "Provide project_id (ISCE3 jobs), work_dir (MintPy jobs), batch_dir (batch jobs), or output_dir (download jobs)"}

    try:
        project = Project.load(project_id)
    except (KeyError, FileNotFoundError):
        return _project_error(project_id)

    try:
        job = Job.load(job_id, project.jobs_dir())
    except FileNotFoundError:
        return _job_error(job_id)

    # PID-based liveness check
    if job.status == "running" and job.pid is not None:
        alive = True
        try:
            os.kill(job.pid, 0)
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
            _finalize_job_status_from_artifacts(job, project.jobs_dir())

    result = {
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
    if include_logs:
        if job.log_path and Path(job.log_path).exists():
            result["log_content"] = Path(job.log_path).read_text(errors="replace")
        else:
            result["log_content"] = None
    return result


def insar_get_job_status(job_id: str, project_id: str) -> dict:
    """Return job state. Use insar_get_job(job_id, project_id) instead."""
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
            _finalize_job_status_from_artifacts(job, project.jobs_dir())

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


def insar_get_job_logs(job_id: str, project_id: str, tail: int = 0) -> dict:
    """Return log content. Use insar_get_job(job_id, project_id, include_logs=True) instead."""
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

    artifacts = []
    candidate_dirs = [project.outputs_dir() / job_id]
    if project.outputs_dir() not in candidate_dirs:
        candidate_dirs.append(project.outputs_dir())
    if project.engine == "isce2":
        candidate_dirs.extend(
            [
                Path(project.workspace_root) / "merged",
                Path(project.workspace_root) / "reference",
                Path(project.workspace_root) / "secondary",
                Path(project.workspace_root) / "geom_reference",
                Path(project.workspace_root) / "fine_interferogram",
                Path(project.workspace_root) / "fine_coreg",
            ]
        )

    seen_paths: set[str] = set()
    for outputs_dir in candidate_dirs:
        if not outputs_dir.exists():
            continue
        for f in sorted(outputs_dir.rglob("*")):
            if f.is_file():
                path_str = str(f)
                if path_str in seen_paths:
                    continue
                seen_paths.add(path_str)
                ext = f.suffix.lower()
                artifact_type, description, viewer = _TYPE_MAP.get(ext, ("other", "Output file", ""))
                artifacts.append({
                    "path": path_str,
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
    base_runconfig: str = "",
    *,
    dem: str,
    output_dir: str,
    reference: str = "auto",
    interaction_mode: str = "interactive",
) -> dict:
    """
    Generate single-reference ISCE3 stack runconfigs from a directory of RSLC files.

    Scans data_dir for NISAR RSLC .h5 files, selects a reference scene, and
    produces one runconfig per secondary scene together with batch runner scripts
    (run_all.sh, run_parallel.sh) and a stack_manifest.csv.

    Args:
        data_dir: Directory containing RSLC .h5 files (all are used).
        base_runconfig: Optional path to a template ISCE3 runconfig YAML.
            When omitted, use the built-in default `insar` template.
        dem: Path to the DEM file to inject into each runconfig.
        output_dir: Directory where runconfigs and runner scripts will be written.
        reference: Reference scene selector — 'auto' (earliest date), a YYYYMMDD
                   string, or an absolute RSLC file path.
    """
    try:
        interaction_mode = _normalize_interaction_mode(interaction_mode)
        result = prepare_stack(
            data_dir=data_dir,
            base_runconfig=base_runconfig or None,
            dem=dem,
            output_dir=output_dir,
            reference=reference,
        )
        result["run_command"] = f"bash {result['run_parallel_sh']} {result['output_dir']} <num_jobs>"
        _param_tuned = Path(data_dir) / "base_runconfig_param_tuned.yaml"
        result["param_tuned_found"] = _param_tuned.exists()
        result["param_tuned_base_runconfig"] = str(_param_tuned) if _param_tuned.exists() else None
        result.update(
            _prepare_handoff(
                interaction_mode=interaction_mode,
                handoff_reason=(
                    "Review the selected reference scene and generated stack manifest before "
                    "launching stack execution."
                ),
                review_artifacts=[
                    result["manifest_csv"],
                    result["run_parallel_sh"],
                    str(Path(result["output_dir"]) / "reference_date.txt"),
                ],
                next_recommended_action=(
                    f"insar_run_batch(batch_dir='{result['output_dir']}', max_jobs=<N>, "
                    f"interaction_mode='{interaction_mode}')"
                ),
            )
        )
        return result
    except FileNotFoundError as exc:
        return {"error": "path_not_found", "message": str(exc)}
    except ValueError as exc:
        return {"error": "invalid_input", "message": str(exc)}


@mcp.tool()
def insar_prepare_network(
    data_dir: str,
    base_runconfig: str = "",
    *,
    dem: str,
    output_dir: str,
    network_mode: str = "tbase",
    max_temporal_baseline_days: int = 36,
    connection_span: int = 3,
    pair_list: str = "",
    interaction_mode: str = "interactive",
) -> dict:
    """
    Generate ISCE3 runconfigs for an interferogram network from a directory of RSLC files.

    Scans data_dir for NISAR RSLC .h5 files, builds an interferogram pair list
    according to the chosen network strategy, and produces one runconfig per pair
    together with batch runner scripts (run_all.sh, run_parallel.sh) and pair
    list manifests.

    Args:
        data_dir: Directory containing RSLC .h5 files.
        base_runconfig: Optional path to a template ISCE3 runconfig YAML.
            When omitted, use the built-in default `insar` template.
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
        interaction_mode = _normalize_interaction_mode(interaction_mode)
        result = prepare_network(
            data_dir=data_dir,
            base_runconfig=base_runconfig or None,
            dem=dem,
            output_dir=output_dir,
            network_mode=network_mode,
            max_temporal_baseline_days=max_temporal_baseline_days,
            connection_span=connection_span,
            pair_list=pair_list or None,
        )
        result["run_command"] = f"bash {result['run_parallel_sh']} {result['output_dir']} <num_jobs>"
        result["gunw_pattern"] = f"{result['output_dir']}/runs/*/products/*.h5"
        _param_tuned = Path(data_dir) / "base_runconfig_param_tuned.yaml"
        result["param_tuned_found"] = _param_tuned.exists()
        result["param_tuned_base_runconfig"] = str(_param_tuned) if _param_tuned.exists() else None
        result.update(
            _prepare_handoff(
                interaction_mode=interaction_mode,
                handoff_reason=(
                    "Review the selected interferogram network and pair list before launching "
                    "network execution."
                ),
                review_artifacts=[
                    result["pairs_selected_txt"],
                    result["manifest_csv"],
                    result["run_parallel_sh"],
                ],
                next_recommended_action=(
                    f"insar_run_batch(batch_dir='{result['output_dir']}', max_jobs=<N>, "
                    f"interaction_mode='{interaction_mode}')"
                ),
            )
        )
        return result
    except FileNotFoundError as exc:
        return {"error": "path_not_found", "message": str(exc)}
    except ValueError as exc:
        return {"error": "invalid_input", "message": str(exc)}


@mcp.tool()
def insar_run_batch(
    batch_dir: str,
    max_jobs: int = 4,
    execution_mode: str = "parallel",
    python_bin: str | None = None,
    interaction_mode: str = "interactive",
) -> dict:
    """
    Execute a prepared stack or network batch by running its run_parallel.sh script.

    Call insar_prepare_stack or insar_prepare_network first to generate the scripts,
    then call this tool to launch execution. Returns job_id and log_path immediately;
    the batch runs in the background. Poll status with insar_get_job(batch_dir=...).

    Show log_path to the user — they can monitor real-time output with:
        tail -f <log_path>

    Args:
        batch_dir: Output directory used in insar_prepare_stack or insar_prepare_network
        max_jobs:  Maximum number of ISCE3 pairs to run in parallel (default: 4)

    Returns:
        job_id, pid, status, log_path, poll (ready-to-use insar_get_job call string)
    """
    import glob as _glob
    import subprocess

    try:
        interaction_mode = _normalize_interaction_mode(interaction_mode)
    except ValueError as exc:
        return {"error": "invalid_input", "message": str(exc)}

    execution_mode = (execution_mode or "parallel").strip().lower()
    if execution_mode not in {"parallel", "serial"}:
        return {
            "error": "invalid_input",
            "message": f"Unsupported execution_mode: {execution_mode!r}. Use 'parallel' or 'serial'.",
        }

    runner_name = "run_parallel.sh" if execution_mode == "parallel" else "run_all.sh"
    runner_path = Path(batch_dir) / runner_name
    if not runner_path.exists():
        return {
            "error": "not_prepared",
            "message": f"{runner_name} not found in {batch_dir!r}. "
                       "Call insar_prepare_stack or insar_prepare_network first.",
        }

    runconfigs = _glob.glob(str(Path(batch_dir) / "runconfigs" / "*.yaml"))
    num_pairs = len(runconfigs)
    if num_pairs == 0:
        return {
            "warning": "no_pairs_to_run",
            "message": f"No runconfig YAML files found in {batch_dir}/runconfigs/.",
        }

    # Detect batch_type from directory contents (network has pair_lists/, stack has reference_date.txt)
    if (Path(batch_dir) / "pair_lists").exists():
        batch_type = "network"
    else:
        batch_type = "stack"

    if execution_mode == "parallel":
        command = ["bash", str(runner_path), batch_dir, str(max_jobs)]
    else:
        command = ["bash", str(runner_path)]

    logs_dir = resolve_plugin_logs_dir(batch_dir, fallback_root=batch_dir)
    logs_dir.mkdir(parents=True, exist_ok=True)

    batch_job = BatchJob(
        batch_dir=batch_dir,
        batch_type=batch_type,
        num_pairs=num_pairs,
        run_parallel_sh=str(runner_path),
        max_jobs=max_jobs,
        command=command,
    )
    log_path = str(logs_dir / f"{batch_job.job_id}.log")
    batch_job.log_path = log_path
    batch_job.started_at = _utc_now()
    batch_job.status = "running"

    try:
        env = _conda_safe_env()
        if python_bin:
            env["PYTHON_BIN"] = python_bin
        running_count = min(max_jobs if execution_mode == "parallel" else 1, num_pairs)
        queued_count = max(num_pairs - running_count, 0)
        with open(log_path, "w") as log_file:
            proc = subprocess.Popen(
                command,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=env,
            )
        batch_job.pid = proc.pid
        batch_job.save()
    except Exception as exc:
        batch_job.status = "failed"
        batch_job.finished_at = _utc_now()
        batch_job.exit_code = -1
        batch_job.save()
        return {"error": "launch_failed", "message": str(exc)}

    return {
        "job_id": batch_job.job_id,
        "batch_dir": batch_dir,
        "batch_type": batch_type,
        "num_pairs": num_pairs,
        "pid": proc.pid,
        "status": "running",
        "state": "running",
        "running_count": running_count,
        "queued_count": queued_count,
        "failed_count": 0,
        "interaction_mode": interaction_mode,
        "execution_mode": execution_mode,
        "log_path": log_path,
        "command": shlex.join(command),
        "progress_hint": (
            f"Monitor with tail -f {log_path} and poll via "
            f'insar_get_job(job_id="{batch_job.job_id}", batch_dir="{batch_dir}")'
        ),
        "poll": f'insar_get_job(job_id="{batch_job.job_id}", batch_dir="{batch_dir}")',
    }


# ── Group 6: Utilities (M5) ───────────────────────────────────────────────────

@mcp.tool()
def insar_describe_rslc(
    reference_rslc: str = "",
    secondary_rslc: str = "",
    project_id: str = "",
) -> dict:
    """
    Summarize locally observable metadata for one RSLC or an RSLC pair.

    This tool is intended to support metadata-first parameter advisory flows.
    It reads facts from HDF5 when possible, falls back to filename-derived
    inference, and optionally attaches the current project processing context.
    """
    project = None
    runconfig = None
    if project_id:
        try:
            project = Project.load(project_id)
        except (KeyError, FileNotFoundError):
            return _project_error(project_id)
        runconfig = project.runconfig
        if not reference_rslc:
            reference_rslc = _safe_get_path(project.runconfig, "runconfig.groups.input_file_group.reference_rslc_file") or ""
        if not secondary_rslc:
            secondary_rslc = _safe_get_path(project.runconfig, "runconfig.groups.input_file_group.secondary_rslc_file") or ""

    if not reference_rslc:
        return {"error": "invalid_input", "message": "reference_rslc must not be empty"}

    paths = [reference_rslc]
    if secondary_rslc:
        paths.append(secondary_rslc)
    missing = [path for path in paths if not Path(path).exists()]
    if missing:
        return {"error": "path_not_found", "message": f"Files not found: {missing}"}

    try:
        result = describe_rslc_pair(
            reference_rslc,
            secondary_rslc or None,
            runconfig=runconfig,
            workflow=project.workflow if project else "insar",
            project_id=project.project_id if project else None,
            require_existing=True,
        )
    except Exception as exc:
        return {"error": "metadata_summary_failed", "message": str(exc)}

    return result


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
        mintpy_config:   Path to MintPy smallbaselineApp config (.cfg or .txt).
        dem_path:        Path to the DEM GeoTIFF used during preprocessing.
        conda_env:       Conda environment that contains MintPy and GDAL.
    """
    try:
        interaction_mode = _normalize_interaction_mode(interaction_mode)
    except ValueError as exc:
        return {"error": "invalid_input", "message": str(exc)}

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
            python_bin=python_bin,
            smallbaseline_bin=smallbaseline_bin,
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
        "interaction_mode": interaction_mode,
        "log_path": result["log_path"],
        "submitted_at": result["submitted_at"],
        "command": shlex.join(result.get("command", [])) if result.get("command") else "",
        "progress_hint": (
            f"Monitor with tail -f {result['log_path']} and poll via "
            f"insar_get_job(job_id='{job_id}', work_dir='{mintpy_work_dir}')"
        ),
        "poll": f"insar_get_job(job_id='{job_id}', work_dir='{mintpy_work_dir}')",
        "work_dir": mintpy_work_dir,
    }


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
    merged/baselines, and reference/IW*.xml.
    """
    try:
        interaction_mode = _normalize_interaction_mode(interaction_mode)
    except ValueError as exc:
        return {"error": "invalid_input", "message": str(exc)}

    stack_dir = Path(stack_work_dir)
    if not stack_dir.exists():
        return {"error": "path_not_found", "message": f"stack_work_dir not found: {stack_work_dir!r}"}

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
    return {
        "job_id": job_id,
        "pid": result["pid"],
        "status": result["status"],
        "interaction_mode": interaction_mode,
        "log_path": result["log_path"],
        "submitted_at": result["submitted_at"],
        "command": shlex.join(result.get("command", [])) if result.get("command") else "",
        "mintpy_config": result.get("mintpy_config", ""),
        "progress_hint": (
            f"Monitor with tail -f {result['log_path']} and poll via "
            f"insar_get_job(job_id='{job_id}', work_dir='{mintpy_work_dir}')"
        ),
        "poll": f"insar_get_job(job_id='{job_id}', work_dir='{mintpy_work_dir}')",
        "work_dir": mintpy_work_dir,
        "stack_work_dir": stack_work_dir,
    }


def insar_get_mintpy_status(job_id: str, mintpy_work_dir: str) -> dict:
    """Return MintPy job status. Use insar_get_job(job_id, work_dir=...) instead."""
    return insar_get_job(job_id=job_id, work_dir=mintpy_work_dir)


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
    output_dir: str,
    bbox: list[float] | None = None,
    aoi_path: str = "",
    freq: str = "A",
    margin: int = 20,
    n_workers: int = 8,
    chunk_rows: int = 256,
    proxy: str | None = None,
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
    dl_job = DownloadJob(output_dir=output_dir, n_files=len(h5_urls))
    job_id = dl_job.job_id
    logs_dir = Path(output_dir) / ".insar_agent" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path_obj = logs_dir / f"nisar_download_{job_id}.log"
    params_path = logs_dir / f"nisar_download_{job_id}_params.json"
    log_path_obj.touch()
    params_path.write_text(json.dumps(params, indent=2, ensure_ascii=False), encoding="utf-8")
    log_path = str(log_path_obj)
    params_file = str(params_path)
    runner_file = str(logs_dir / f"nisar_download_{job_id}_run.py")
    dl_job.log_path = log_path

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
            )
    except Exception as exc:
        return {"error": "launch_failed", "message": str(exc)}

    dl_job.pid = proc.pid
    dl_job.save()

    return {
        "job_id": job_id,
        "status": "running",
        "pid": proc.pid,
        "n_files": len(h5_urls),
        "output_dir": output_dir,
        "log_path": log_path,
        "params_path": params_file,
        "poll": f'insar_get_job(job_id="{job_id}", output_dir="{output_dir}")',
    }


@mcp.tool()
def insar_download_dem(
    output_path: str,
    bbox: list[float] | None = None,
    aoi_path: str = "",
    source: str = "copernicus_30",
    margin_deg: float = 0.1,
    proxy: str | None = None,
    backend: str = "general",
    dem_type: str | None = None,
) -> dict:
    """Download a DEM covering the given bbox or AOI file."""
    try:
        resolved_bbox = _resolve_bbox_input(bbox=bbox, aoi_path=aoi_path)
    except FileNotFoundError as exc:
        return {"error": "path_not_found", "message": str(exc)}
    except ValueError as exc:
        return {"error": "invalid_input", "message": str(exc)}
    except Exception as exc:
        return {"error": "bbox_failed", "message": str(exc)}

    params = {
        "output_path": output_path,
        "bbox": list(bbox) if bbox is not None else None,
        "aoi_path": aoi_path,
        "source": source,
        "margin_deg": margin_deg,
        "proxy": proxy,
        "backend": backend,
        "dem_type": dem_type,
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

        return {
            "output_path": str(output),
            "source": isce2_dem_type,
            "bbox": list(resolved_bbox),
            "backend": backend,
            "command": command,
            "log": messages,
            "log_path": str(log_path),
            "params_path": str(params_path),
        }

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
    result["log_path"] = str(log_path)
    result["params_path"] = str(params_path)
    return result


# ── New tools: Sentinel download, S1 metadata, environment check ───────────────

@mcp.tool()
def insar_download_scene(
    urls: list[str],
    output_dir: str,
    n_workers: int = 4,
    proxy: str | None = None,
) -> dict:
    """
    Download Sentinel-1 or Sentinel-2 scene files (ZIP/SAFE) from provided URLs.

    Downloads files in parallel. Authentication uses ~/.netrc when needed.
    By default the download inherits the current system proxy settings.
    Pass proxy to temporarily override for this download only.

    Args:
        urls:       List of direct download URLs for S1/S2 ZIP or SAFE files.
        output_dir: Local directory to write downloaded files.
        n_workers:  Number of parallel download threads (default 4).
        proxy:      Optional HTTP proxy URL, e.g. "http://10.0.0.1:7890".
                    If omitted, inherits current system proxy settings.

    Returns:
        {ok: [{url, path, size_mb}], failed: [{url, error}], output_dir}
    """
    import concurrent.futures
    import urllib.request

    out_dir = Path(output_dir)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return {"error": "output_dir_not_writable", "message": str(exc)}

    proxy_env: dict[str, str] = {}
    if proxy:
        proxy_env["http_proxy"] = proxy
        proxy_env["https_proxy"] = proxy

    def _download_one(url: str) -> dict:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        rel_path = parsed.path.lstrip("/").split("?")[0] or f"scene_{uuid.uuid4().hex[:8]}"
        dest = out_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            size_mb = round(dest.stat().st_size / 1024 / 1024, 2)
            return {"url": url, "path": str(dest), "size_mb": size_mb, "skipped": True}
        try:
            opener = urllib.request.build_opener()
            if proxy:
                opener = urllib.request.build_opener(
                    urllib.request.ProxyHandler({"http": proxy, "https": proxy})
                )
            with opener.open(url) as response, dest.open("wb") as fh:
                shutil.copyfileobj(response, fh)
            if dest.exists():
                return {"url": url, "path": str(dest),
                        "size_mb": round(dest.stat().st_size / 1024 / 1024, 2)}
            return {"url": url, "error": "file not created after download"}
        except Exception as exc:
            return {"url": url, "error": str(exc)}

    _, log_path, params_path = _prepare_tool_log(
        [output_dir],
        "sentinel_scene",
        {"urls": urls, "output_dir": output_dir, "n_workers": n_workers, "proxy": proxy},
        fallback_root=Path(output_dir).expanduser().parent,
    )
    ok: list[dict] = []
    failed: list[dict] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as pool:
        futures = {pool.submit(_download_one, u): u for u in urls}
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if "error" in res:
                failed.append(res)
                _append_log(log_path, f"FAILED {res['url']}: {res['error']}")
            else:
                ok.append(res)
                _append_log(log_path, f"OK {res['url']} -> {res['path']}")

    return {
        "ok": ok,
        "failed": failed,
        "output_dir": output_dir,
        "log_path": str(log_path),
        "params_path": str(params_path),
    }


@mcp.tool()
def insar_describe_s1(zip_path: str) -> dict:
    """
    Parse Sentinel-1 SAFE/ZIP metadata and return key scene information.

    Reads manifest.safe and annotation XML from inside the SAFE package
    without full extraction. Works with both .zip archives and unpacked
    .SAFE directories.

    Args:
        zip_path: Absolute path to a Sentinel-1 .zip archive or .SAFE directory.

    Returns:
        {
            "scene_id": str,
            "satellite": "S1A" | "S1B",
            "mode": "IW" | "EW" | ...,
            "polarizations": ["VV", "VH"],
            "pass_direction": "ASCENDING" | "DESCENDING",
            "relative_orbit": int,
            "absolute_orbit": int,
            "start_time": str (ISO8601),
            "stop_time": str (ISO8601),
            "bbox": [west, south, east, north],
        }
    """
    p = Path(zip_path)
    if not p.exists():
        return {"error": "path_not_found", "message": f"Path does not exist: {zip_path!r}"}

    try:
        scene_id, info = _read_safe_metadata(p)
        info["scene_id"] = scene_id
        return info
    except FileNotFoundError as exc:
        return {"error": "manifest_not_found", "message": str(exc)}
    except ValueError as exc:
        return {"error": "invalid_format", "message": str(exc)}
    except zipfile.BadZipFile:
        return {"error": "invalid_zip", "message": f"Cannot open as ZIP: {zip_path!r}"}
    except Exception as exc:
        return {"error": "parse_failed", "message": str(exc)}


def _launch_sentinel_prepare_background(params: dict) -> dict:
    root = Path(params["project_root"]).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    logs_dir = resolve_plugin_logs_dir(root, fallback_root=root)
    logs_dir.mkdir(parents=True, exist_ok=True)
    job = DownloadJob(output_dir=str(root), n_files=len(params.get("source_paths") or []))
    log_path = logs_dir / f"sentinel_prepare_{job.job_id}.log"
    params_path = logs_dir / f"sentinel_prepare_{job.job_id}_params.json"
    runner_path = logs_dir / f"sentinel_prepare_{job.job_id}_run.py"
    log_path.touch()
    params_path.write_text(json.dumps(params, indent=2, ensure_ascii=False), encoding="utf-8")

    src_dir = str(Path(__file__).resolve().parent.parent.parent)
    runner_script = f"""\
import json
import sys
import traceback
sys.path.insert(0, {src_dir!r})
from insar_agent.engines.isce2.sentinel_prep import prepare_sentinel_data
from insar_agent.mcp.server import insar_download_dem

with open({str(params_path)!r}, encoding="utf-8") as _f:
    _params = json.load(_f)

try:
    _result = prepare_sentinel_data(**_params, dem_downloader=insar_download_dem)
    print(json.dumps({{"status": "done", "result": _result}}, ensure_ascii=False), flush=True)
except Exception as _exc:
    print(json.dumps({{"status": "failed", "error": str(_exc), "traceback": traceback.format_exc()}}, ensure_ascii=False), flush=True)
"""
    runner_path.write_text(runner_script, encoding="utf-8")
    job.log_path = str(log_path)

    try:
        with open(log_path, "w", encoding="utf-8") as log_file:
            proc = subprocess.Popen(
                [sys.executable, str(runner_path)],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=_conda_safe_env(),
            )
    except Exception as exc:
        return {"error": "launch_failed", "message": str(exc), "log_path": str(log_path), "params_path": str(params_path)}

    job.pid = proc.pid
    job.save()
    return {
        "job_id": job.job_id,
        "status": "running",
        "pid": proc.pid,
        "output_dir": str(root),
        "n_files": job.n_files,
        "log_path": str(log_path),
        "params_path": str(params_path),
        "poll": f'insar_get_job(job_id="{job.job_id}", output_dir="{root}")',
    }


@mcp.tool()
def insar_prepare_sentinel_data(
    project_root: str,
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
    background: bool = False,
) -> dict:
    """
    Organize Sentinel-1 SAFE inputs into grouped SAFE paths for later ISCE2 use.

    This tool only prepares grouped SAFE outputs. It can organize existing
    SAFE/ZIP inputs or synthesize lightweight SAFE directories from local burst
    files. It can also optionally prepare DEM and Sentinel-1 orbit files for
    downstream ISCE2 workflows.
    """
    params = {
        "project_root": project_root,
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
    }
    if background:
        return _launch_sentinel_prepare_background(params)

    try:
        return prepare_sentinel_data(
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
            dem_downloader=insar_download_dem,
        )
    except FileNotFoundError as exc:
        return {"error": "path_not_found", "message": str(exc)}
    except FileExistsError as exc:
        return {"error": "target_exists", "message": str(exc)}
    except ValueError as exc:
        return {"error": "invalid_input", "message": str(exc)}
    except Exception as exc:
        return {"error": "prepare_failed", "message": str(exc)}

@mcp.tool()
def insar_check_env() -> dict:
    """
    Check the project environment status: conda envs, MCP registration, and skills.

    Probes each expected conda environment by attempting to import its key package.
    Also checks MCP server registration and installed Claude Code skills.

    Returns:
        {
            "envs": {"isce3": {"status": "ok"|"missing", "version": ...}, ...},
            "mcp": {"registered": bool, "server_name": str},
            "skills": {"installed": [...], "missing": [...]},
            "install_hints": {env_name: "conda install ..." for missing envs},
        }
    """
    envs_to_check = {
        "isce3gpu": {
            "probe": "import isce3; print(isce3.__version__)",
            "install": "conda create -n isce3gpu -c conda-forge isce3 cudatoolkit -y",
        },
        "isce3": {
            "probe": "import isce3; print(isce3.__version__)",
            "install": "conda create -n isce3 -c conda-forge isce3 -y",
        },
        "mintpy": {
            "probe": "import mintpy; print(mintpy.__version__)",
            "install": "conda create -n mintpy -c conda-forge mintpy -y",
        },
        "isce2": {
            "probe": "import isce; print(isce.__version__)",
            "install": "conda create -n isce2 -c conda-forge isce2 -y",
        },
    }

    env_results: dict[str, dict] = {}
    install_hints: dict[str, str] = {}

    for env_name, cfg in envs_to_check.items():
        try:
            result = subprocess.run(
                ["conda", "run", "-n", env_name, "--no-capture-output",
                 "python", "-c", cfg["probe"]],
                capture_output=True,
                text=True,
                timeout=30,
                env=_conda_safe_env(),
            )
            if result.returncode == 0:
                version = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "unknown"
                env_results[env_name] = {"status": "ok", "version": version}
            else:
                env_results[env_name] = {"status": "missing", "error": result.stderr.strip()[:200]}
                install_hints[env_name] = cfg["install"]
        except FileNotFoundError:
            env_results[env_name] = {"status": "missing", "error": "conda not found in PATH"}
            install_hints[env_name] = cfg["install"]
        except subprocess.TimeoutExpired:
            env_results[env_name] = {"status": "timeout", "error": "probe timed out after 30s"}

    # Check MCP registration via claude mcp list
    mcp_status: dict = {"registered": False, "server_name": "insar-mcp-server"}
    try:
        result = subprocess.run(
            ["claude", "mcp", "list"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and "insar-mcp-server" in result.stdout:
            mcp_status["registered"] = True
        mcp_status["raw_output"] = result.stdout.strip()[:500]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        mcp_status["error"] = "claude CLI not found or timed out"

    # Check installed skills
    expected_skills = [
        "env-setup", "insar-agent", "data-prep", "data-prep-nisar", "data-prep-sentinel",
        "d-insar-isce3", "stack-insar-isce3", "param-advisor", "mintpy",
        "d-insar-isce2", "stack-insar-isce2",
    ]
    installed_skills: list[str] = []
    try:
        result = subprocess.run(
            ["claude", "plugin", "list"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        raw = result.stdout
        installed_skills = [s for s in expected_skills if s in raw]
        missing_skills = [s for s in expected_skills if s not in installed_skills]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        missing_skills = expected_skills

    skills_status = {
        "installed": installed_skills,
        "missing": missing_skills,
    }
    if missing_skills:
        skills_status["hint"] = (
            "Run: claude plugin marketplace add /home/august/insar-agent --scope project "
            "&& claude plugin install insar-agent-skills@insar-agent"
        )

    return {
        "envs": env_results,
        "mcp": mcp_status,
        "skills": skills_status,
        "install_hints": install_hints,
    }


# ── CLI entry point ────────────────────────────────────────────────────────────

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
