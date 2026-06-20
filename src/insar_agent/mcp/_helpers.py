"""Protocol-light helper functions shared by the MCP tool modules.

Defined together in one module so inter-helper calls resolve locally.  The
shared foundation (imports + constants + ``mcp``) is imported from ``_app``,
which declares ``__all__`` covering the underscore-prefixed constants.
"""
from __future__ import annotations

from insar_agent.mcp._app import *  # noqa: F403  (foundation: imports + constants + mcp)


def _conda_safe_env(overrides: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    for key, value in _CONDA_SAFE_DEFAULTS.items():
        env.setdefault(key, value)
    if overrides:
        env.update(overrides)
    return env


def _launch_detached_shell_job(
    shell_command: str,
    *,
    cwd: str | Path,
    env: dict[str, str],
    log_path: str | Path,
) -> int:
    launcher_command = (
        f"nohup bash -lc {shlex.quote(shell_command)} "
        f"> {shlex.quote(str(log_path))} 2>&1 < /dev/null & "
        "printf '%s\\n' \"$!\""
    )
    proc = subprocess.Popen(
        ["bash", "-lc", launcher_command],
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    if not hasattr(proc, "communicate"):
        return proc.pid
    result = proc.communicate(timeout=10)
    if not (isinstance(result, tuple) and len(result) == 2):
        return proc.pid
    stdout, stderr = result
    if not isinstance(stdout, str):
        return proc.pid
    if proc.returncode:
        message = stderr.strip() or stdout.strip() or f"launcher exited with {proc.returncode}"
        raise RuntimeError(message)
    pid_text = stdout.strip().splitlines()[-1]
    return int(pid_text)


def _ensure_logging_group(runconfig: dict, logs_dir: Path) -> None:
    """Backfill the ISCE3 logging block required by official workflows."""
    groups = runconfig.setdefault("runconfig", {}).setdefault("groups", {})
    logging_cfg = groups.setdefault("logging", {})
    if not logging_cfg.get("path"):
        logging_cfg["path"] = str(logs_dir / "insar_workflow.log")
    logging_cfg.setdefault("write_mode", "w")


def _ensure_project_logging(project: Project) -> None:
    """Ensure both live and template runconfigs carry a writable logging path."""
    logs_dir = project.logs_dir()
    _ensure_logging_group(project.runconfig, logs_dir)
    if project.runconfig_template:
        _ensure_logging_group(project.runconfig_template, logs_dir)


def _normalize_isce3_output_paths(project: Project) -> None:
    """Legacy path normaliser: resolve relative paths and create directories.

    Kept for backward compatibility.  New code should prefer
    ``_apply_run_layout_to_runconfig``.
    """
    product_path_key = "runconfig.groups.product_path_group.product_path"
    scratch_path_key = "runconfig.groups.product_path_group.scratch_path"
    sas_output_key = "runconfig.groups.product_path_group.sas_output_file"

    try:
        product_path = get_path(project.runconfig, product_path_key)
    except KeyError:
        product_path = None
    try:
        scratch_path = get_path(project.runconfig, scratch_path_key)
    except KeyError:
        scratch_path = None
    try:
        sas_output_file = get_path(project.runconfig, sas_output_key)
    except KeyError:
        sas_output_file = None

    workspace_root = Path(project.workspace_root).resolve()
    if isinstance(product_path, str) and product_path:
        product_dir = Path(product_path)
        resolved_product_dir = product_dir.resolve()
        if resolved_product_dir.is_relative_to(workspace_root):
            product_dir.mkdir(parents=True, exist_ok=True)
        if isinstance(sas_output_file, str) and sas_output_file and not Path(sas_output_file).is_absolute():
            set_path(project.runconfig, sas_output_key, str(product_dir / sas_output_file))

    if isinstance(scratch_path, str) and scratch_path:
        scratch_dir = Path(scratch_path)
        if scratch_dir.resolve().is_relative_to(workspace_root):
            scratch_dir.mkdir(parents=True, exist_ok=True)


def _redact_sensitive_params(value: object) -> object:
    if isinstance(value, dict):
        return {
            str(key): "<redacted>" if str(key).lower() in _SENSITIVE_PARAM_KEYS else _redact_sensitive_params(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_sensitive_params(item) for item in value]
    return value


def _run_root_logs_dir(*paths: str | Path | None) -> Path | None:
    for raw in paths:
        if raw in (None, ""):
            continue
        run_root = infer_run_root(raw)
        if run_root is not None:
            return run_root / "logs"
    return None


def _task_root_from_run_root(run_root: Path) -> Path:
    # New layout: run_root is <output_root>/<task>_<run_id>; agent-state is in run_root itself.
    # Return run_root itself as the "task root" since .insar_agent is a direct child.
    return run_root


def _task_jobs_dir_from_run_root(run_root: Path) -> Path:
    return run_root / ".insar_agent" / "jobs"


def _task_job_context_from_path(path: str | Path) -> dict | None:
    run_root = find_run_root(path)
    if run_root is None:
        return None
    # New layout: <output_root>/<task>_<run_id>; output_root is the direct parent.
    output_root = run_root.parent
    return {
        "workspace_root": str(output_root),
        "task_id": run_root.name,
        "run_id": run_root.name,
        "run_root": str(run_root),
        "jobs_dir": _task_jobs_dir_from_run_root(run_root),
    }


def _task_job_context(workspace_root: str = "", task_id: str = "", path: str | Path | None = None) -> dict | None:
    if workspace_root.strip() and task_id.strip():
        workspace = Path(workspace_root).expanduser().resolve()
        task = task_id.strip()
        context = {
            "workspace_root": str(workspace),
            "task_id": task,
            "jobs_dir": DownloadJob.jobs_dir_for_task(workspace, task),
        }
        if path is not None:
            run_context = _task_job_context_from_path(path)
            if run_context is not None:
                context.update({"run_id": run_context["run_id"], "run_root": run_context["run_root"]})
        return context
    if path is not None:
        return _task_job_context_from_path(path)
    return None


def _task_job_poll(job_id: str, job_context: dict, *, include_logs: bool = False) -> str:
    poll = (
        f'insar_get_job(job_id="{job_id}", '
        f'workspace_root="{job_context["workspace_root"]}", '
        f'task_id="{job_context["task_id"]}"'
    )
    if include_logs:
        poll += ", include_logs=True"
    return poll + ")"


def _resolve_task_run_id(workspace_root: str, task_id: str, run_id: str = "") -> str:
    """Run id to use for an input tool: explicit run_id, else the project's pinned
    run_id (so DEM/RSLC/prep join the same run as the workflow), else '' (mint fresh)."""
    if run_id.strip():
        return run_id.strip()
    proj = Project.load_for_task(workspace_root, task_id)
    return proj.run_id if (proj and proj.run_id) else ""


def _honor_output_path(
    output_path: str,
    workspace_root: str = "",
    task_id: str = "",
    run_id: str = "",
) -> tuple[str, str, str, str]:
    """Honor a user-provided output path for a flexible-input/download tool.

    The path is honored exactly as given (expanded + resolved, never moved).
    When it genuinely lands inside a run dir
    (``<workspace>/<task_id>/outputs/<run_id>``) the run context is derived from
    it so background jobs still associate with the task; otherwise the supplied
    ``workspace_root``/``task_id``/``run_id`` are preserved unchanged.
    """
    resolved = Path(output_path).expanduser().resolve()
    run_root = find_run_root(resolved)
    if run_root is not None:
        output_root = run_root.parent
        return (
            str(resolved),
            str(output_root),
            run_root.name,
            run_root.name,
        )
    return str(resolved), workspace_root, task_id, run_id


def _task_root_pollution(workspace_root: str = "", task_id: str = "") -> dict | None:
    if not workspace_root.strip() or not task_id.strip():
        return None
    task_root = Path(workspace_root).expanduser().resolve() / task_id.strip()
    if not task_root.exists() or not task_root.is_dir():
        return None
    polluting_paths = sorted(
        str(path)
        for path in task_root.iterdir()
        if path.name not in _TASK_ROOT_MANAGEMENT_DIRS
    )
    if not polluting_paths:
        return None
    return {
        "error": "task_root_pollution",
        "message": "Active processing artifacts must be under workspace/<task_id>/outputs/<run_id> or a user custom output root.",
        "workspace_root": str(task_root.parent),
        "task_id": task_root.name,
        "polluting_paths": polluting_paths,
    }


def _with_task_root_guard(result: dict, workspace_root: str = "", task_id: str = "") -> dict:
    pollution = _task_root_pollution(workspace_root, task_id)
    if pollution is None:
        return result
    from insar_agent.core.output_resolver import _strict_output
    if not _strict_output():
        guarded = dict(result)
        guarded["warning"] = pollution["error"]
        guarded["polluting_paths"] = pollution["polluting_paths"]
        return guarded
    guarded = dict(pollution)
    guarded["tool_result"] = result
    return guarded


def _prepare_tool_log(
    paths: list[str | Path | None],
    prefix: str,
    params: dict,
    *,
    fallback_root: str | Path | None = None,
) -> tuple[str, Path, Path]:
    job_id = uuid.uuid4().hex[:12]
    logs_dir = _run_root_logs_dir(*paths) or ((Path(fallback_root) / "logs") if fallback_root else Path.cwd() / "logs")
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"{prefix}_{job_id}.log"
    params_path = logs_dir / f"{prefix}_{job_id}_params.json"
    log_path.touch()
    params_path.write_text(json.dumps(_redact_sensitive_params(params), indent=2, ensure_ascii=False), encoding="utf-8")
    return job_id, log_path, params_path


def _append_log(log_path: Path, message: str) -> None:
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(f"{message}\n")


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
    except (OSError, ValueError):
        return None


def _normalize_interaction_mode(interaction_mode: str) -> str:
    mode = (interaction_mode or "interactive").strip().lower()
    if mode not in {"interactive", "auto"}:
        raise ValueError(
            f"Unsupported interaction_mode: {interaction_mode!r}. Use 'interactive' or 'auto'."
        )
    return mode


def _opencode_session_workspace_key(path: str | Path) -> str | None:
    parts = Path(path).parts
    for index, part in enumerate(parts):
        if len(parts) > index + 3 and part == ".opencode-test" and parts[index + 1] == "sessions":
            if parts[index + 3] == "workspace":
                return parts[index + 2]
    return None


def _validate_same_opencode_session_workspace(left: str | Path, right: str | Path) -> str | None:
    left_key = _opencode_session_workspace_key(left)
    right_key = _opencode_session_workspace_key(right)
    if left_key and right_key and left_key != right_key:
        return (
            "stack_work_dir and mintpy_work_dir must refer to the same OpenCode session workspace; "
            f"got {left_key!r} and {right_key!r}"
        )
    return None


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


def _workflow_log_has_failure(log_tail: str) -> bool:
    log_lower = log_tail.lower()
    if any(marker in log_lower for marker in WORKFLOW_LOG_FAILURE_SUBSTRINGS):
        return True
    return any(
        pattern.search(line)
        for line in log_tail.splitlines()
        for pattern in WORKFLOW_LOG_FAILURE_PATTERNS
    )


def _workflow_log_has_success(log_tail: str) -> bool:
    log_lower = log_tail.lower()
    return any(marker in log_lower for marker in WORKFLOW_LOG_SUCCESS_MARKERS)


def _finalize_job_status_from_artifacts(job: Job, jobs_dir: Path) -> None:
    """Update a finished workflow job using persisted exit code or log markers."""
    log_tail = _read_log_tail(job.log_path, n=WORKFLOW_LOG_TAIL_LINES)
    failed = _workflow_log_has_failure(log_tail)
    succeeded = _workflow_log_has_success(log_tail)
    exit_code = _read_exit_code(job.exit_code_path)
    requires_success_marker = job.engine == "isce2" and job.workflow == "stack"

    if exit_code is not None and not failed and (not requires_success_marker or succeeded):
        job.status = "done" if exit_code == 0 else "failed"
        job.exit_code = exit_code
    else:
        job.status = "done" if succeeded and not failed else "failed"
        job.exit_code = 0 if succeeded and not failed else 1
    job.finished_at = _utc_now()
    job.save(jobs_dir)


def _job_result(job: Job, include_logs: bool = False) -> dict:
    result: dict = {
        "job_id": job.job_id,
        "project_id": job.project_id,
        "engine": job.engine,
        "workflow": job.workflow,
        "status": job.status,
        "pid": job.pid,
        "exit_code": job.exit_code,
        "submitted_at": job.submitted_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "log_path": job.log_path,
        "output_paths": job.output_paths,
        "runconfig_path": job.runconfig_path,
        "task_id": job.task_id,
        "run_id": job.run_id,
        "run_root": job.run_root,
        "tool_name": job.tool_name,
        "job_type": job.job_type,
    }
    if include_logs:
        if job.log_path and Path(job.log_path).exists():
            result["log_content"] = Path(job.log_path).read_text(errors="replace")
        else:
            result["log_content"] = None
    return result


def _refresh_workflow_job_status(job: Job, jobs_dir: Path) -> Job:
    if job.status != "running":
        return job

    if _read_exit_code(job.exit_code_path) is not None:
        _finalize_job_status_from_artifacts(job, jobs_dir)
        return job

    if job.pid is None:
        return job

    alive = True
    try:
        os.kill(job.pid, 0)
        state_line = next(
            (ln for ln in Path(f"/proc/{job.pid}/status").read_text().splitlines() if ln.startswith("State:")),
            "",
        )
        if "Z" in state_line:
            alive = False
    except PermissionError:
        return job
    except (ProcessLookupError, FileNotFoundError):
        alive = False

    if not alive:
        log_tail = _read_log_tail(job.log_path, n=WORKFLOW_LOG_TAIL_LINES)
        if (
            _read_exit_code(job.exit_code_path) is not None
            or _workflow_log_has_failure(log_tail)
            or _workflow_log_has_success(log_tail)
        ):
            _finalize_job_status_from_artifacts(job, jobs_dir)
        # else: exitcode file not yet flushed, no clear outcome in log;
        # keep status as running so the next poll can read the exitcode file
    return job


def _find_reusable_workflow_job(project: Project) -> Job | None:
    jobs_dir = project.jobs_dir()
    if not jobs_dir.exists():
        return None

    reusable_statuses = {"running", "done"}
    candidates: list[Job] = []
    for job_file in jobs_dir.glob("*.json"):
        try:
            job = Job.load(job_file.stem, jobs_dir)
        except (FileNotFoundError, json.JSONDecodeError, TypeError):
            continue
        if (
            job.project_id == project.project_id
            and job.engine == project.engine
            and job.workflow == project.workflow
        ):
            refreshed = _refresh_workflow_job_status(job, jobs_dir)
            if refreshed.status in reusable_statuses:
                candidates.append(refreshed)

    candidates.sort(
        key=lambda item: item.started_at if item.started_at is not None else item.submitted_at,
        reverse=True,
    )
    return candidates[0] if candidates else None


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


def _coerce_processing_param_value(value: object, meta: dict) -> object:
    if meta.get("type") == "bool" and isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    return value


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


def _is_bbox(value: object) -> TypeGuard[list[float] | tuple[float, float, float, float]]:
    return (
        isinstance(value, list | tuple)
        and len(value) == 4
        and all(isinstance(item, int | float) for item in value)
    )


def _bbox_intersects(a: list[float], b: list[float] | tuple[float, float, float, float]) -> bool:
    return a[0] <= b[2] and a[2] >= b[0] and a[1] <= b[3] and a[3] >= b[1]


def _sentinel_scene_paths_for_isce2(params: dict, workflow: str) -> list[Path]:
    if workflow == "tops":
        return [Path(str(params[key])) for key in ("reference_safe", "secondary_safe") if params.get(key)]
    if workflow == "stack" and params.get("slc_dir"):
        slc_dir = Path(str(params["slc_dir"]))
        safe_dirs = [path for path in slc_dir.glob("*.SAFE") if path.is_dir()]
        zip_files = [path for path in slc_dir.glob("*.zip") if path.is_file()]
        zip_files.extend(path for path in slc_dir.glob("*.ZIP") if path.is_file())
        return sorted(safe_dirs + zip_files)
    return []


def _validate_isce2_safe_annotation_geolocation(params: dict, workflow: str) -> list[str]:
    errors: list[str] = []
    for scene_path in _sentinel_scene_paths_for_isce2(params, workflow):
        if not scene_path.is_dir() or scene_path.suffix.upper() != ".SAFE":
            continue
        try:
            scene_id, metadata = _read_safe_metadata(scene_path)
        except (FileNotFoundError, ValueError, zipfile.BadZipFile):
            continue
        scene_bbox = metadata.get("bbox")
        if not _is_bbox(scene_bbox):
            continue
        annotation_dir = scene_path / "annotation"
        if not annotation_dir.is_dir():
            continue
        for annotation_path in annotation_dir.glob("*.xml"):
            result = check_annotation_geolocation_grid(annotation_path.read_text(encoding="utf-8"), scene_bbox)
            if result["status"] != "invalid":
                continue
            errors.append(
                "Sentinel-1 SAFE annotation geolocation is inconsistent with manifest footprint: "
                f"scene={scene_id!r}, annotation={str(annotation_path)!r}, reason={result['reason']}. "
                "Regenerate or replace the SAFE before running ISCE2."
            )
    return errors


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

    job = _refresh_workflow_job_status(job, project.jobs_dir())

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


def _launch_dem_download_background(params: dict) -> dict:
    output_path = Path(params["output_path"]).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_root = find_run_root(output_path)
    output_dir = run_root or output_path.parent

    # Prefer project_id-derived job context (prepare/ path has no run-root ancestor).
    _pid = str(params.get("project_id") or "").strip()
    if _pid:
        try:
            _proj = Project.load(_pid)
        except (KeyError, FileNotFoundError):
            return {"error": "project_not_found", "message": f"Project {_pid!r} not found"}
        _jobs_dir = Path(_proj.output_root) / ".insar_agent" / "jobs"
        job_context = {
            "workspace_root": _proj.output_root,
            "task_id": _proj.task or _proj.task_id or "",
            "run_id": _proj.run_id or "",
            "run_root": str(run_root) if run_root else "",
            "jobs_dir": _jobs_dir,
        }
    else:
        job_context = _task_job_context(
            workspace_root=str(params.get("workspace_root") or ""),
            task_id=str(params.get("task_id") or ""),
            path=output_path,
        )
        if job_context is None:
            return {
                "error": "missing_task_context",
                "message": "Background DEM downloads must be associated with a project_id or <workspace>/<task_id>; provide project_id, workspace_root+task_id, or an output_path under a run root.",
            }
    logs_dir = output_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    job = DownloadJob(
        output_dir=str(output_dir),
        n_files=1,
        task_id=job_context.get("task_id"),
        run_id=job_context.get("run_id"),
        run_root=job_context.get("run_root"),
        tool_name="insar_download_dem",
        job_type="dem_download",
        output_path=str(output_path),
    )
    log_path = logs_dir / f"sentinel_dem_{job.job_id}.log"
    params_path = logs_dir / f"sentinel_dem_{job.job_id}_params.json"
    runner_path = logs_dir / f"sentinel_dem_{job.job_id}_run.py"
    params_for_disk = {**params, "background": False}
    dem_proxy = params_for_disk.pop("proxy", None)
    params_for_disk["proxy"] = None
    params_path.write_text(json.dumps(params_for_disk, indent=2, ensure_ascii=False), encoding="utf-8")

    src_dir = str(Path(__file__).resolve().parent.parent.parent)
    runner_script = f"""\
import json
import os
import sys
import traceback
sys.path.insert(0, {src_dir!r})
from insar_agent.mcp.server import insar_download_dem

with open({str(params_path)!r}, encoding="utf-8") as _f:
    _params = json.load(_f)
_dem_proxy = os.environ.get("INSAR_AGENT_DEM_PROXY")
if _dem_proxy is not None:
    _params["proxy"] = _dem_proxy

try:
    _result = insar_download_dem(**_params)
    if isinstance(_result, dict) and _result.get("error"):
        print("ERROR: " + json.dumps(_result, ensure_ascii=False), flush=True)
    else:
        print(json.dumps({{"status": "done", "result": _result}}, ensure_ascii=False), flush=True)
except Exception as _exc:
    print(json.dumps({{"status": "failed", "error": str(_exc), "traceback": traceback.format_exc()}}, ensure_ascii=False), flush=True)
"""
    runner_path.write_text(runner_script, encoding="utf-8")
    log_path.touch()
    job.log_path = str(log_path)
    job.params_path = str(params_path)

    try:
        with open(log_path, "w", encoding="utf-8") as log_file:
            proc = subprocess.Popen(
                [sys.executable, str(runner_path)],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=_conda_safe_env({"INSAR_AGENT_DEM_PROXY": str(dem_proxy)} if dem_proxy is not None else None),
                start_new_session=True,
            )
    except Exception as exc:
        return {"error": "launch_failed", "message": str(exc), "log_path": str(log_path), "params_path": str(params_path)}

    job.pid = proc.pid
    job.save(Path(job_context["jobs_dir"]))
    return {
        "job_id": job.job_id,
        "status": "running",
        "pid": proc.pid,
        "output_path": str(output_path),
        "output_dir": str(output_dir),
        "n_files": job.n_files,
        "log_path": str(log_path),
        "params_path": str(params_path),
        "workspace_root": job_context.get("workspace_root"),
        "task_id": job_context.get("task_id"),
        "run_id": job_context.get("run_id"),
        "run_root": job_context.get("run_root"),
        "poll": _task_job_poll(job.job_id, job_context, include_logs=True),
    }


def _launch_sentinel_prepare_background(params: dict) -> dict:
    root = Path(params["project_root"]).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    job_context = _task_job_context(
        workspace_root=str(params.get("workspace_root") or ""),
        task_id=str(params.get("task_id") or ""),
        path=root,
    )
    if job_context is None:
        return {
            "error": "missing_task_context",
            "message": "Background Sentinel preparation must be associated with <workspace>/<task_id>; provide workspace_root and task_id or a project_root under outputs/<run_id>.",
        }
    logs_dir = (infer_run_root(root) or root) / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    job = DownloadJob(
        output_dir=str(root),
        n_files=len(params.get("source_paths") or []),
        task_id=job_context.get("task_id"),
        run_id=job_context.get("run_id"),
        run_root=job_context.get("run_root"),
        tool_name="insar_prepare_sentinel_data",
        job_type="sentinel_prepare",
    )
    log_path = logs_dir / f"sentinel_prepare_{job.job_id}.log"
    params_path = logs_dir / f"sentinel_prepare_{job.job_id}_params.json"
    runner_path = logs_dir / f"sentinel_prepare_{job.job_id}_run.py"
    log_path.touch()
    orbit_password = params.get("orbit_password")
    params_for_disk = {key: value for key, value in params.items() if key != "orbit_password"}
    params_path.write_text(json.dumps(params_for_disk, indent=2, ensure_ascii=False), encoding="utf-8")

    src_dir = str(Path(__file__).resolve().parent.parent.parent)
    runner_script = f"""\
import json
import os
import sys
import traceback
sys.path.insert(0, {src_dir!r})
from insar_agent.engines.isce2.sentinel_prep import prepare_sentinel_data
from insar_agent.mcp.server import insar_download_dem

with open({str(params_path)!r}, encoding="utf-8") as _f:
    _params = json.load(_f)
_params.pop("workspace_root", None)
_params.pop("task_id", None)
_params.pop("run_id", None)
_orbit_password = os.environ.get("INSAR_AGENT_ORBIT_PASSWORD")
if _orbit_password is not None:
    _params["orbit_password"] = _orbit_password

try:
    _result = prepare_sentinel_data(**_params, dem_downloader=insar_download_dem)
    print(json.dumps({{"status": "done", "result": _result}}, ensure_ascii=False), flush=True)
except Exception as _exc:
    print(json.dumps({{"status": "failed", "error": str(_exc), "traceback": traceback.format_exc()}}, ensure_ascii=False), flush=True)
"""
    runner_path.write_text(runner_script, encoding="utf-8")
    job.log_path = str(log_path)
    job.params_path = str(params_path)

    env_overrides = {"INSAR_AGENT_ORBIT_PASSWORD": str(orbit_password)} if orbit_password else None
    try:
        with open(log_path, "w", encoding="utf-8") as log_file:
            proc = subprocess.Popen(
                [sys.executable, str(runner_path)],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env=_conda_safe_env(env_overrides),
                start_new_session=True,
            )
    except Exception as exc:
        return {"error": "launch_failed", "message": str(exc), "log_path": str(log_path), "params_path": str(params_path)}

    job.pid = proc.pid
    job.save(Path(job_context["jobs_dir"]))
    return {
        "job_id": job.job_id,
        "status": "running",
        "pid": proc.pid,
        "output_dir": str(root),
        "n_files": job.n_files,
        "log_path": str(log_path),
        "monitor": f"tail -f {log_path}",
        "params_path": str(params_path),
        "workspace_root": job_context.get("workspace_root"),
        "task_id": job_context.get("task_id"),
        "run_id": job_context.get("run_id"),
        "run_root": job_context.get("run_root"),
        "poll": _task_job_poll(job.job_id, job_context),
    }


def _configured_opencode_skill_sources(repo_root: Path) -> list[Path]:
    xdg_config_home = Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser()
    config_paths = [
        xdg_config_home / "opencode" / "opencode.json",
        repo_root / ".opencode" / "opencode.json",
    ]
    sources: list[Path] = []
    for config_path in config_paths:
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for source in config.get("skills", {}).get("sources", []):
            path = source.get("path")
            if not path:
                continue
            resolved = Path(path).expanduser().resolve()
            if resolved not in sources:
                sources.append(resolved)
    return sources


__all__ = [
    '_conda_safe_env',
    '_launch_detached_shell_job',
    '_ensure_logging_group',
    '_ensure_project_logging',
    '_normalize_isce3_output_paths',
    '_redact_sensitive_params',
    '_run_root_logs_dir',
    '_task_root_from_run_root',
    '_task_jobs_dir_from_run_root',
    '_task_job_context_from_path',
    '_task_job_context',
    '_task_job_poll',
    '_resolve_task_run_id',
    '_honor_output_path',
    '_task_root_pollution',
    '_with_task_root_guard',
    '_prepare_tool_log',
    '_append_log',
    '_utc_now',
    '_read_log_tail',
    '_read_exit_code',
    '_normalize_interaction_mode',
    '_opencode_session_workspace_key',
    '_validate_same_opencode_session_workspace',
    '_prepare_handoff',
    '_workflow_log_has_failure',
    '_workflow_log_has_success',
    '_finalize_job_status_from_artifacts',
    '_job_result',
    '_refresh_workflow_job_status',
    '_find_reusable_workflow_job',
    '_safe_get_path',
    '_engine_error',
    '_project_error',
    '_job_error',
    '_coerce_processing_param_value',
    '_validate_processing_param_type',
    '_validate_processing_param_structure',
    'insar_unset_runconfig_value',
    'insar_validate_runconfig',
    '_is_bbox',
    '_bbox_intersects',
    '_sentinel_scene_paths_for_isce2',
    '_validate_isce2_safe_annotation_geolocation',
    'insar_get_job_status',
    'insar_get_job_logs',
    'insar_extract_bbox',
    '_launch_dem_download_background',
    '_launch_sentinel_prepare_background',
    '_configured_opencode_skill_sources',
]
