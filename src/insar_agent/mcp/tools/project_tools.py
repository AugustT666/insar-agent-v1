"""MCP tools: project_tools (registered on the shared FastMCP)."""

from __future__ import annotations

from insar_agent.mcp._app import *  # noqa: F403  (foundation: imports + constants + mcp)
from insar_agent.mcp._helpers import *  # noqa: F403  (shared helpers)


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


@mcp.tool()
def insar_create_project(
    engine: str,
    workflow: str,
    output_root: str = "",
    name: str = "",
    conda_env: str = "",
    # Deprecated: use output_root instead. Accepted for backwards compatibility.
    workspace_root: str = "",
    task_id: str = "",
) -> dict:
    """
    Create a new InSAR processing project.

    Initializes the run directory under ``<output_root>/<task>_<timestamp>/``,
    loads the default runconfig template for the chosen workflow, and registers
    the project for future lookups.

    Args:
        engine: Engine name, e.g. 'isce3' or 'isce2'
        workflow: Workflow name, e.g. 'insar', 'stack', or 'tops'
        output_root: Absolute path that will contain all run directories.
            Each run is created as ``<output_root>/<task>_<timestamp>/``.
        name: Human-readable project name (auto-generated if omitted)
        conda_env: Conda environment name for workflow execution (e.g. 'isce3')
        workspace_root: Deprecated alias for output_root.
        task_id: Deprecated override for the auto-derived task identifier.
    """
    # Resolve output_root — accept deprecated workspace_root as alias.
    effective_output_root = output_root.strip() or workspace_root.strip()
    if not effective_output_root:
        return {"error": "output_root_required", "message": "output_root is required"}

    if engine not in _ENGINES:
        return _engine_error(engine)

    workflow_names = {w.workflow for w in _ENGINES[engine].list_workflows()}
    if workflow not in workflow_names:
        return {"error": "workflow_not_found", "message": f"Workflow {workflow!r} not found for engine {engine!r}"}

    out = Path(effective_output_root)
    if not out.exists():
        try:
            out.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            return {"error": "output_root_not_writable", "message": str(exc)}
    elif not out.is_dir():
        return {"error": "output_root_not_writable", "message": f"{effective_output_root!r} exists but is not a directory"}

    # Derive the canonical task identifier via the engine adapter.
    task = _ENGINES[engine].task_id_for(workflow)

    # ISCE2 uses a flat param dict instead of a nested YAML runconfig
    if engine == "isce2":
        try:
            default_params = isce2_load_default_params(workflow)
        except FileNotFoundError as exc:
            return {"error": "template_not_found", "message": str(exc)}

        project_name = name.strip() or f"{engine}-{workflow}-{out.name}"
        project = new_project(
            name=project_name,
            engine=engine,
            workflow=workflow,
            output_root=str(out.resolve()),
            conda_env=conda_env.strip() or None,
            task=task,
        )
        from insar_agent.core.layout import make_run_id
        project.run_id = make_run_id()
        project.runconfig = default_params
        project.runconfig_template = default_params

        try:
            project.save()
        except Exception as exc:
            return {"error": "output_root_not_writable", "message": str(exc)}

        required = ISCE2_REQUIRED_PARAM_FIELDS.get(workflow, [])
        return {
            "project_id": project.project_id,
            "run_root": str(project.run_root()),
            "output_root": project.output_root,
            "task": project.task,
            "run_id": project.run_id,
            "name": project.name,
            "engine": project.engine,
            "workflow": project.workflow,
            "conda_env": project.conda_env,
            "created_at": project.created_at,
            "required_fields": required,
            "guidance": (
                "Set required path fields with insar_set_processing_param. "
                "Use insar_describe_s1 to inspect scene metadata (orbit, polarization, coverage). "
                "If you need to tune looks, filtering, ESD/coregistration, unwrapping, or stack connections, "
                "enter the param-advisor skill with engine=isce2 before validate/run. That skill must call "
                "insar_describe_s1, then delegate recommendation generation to the param-advisor subagent insar-agent-plugin:param-advisor before applying changes via "
                "insar_set_processing_param. "
                "For S1 time-series (workflow='stack'), set slc_dir to the directory containing "
                "all S1 SAFE/ZIP files, then call insar_run_workflow to run stackSentinel.py."
            ),
        }

    try:
        default_runconfig = load_default_runconfig(workflow)
    except FileNotFoundError as exc:
        return {"error": "template_not_found", "message": str(exc)}

    project_name = name.strip() or f"{engine}-{workflow}-{out.name}"
    project = new_project(
        name=project_name,
        engine=engine,
        workflow=workflow,
        output_root=str(out.resolve()),
        conda_env=conda_env.strip() or None,
        task=task,
    )
    from insar_agent.core.layout import make_run_id
    project.run_id = make_run_id()
    project.runconfig = default_runconfig
    project.runconfig_template = default_runconfig
    _ensure_project_logging(project)

    try:
        project.save()
    except Exception as exc:
        return {"error": "output_root_not_writable", "message": str(exc)}

    required = REQUIRED_PATH_FIELDS.get(workflow, [])
    return {
        "project_id": project.project_id,
        "run_root": str(project.run_root()),
        "output_root": project.output_root,
        "task": project.task,
        "run_id": project.run_id,
        "name": project.name,
        "engine": project.engine,
        "workflow": project.workflow,
        "conda_env": project.conda_env,
        "created_at": project.created_at,
        "required_fields": required,
        "guidance": (
            "Set required path fields with insar_set_runconfig_value. "
            "Use insar_describe_rslc to build a metadata summary before parameter tuning. "
            "If you need to tune multilook, filtering, unwrapping, or atmospheric corrections, "
            "enter the param-advisor skill with engine=isce3 before validate/export/run. That skill must "
            "call insar_describe_rslc, then delegate recommendation generation to the "
            "param-advisor subagent insar-agent-plugin:param-advisor before "
            "applying changes via insar_set_processing_param. The subagent may consult the "
            "engine-specific reference asset at references/param-advisor/param-advisor-isce{engine}.md and may use automatic "
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
