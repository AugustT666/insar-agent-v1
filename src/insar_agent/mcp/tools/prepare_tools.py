"""MCP tools: prepare_tools (registered on the shared FastMCP)."""

from __future__ import annotations

from insar_agent.mcp._app import *  # noqa: F403  (foundation: imports + constants + mcp)
from insar_agent.mcp._helpers import *  # noqa: F403  (shared helpers)
from insar_agent.core.output_resolver import OutputEscapeError, resolve_output


@mcp.tool()
def insar_prepare_stack(
    data_dir: str,
    base_runconfig: str = "",
    *,
    dem: str,
    output_dir: str = "",
    workspace_root: str = "",
    task_id: str = "stack-insar-isce3",
    run_id: str = "",
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
            If omitted, workspace_root is required and the output directory is derived
            under workspace_root/task_id/outputs/run_id.
        workspace_root: Top-level workspace used to derive output_dir when output_dir is empty.
        task_id: Task directory name for derived output_dir; defaults to stack-insar-isce3.
        run_id: Optional run id. Pass the same value to stack and network prepare to share a run root.
        reference: Reference scene selector — 'auto' (earliest date), a YYYYMMDD
                   string, or an absolute RSLC file path.
    """
    try:
        interaction_mode = _normalize_interaction_mode(interaction_mode)
        _res = resolve_output(
            output_dir=output_dir or None,
            workspace_root=workspace_root or None,
            task_id=task_id or "stack-insar-isce3",
            run_id=run_id or None,
            subdir="stack",
        )
        resolved_output_dir, run_layout = str(_res.target), _res.layout
        result = prepare_stack(
            data_dir=data_dir,
            base_runconfig=base_runconfig or None,
            dem=dem,
            output_dir=resolved_output_dir,
            reference=reference,
        )
        result.update({
            "task_id": run_layout.task_id,
            "run_id": run_layout.run_id,
            "run_root": str(run_layout.run_root),
            "stack_dir": str(run_layout.stack_dir),
        })
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
    except OutputEscapeError as exc:
        return {"error": "output_escape", "message": str(exc)}
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
    output_dir: str = "",
    workspace_root: str = "",
    task_id: str = "stack-insar-isce3",
    run_id: str = "",
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
            If omitted, workspace_root is required and the output directory is derived
            under workspace_root/task_id/outputs/run_id.
        workspace_root: Top-level workspace used to derive output_dir when output_dir is empty.
        task_id: Task directory name for derived output_dir; defaults to stack-insar-isce3.
        run_id: Optional run id. Pass the same value to stack and network prepare to share a run root.
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
        _res = resolve_output(
            output_dir=output_dir or None,
            workspace_root=workspace_root or None,
            task_id=task_id or "stack-insar-isce3",
            run_id=run_id or None,
            subdir="network",
        )
        resolved_output_dir, run_layout = str(_res.target), _res.layout
        result = prepare_network(
            data_dir=data_dir,
            base_runconfig=base_runconfig or None,
            dem=dem,
            output_dir=resolved_output_dir,
            network_mode=network_mode,
            max_temporal_baseline_days=max_temporal_baseline_days,
            connection_span=connection_span,
            pair_list=pair_list or None,
        )
        result.update({
            "task_id": run_layout.task_id,
            "run_id": run_layout.run_id,
            "run_root": str(run_layout.run_root),
            "network_dir": str(run_layout.network_dir),
        })
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
    except OutputEscapeError as exc:
        return {"error": "output_escape", "message": str(exc)}
    except FileNotFoundError as exc:
        return {"error": "path_not_found", "message": str(exc)}
    except ValueError as exc:
        return {"error": "invalid_input", "message": str(exc)}


@mcp.tool()
def insar_run_batch(
    batch_dir: str,
    max_jobs: int = 4,
    execution_mode: str = "parallel",
    conda_env: str = "",
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
        batch_dir:  Output directory used in insar_prepare_stack or insar_prepare_network
        max_jobs:   Maximum number of ISCE3 pairs to run in parallel (default: 4)
        conda_env:  Conda environment name to activate for ISCE3 (e.g. 'isce3', 'isce3gpu')

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

    env_name = (conda_env or "").strip()
    if execution_mode == "parallel":
        inner = ["bash", str(runner_path), batch_dir, str(max_jobs)]
    else:
        inner = ["bash", str(runner_path)]
    if env_name:
        command = ["conda", "run", "-n", env_name, "--no-capture-output"] + inner
    else:
        command = inner

    logs_dir = Path(batch_dir) / "logs"
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
                start_new_session=True,
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


@mcp.tool()
def insar_download_scene(
    urls: list[str],
    output_dir: str,
    n_workers: int = 4,
    proxy: str | None = None,
    overwrite: bool = False,
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
                    Use "direct" or "none" to bypass environment proxies.
        overwrite:  If true, re-download even when the destination file exists.
                    Existing partial ``.part`` files are discarded first.

    Returns:
        {ok: [{url, path, size_mb}], failed: [{url, error}], output_dir}
    """
    import concurrent.futures
    from urllib.parse import urlparse

    out_dir = Path(output_dir)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return {"error": "output_dir_not_writable", "message": str(exc)}

    direct_proxy_values = {"direct", "none", "off", "false", "no_proxy", "no-proxy"}
    proxy_mode = proxy.strip().lower() if proxy else None
    def _downloaded_file_error(path: Path) -> str | None:
        data = path.read_bytes()[:512]
        stripped = data.lstrip().lower()
        if stripped.startswith((b"<html", b"<!doctype html")) or b"asf-urs" in stripped:
            return "download returned an HTML login page instead of data"
        suffix = path.suffix.lower()
        if suffix in {".tif", ".tiff"} and not (data.startswith(b"II*\x00") or data.startswith(b"MM\x00*")):
            return "downloaded TIFF does not have a TIFF header"
        if suffix == ".xml" and not (stripped.startswith(b"<burst") or stripped.startswith(b"<?xml")):
            return "downloaded XML does not have an XML/burst header"
        if suffix == ".xml":
            from xml.etree import ElementTree as ET

            try:
                ET.parse(path)
            except ET.ParseError as exc:
                return f"downloaded XML is not well-formed: {exc}"
        return None

    def _download_with_curl(url: str, dest: Path) -> dict:
        if shutil.which("curl") is None:
            return {"url": url, "error": "curl executable not found"}
        tmp_path = dest.with_suffix(dest.suffix + ".part")

        def _last_http_status(header_path: Path) -> int | None:
            if not header_path.exists():
                return None
            statuses = []
            for line in header_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("HTTP/"):
                    parts = line.split()
                    if len(parts) >= 2 and parts[1].isdigit():
                        statuses.append(int(parts[1]))
            return statuses[-1] if statuses else None

        def _keep_chunk_progress(chunk_path: Path, existing_size: int, status: int | None) -> None:
            if not chunk_path.exists() or chunk_path.stat().st_size == 0:
                return
            if existing_size and status == 206:
                with tmp_path.open("ab") as target, chunk_path.open("rb") as chunk:
                    shutil.copyfileobj(chunk, target)
            elif status == 200:
                chunk_path.replace(tmp_path)

        last_error = "curl download failed"
        for attempt in range(1, 6):
            cookie_path = Path(tempfile.gettempdir()) / f"insar_asf_cookies_{uuid.uuid4().hex}.txt"
            header_path = Path(tempfile.gettempdir()) / f"insar_asf_headers_{uuid.uuid4().hex}.txt"
            chunk_path = tmp_path.with_name(f"{tmp_path.name}.{uuid.uuid4().hex}.chunk")
            existing_size = tmp_path.stat().st_size if tmp_path.exists() else 0
            command = [
                "curl",
                "--fail",
                "--location",
                "--netrc",
                "--cookie-jar",
                str(cookie_path),
                "--cookie",
                str(cookie_path),
                "--connect-timeout",
                "30",
                "--speed-time",
                "120",
                "--speed-limit",
                "1024",
                "--dump-header",
                str(header_path),
                "--output",
                str(chunk_path),
            ]
            if existing_size:
                command.extend(["--range", f"{existing_size}-"])
            if proxy_mode in direct_proxy_values:
                command.extend(["--noproxy", "*"])
            elif proxy:
                command.extend(["--proxy", proxy])
            command.append(url)
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=None)
                status = _last_http_status(header_path)
                if result.returncode != 0:
                    last_error = result.stderr.strip() or result.stdout.strip() or "curl download failed"
                    _keep_chunk_progress(chunk_path, existing_size, status)
                    continue
                if existing_size and status == 206:
                    _keep_chunk_progress(chunk_path, existing_size, status)
                elif existing_size and status == 200:
                    _keep_chunk_progress(chunk_path, existing_size, status)
                elif existing_size:
                    last_error = f"curl resume returned HTTP status {status or 'unknown'}"
                    continue
                else:
                    chunk_path.replace(tmp_path)
                break
            except Exception as exc:
                last_error = str(exc)
                continue
            finally:
                cookie_path.unlink(missing_ok=True)
                header_path.unlink(missing_ok=True)
                chunk_path.unlink(missing_ok=True)
            if attempt < 5:
                time.sleep(2)
        else:
            return {"url": url, "error": last_error}

        try:
            tmp_path.replace(dest)
            file_error = _downloaded_file_error(dest)
            if file_error:
                dest.unlink(missing_ok=True)
                return {"url": url, "error": file_error}
            return {"url": url, "path": str(dest), "size_mb": round(dest.stat().st_size / 1024 / 1024, 2)}
        except Exception as exc:
            return {"url": url, "error": str(exc)}

    def _download_one(url: str) -> dict:
        rel_path = urlparse(url).path.lstrip("/").split("?")[0] or f"scene_{uuid.uuid4().hex[:8]}"
        dest = out_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            existing_error = None if overwrite else _downloaded_file_error(dest)
            if not overwrite and existing_error is None:
                size_mb = round(dest.stat().st_size / 1024 / 1024, 2)
                return {"url": url, "path": str(dest), "size_mb": size_mb, "skipped": True}
            dest.unlink()
            if overwrite:
                dest.with_suffix(dest.suffix + ".part").unlink(missing_ok=True)
        return _download_with_curl(url, dest)

    _, log_path, params_path = _prepare_tool_log(
        [output_dir],
        "sentinel_scene",
        {"urls": urls, "output_dir": output_dir, "n_workers": n_workers, "proxy": proxy, "overwrite": overwrite},
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
