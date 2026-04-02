"""MintPy time-series processing launcher.

Normalised from docs/archive/knowledge-base/wangshuai/Scripts/run_mintpy_nisar_stack.sh.
Provides importable library functions used by the MCP tool layer.

The shell script is bundled at assets/run_mintpy_nisar_stack.sh.
Helper scripts (prep_nisar_current_gunw.py, apply_common_ifgram_mask.py)
are at scripts/ so that ROOT_DIR/scripts/ resolves correctly at runtime.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, UTC
from pathlib import Path
from uuid import uuid4

_SCRIPT = Path(__file__).parent / "assets" / "run_mintpy_nisar_stack.sh"


def run_mintpy(
    mintpy_work_dir: str | Path,
    gunw_glob: str,
    mintpy_config: str | Path,
    dem_path: str | Path,
    conda_env: str,
    python_bin: str | None = None,
    smallbaseline_bin: str | None = None,
) -> dict[str, object]:
    """Launch MintPy time-series processing asynchronously.

    Runs run_mintpy_nisar_stack.sh inside the given conda environment via
    ``conda run``.  stdout and stderr are redirected to a log file under
    ``<mintpy_work_dir>/logs/<job_id>.log``.  Job metadata is persisted to
    ``<mintpy_work_dir>/.jobs/<job_id>.json`` so status can be polled across
    tool calls.

    Args:
        mintpy_work_dir: Output directory for MintPy results.
        gunw_glob:       Shell glob pattern matching GUNW .h5 files,
                         e.g. ``/path/to/network/runs/*/products/*.h5``.
        mintpy_config:   Path to the MintPy smallbaselineApp config file
                         (.cfg or .txt).
        dem_path:        Path to the DEM GeoTIFF used during GUNW preprocessing.
        conda_env:       Conda environment name that contains MintPy and GDAL.
        python_bin:      Optional override for PYTHON_BIN inside the shell script.
        smallbaseline_bin: Optional override for SMALLBASELINE_BIN inside the shell script.

    Returns:
        dict with keys: job_id, pid, status, log_path, submitted_at
    """
    work_dir = Path(mintpy_work_dir)
    config = Path(mintpy_config)
    dem = Path(dem_path)

    if not _SCRIPT.exists():
        raise FileNotFoundError(f"MintPy script not found: {_SCRIPT}")
    if not config.exists():
        raise FileNotFoundError(str(config))
    if not dem.exists():
        raise FileNotFoundError(str(dem))

    work_dir.mkdir(parents=True, exist_ok=True)
    jobs_dir = work_dir / ".jobs"
    jobs_dir.mkdir(exist_ok=True)
    logs_dir = work_dir / "logs"
    logs_dir.mkdir(exist_ok=True)

    job_id = str(uuid4())
    log_path = str(logs_dir / f"{job_id}.log")

    command = [
        "conda", "run", "--no-capture-output", "-n", conda_env,
        "bash", str(_SCRIPT),
        str(work_dir),
        gunw_glob,
        str(config),
        str(dem),
    ]

    env = os.environ.copy()
    if python_bin:
        env["PYTHON_BIN"] = python_bin
    if smallbaseline_bin:
        env["SMALLBASELINE_BIN"] = smallbaseline_bin

    with open(log_path, "w") as lf:
        proc = subprocess.Popen(command, stdout=lf, stderr=subprocess.STDOUT, env=env)

    job_data: dict[str, object] = {
        "job_id": job_id,
        "pid": proc.pid,
        "status": "running",
        "log_path": log_path,
        "submitted_at": datetime.now(UTC).isoformat(),
        "finished_at": None,
        "command": command,
    }
    (jobs_dir / f"{job_id}.json").write_text(json.dumps(job_data, indent=2))
    return job_data


def get_mintpy_status(job_id: str, mintpy_work_dir: str | Path) -> dict[str, object]:
    """Return the current status of a MintPy job.

    Reads the job JSON from ``<mintpy_work_dir>/.jobs/<job_id>.json``.
    If the job was last seen as ``running``, checks whether the process is
    still alive via ``os.kill(pid, 0)``.  If the process has exited, the
    log tail is inspected to distinguish ``done`` from ``failed``, and the
    JSON is updated accordingly.

    Args:
        job_id:          UUID returned by :func:`run_mintpy`.
        mintpy_work_dir: Same directory passed to :func:`run_mintpy`.

    Returns:
        dict with keys: job_id, pid, status, log_path, submitted_at, finished_at
    """
    jobs_dir = Path(mintpy_work_dir) / ".jobs"
    job_file = jobs_dir / f"{job_id}.json"
    if not job_file.exists():
        raise FileNotFoundError(job_file)

    data: dict[str, object] = json.loads(job_file.read_text())
    pid = data.get("pid")

    if data.get("status") == "running" and pid is not None:
        try:
            os.kill(int(pid), 0)
        except ProcessLookupError:
            log_tail = _read_log_tail(str(data.get("log_path", "")))
            log_lower = log_tail.lower()
            failed = (
                "error:" in log_lower
                or "traceback" in log_lower
                or "exit 1" in log_lower
                or "exception:" in log_lower
            )
            data["status"] = "failed" if failed else "done"
            data["finished_at"] = datetime.now(UTC).isoformat()
            job_file.write_text(json.dumps(data, indent=2))

    return data


def _read_log_tail(log_path: str, n: int = 10) -> str:
    """Return the last *n* lines of a log file, or '' on any error."""
    try:
        lines = Path(log_path).read_text(errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except OSError:
        return ""
