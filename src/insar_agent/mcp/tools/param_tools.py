"""MCP tools: param_tools (registered on the shared FastMCP)."""

from __future__ import annotations

from insar_agent.mcp._app import *  # noqa: F403  (foundation: imports + constants + mcp)
from insar_agent.mcp._helpers import *  # noqa: F403  (shared helpers)


@mcp.tool()
def insar_record_param_advice(
    project_id: str,
    recommendation_package: dict,
    output_dir: str = "",
    task_id: str = "",
    format_version: str = "param-advisor.v1",
) -> dict:
    """Persist a fixed-format parameter advisory package for audit and papers."""
    try:
        project = Project.load(project_id)
    except (KeyError, FileNotFoundError):
        return _project_error(project_id)

    if not isinstance(recommendation_package, dict):
        return {"error": "invalid_recommendation_package", "message": "recommendation_package must be an object"}

    try:
        validate_param_advice_format_version(format_version)
    except ValueError as exc:
        return {"error": "invalid_format_version", "message": str(exc)}

    try:
        advice_dir = _param_advice_output_dir(project, output_dir, task_id)
    except ValueError as exc:
        return {"error": "invalid_output_dir", "message": str(exc)}

    try:
        advice_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return {"error": "output_dir_not_writable", "message": str(exc)}

    record = {
        "format_version": format_version,
        "created_at": _utc_now(),
        "project_id": project.project_id,
        "engine": project.engine,
        "workflow": project.workflow,
        "recommendation_package": recommendation_package,
    }
    json_path = advice_dir / "recommendation.json"
    markdown_path = advice_dir / "recommendation.md"
    try:
        json_path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        markdown_path.write_text(_render_param_advice_markdown(record), encoding="utf-8")
    except Exception as exc:
        return {"error": "write_failed", "message": str(exc)}

    return {
        "project_id": project.project_id,
        "advice_dir": str(advice_dir),
        "recommendation_json": str(json_path),
        "recommendation_markdown": str(markdown_path),
        "format_version": format_version,
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

        value = _coerce_processing_param_value(value, meta)
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
    value = _coerce_processing_param_value(value, meta)
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


@mcp.tool()
def insar_export_runconfig(project_id: str, output_dir: str = "") -> dict:
    """
    Render the current runconfig as a YAML file on disk.

    The exported file can be used directly with ISCE3 or reviewed by the user.
    Per-run exports should live under <workspace_root>/<task_id>/outputs/<run_id>/...
    so they do not pollute the task root.

    Args:
        project_id: Project UUID
        output_dir: Directory to write YAML into (default: a run-root configs directory)
    """
    try:
        project = Project.load(project_id)
    except (KeyError, FileNotFoundError):
        return _project_error(project_id)

    _ensure_project_logging(project)
    rl = RunLayout(
        output_root=project.output_root,
        task=project.task or project.task_id or project.name or project.project_id,
        run_id=project.run_id,
    )
    dest_dir = Path(output_dir.strip()) if output_dir.strip() else rl.configs_dir
    if output_dir.strip() and project.task_id:
        # Legacy-layout containment check (task_id-gated for backward compatibility).
        # For new-layout projects (task_id=None), no containment check is applied here.
        run_layout = _resolve_run_layout(project)
        if run_layout is not None:
            output_root_path = Path(project.output_root).expanduser().resolve()
            resolved_dest = dest_dir.expanduser().resolve()
            if resolved_dest.is_relative_to(output_root_path) and not resolved_dest.is_relative_to(run_layout.run_root.resolve()):
                return {
                    "error": "invalid_input",
                    "message": "output_dir must be inside the run root",
                }
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
