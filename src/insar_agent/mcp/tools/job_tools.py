"""MCP tools: job_tools (registered on the shared FastMCP)."""

from __future__ import annotations

from insar_agent.mcp._app import *  # noqa: F403  (foundation: imports + constants + mcp)
from insar_agent.mcp._helpers import *  # noqa: F403  (shared helpers)


@mcp.tool()
def insar_get_job(
    job_id: str,
    project_id: str = "",
    work_dir: str = "",
    batch_dir: str = "",
    output_dir: str = "",
    workspace_root: str = "",
    task_id: str = "",
    include_logs: bool = False,
) -> dict:
    """
    Return the current state of any job (ISCE3 workflow, MintPy, batch, or download).

    For ISCE3 workflow jobs: provide project_id.
    For MintPy jobs: provide work_dir (the mintpy_work_dir passed to insar_run_mintpy).
    For batch jobs (insar_run_batch): provide batch_dir (the output_dir of prepare_stack/network).
    For download/prep jobs: provide workspace_root and task_id; output_dir is accepted only to infer that task context from an outputs/<run_id> path.

    Args:
        job_id: Job UUID
        project_id: Parent project UUID (for ISCE3 workflow jobs)
        work_dir: MintPy work directory (for MintPy jobs)
        batch_dir: Batch output directory (for insar_run_batch jobs)
        output_dir: Download/prep output directory, used only to infer task context
        workspace_root: Top-level workspace root for task-level background jobs
        task_id: Workflow task_id for task-level background jobs
        include_logs: If true, include the full log content in the response
    """
    if output_dir or (workspace_root and task_id):
        output_path = Path(output_dir).expanduser() if output_dir else None
        if output_path is not None and not output_path.exists():
            return {"error": "path_not_found", "message": f"output_dir not found: {output_dir!r}"}
        job_context = _task_job_context(
            workspace_root=workspace_root,
            task_id=task_id,
            path=output_path,
        )
        if job_context is None:
            return {
                "error": "missing_task_context",
                "message": "Provide workspace_root and task_id, or an output_dir under <workspace>/<task_id>/outputs/<run_id>.",
            }
        jobs_dir = Path(job_context["jobs_dir"])
        try:
            dl_job = DownloadJob.load(job_id, jobs_dir)
        except ValueError as exc:
            return {"error": "invalid_job_id", "message": str(exc)}
        except FileNotFoundError:
            return {"error": "job_not_found", "message": f"No download/prep job {job_id!r} in {str(jobs_dir)!r}"}
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
                dl_job.save(jobs_dir)

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
            "task_id": dl_job.task_id,
            "run_id": dl_job.run_id,
            "run_root": dl_job.run_root,
            "tool_name": dl_job.tool_name,
            "job_type": dl_job.job_type,
            "output_path": dl_job.output_path,
            "params_path": dl_job.params_path,
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
        except ValueError as exc:
            return {"error": "invalid_job_id", "message": str(exc)}
        except FileNotFoundError:
            return {"error": "job_not_found", "message": f"No batch job {job_id!r} in {batch_dir!r}"}
        except TypeError:
            try:
                legacy_job = Job.load(job_id, BatchJob.jobs_dir_for(batch_dir))
            except ValueError as exc:
                return {"error": "invalid_job_id", "message": str(exc)}
            except (FileNotFoundError, json.JSONDecodeError, TypeError) as exc:
                return {"error": "load_failed", "message": str(exc)}
            return _job_result(legacy_job, include_logs=include_logs)
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
                    or "environmentlocationnotfound" in log_lower
                    or "not a conda environment" in log_lower
                    or "condaerror" in log_lower
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
    except ValueError as exc:
        return {"error": "invalid_job_id", "message": str(exc)}
    except FileNotFoundError:
        return _job_error(job_id)

    job = _refresh_workflow_job_status(job, project.jobs_dir())

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
    workspace_root = Path(project.workspace_root)
    candidate_dirs: list[Path] = []
    candidate_files: list[Path] = []

    # Priority 1: paths explicitly stored in job metadata (run-layout aware)
    for p in job.output_paths:
        candidate_files.append(Path(p))

    if job.run_root:
        run_root_path = Path(job.run_root)
        if run_root_path not in candidate_dirs:
            candidate_dirs.append(run_root_path)

    if job.products_dir:
        products_path = Path(job.products_dir)
        if products_path not in candidate_dirs:
            candidate_dirs.append(products_path)

    # Priority 2: runconfig product_path / sas_output_file
    try:
        product_path = get_path(project.runconfig, "runconfig.groups.product_path_group.product_path")
    except KeyError:
        product_path = None
    if isinstance(product_path, str) and product_path:
        product_dir = Path(product_path)
        if product_dir not in candidate_dirs:
            candidate_dirs.append(product_dir)

    try:
        sas_output_file = get_path(project.runconfig, "runconfig.groups.product_path_group.sas_output_file")
    except KeyError:
        sas_output_file = None
    if isinstance(sas_output_file, str) and sas_output_file:
        sas_output_path = Path(sas_output_file)
        if sas_output_path.is_absolute():
            candidate_files.append(sas_output_path)
        else:
            candidate_files.append(workspace_root / sas_output_path)
            if isinstance(product_path, str) and product_path:
                candidate_files.append(Path(product_path) / sas_output_path)

    # Priority 3: legacy fallback directories
    legacy_by_job = project.outputs_dir() / job_id
    if legacy_by_job not in candidate_dirs:
        candidate_dirs.append(legacy_by_job)
    if project.outputs_dir() not in candidate_dirs:
        candidate_dirs.append(project.outputs_dir())

    if project.engine == "isce3":
        candidate_files.extend(sorted(workspace_root.glob("*.h5")))
    if project.engine == "isce2":
        candidate_dirs.extend(
            [
                workspace_root / "merged",
                workspace_root / "reference",
                workspace_root / "secondary",
                workspace_root / "geom_reference",
                workspace_root / "fine_interferogram",
                workspace_root / "fine_coreg",
            ]
        )

    def _make_artifact(f: Path) -> dict:
        ext = f.suffix.lower()
        artifact_type, description, viewer = _TYPE_MAP.get(ext, ("other", "Output file", ""))
        entry: dict = {
            "path": str(f),
            "artifact_type": artifact_type,
            "description": description,
            "recommended_viewer": viewer,
        }
        try:
            entry["relative_path"] = str(f.relative_to(workspace_root))
        except ValueError:
            entry["relative_path"] = str(f)
        if job.task_id:
            entry["task_id"] = job.task_id
        if job.run_id:
            entry["run_id"] = job.run_id
        if job.run_root:
            entry["run_root"] = job.run_root
        return entry

    seen_paths: set[str] = set()
    for f in candidate_files:
        if not f.is_file():
            continue
        path_str = str(f)
        if path_str in seen_paths:
            continue
        seen_paths.add(path_str)
        artifacts.append(_make_artifact(f))

    for outputs_dir in candidate_dirs:
        if not outputs_dir.exists():
            continue
        for f in sorted(outputs_dir.rglob("*")):
            if f.is_file():
                path_str = str(f)
                if path_str in seen_paths:
                    continue
                seen_paths.add(path_str)
                artifacts.append(_make_artifact(f))

    return {
        "job_id": job_id,
        "status": job.status,
        "task_id": job.task_id,
        "run_id": job.run_id,
        "run_root": job.run_root,
        "outputs": artifacts,
    }


def insar_get_mintpy_status(job_id: str, mintpy_work_dir: str) -> dict:
    """Return MintPy job status. Use insar_get_job(job_id, work_dir=...) instead."""
    return insar_get_job(job_id=job_id, work_dir=mintpy_work_dir)
