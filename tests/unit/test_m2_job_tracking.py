"""
Unit tests for M2 job tracking: PID capture in insar_run_workflow and
PID-based liveness check in insar_get_job_status.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from insar_agent.mcp.server import (
    insar_create_project,
    insar_export_runconfig,
    insar_get_job,
    insar_get_job_status,
    insar_run_workflow,
)
from insar_agent.core.project import Project


# ── fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "registry"))


@pytest.fixture()
def ready_project(tmp_path):
    """Project with a valid exported runconfig, ready to launch."""
    ws = str(tmp_path / "ws")
    result = insar_create_project(
        engine="isce3",
        workflow="insar",
        workspace_root=ws,
        name="test-job-tracking",
        conda_env="isce3gpu",
    )
    pid = result["project_id"]

    # Populate required paths with placeholder files that exist
    ref = tmp_path / "ref.h5"
    sec = tmp_path / "sec.h5"
    dem = tmp_path / "dem.wgs84"
    for f in (ref, sec, dem):
        f.write_bytes(b"")

    from insar_agent.mcp.server import insar_set_runconfig_value
    for key, val in {
        "runconfig.groups.input_file_group.reference_rslc_file": str(ref),
        "runconfig.groups.input_file_group.secondary_rslc_file": str(sec),
        "runconfig.groups.dynamic_ancillary_file_group.dem_file": str(dem),
        "runconfig.groups.product_path_group.product_path": str(tmp_path / "out"),
        "runconfig.groups.product_path_group.scratch_path": str(tmp_path / "scratch"),
        "runconfig.groups.product_path_group.sas_output_file": "GUNW_product.h5",
        "runconfig.groups.logging.path": str(tmp_path / "run.log"),
    }.items():
        insar_set_runconfig_value(pid, key, val)

    insar_export_runconfig(pid)
    return pid


# ── insar_run_workflow: PID capture ────────────────────────────────────────────

class TestRunWorkflowPidCapture:
    def test_pid_stored_in_job_json(self, ready_project, tmp_path):
        """After a successful launch, job JSON must contain the process PID."""
        mock_proc = MagicMock()
        mock_proc.pid = 42000

        with patch("insar_agent.mcp.server.subprocess.Popen", return_value=mock_proc):
            result = insar_run_workflow(ready_project, dry_run=False)

        assert "job_id" in result
        assert result["pid"] == 42000

        # Verify job JSON on disk
        project = Project.load(ready_project)
        job_files = list(project.jobs_dir().glob("*.json"))
        assert len(job_files) == 1
        data = json.loads(job_files[0].read_text())
        assert data["pid"] == 42000

    def test_dry_run_has_no_pid(self, ready_project):
        """dry_run=True must not launch a process or write a pid."""
        result = insar_run_workflow(ready_project, dry_run=True)
        assert result["dry_run"] is True
        assert "pid" not in result

    def test_launch_failure_marks_job_failed(self, ready_project):
        """If Popen raises, job is saved as failed."""
        with patch("insar_agent.mcp.server.subprocess.Popen", side_effect=OSError("no such file")):
            result = insar_run_workflow(ready_project, dry_run=False)

        assert result["error"] == "launch_failed"

        project = Project.load(ready_project)
        job_files = list(project.jobs_dir().glob("*.json"))
        assert len(job_files) == 1
        data = json.loads(job_files[0].read_text())
        assert data["status"] == "failed"
        assert data["exit_code"] == -1


# ── insar_get_job_status: PID liveness ─────────────────────────────────────────

class TestGetJobStatusLiveness:

    def _launch_job(self, project_id: str, pid: int) -> str:
        """Helper: record a running job with a given PID in the job registry."""
        mock_proc = MagicMock()
        mock_proc.pid = pid
        with patch("insar_agent.mcp.server.subprocess.Popen", return_value=mock_proc):
            result = insar_run_workflow(project_id, dry_run=False)
        return result["job_id"]

    def test_alive_pid_returns_running(self, ready_project):
        """Live, non-zombie PID → status stays 'running'."""
        import os as _os
        live_pid = _os.getpid()  # current process is guaranteed alive + not zombie
        job_id = self._launch_job(ready_project, pid=live_pid)
        result = insar_get_job_status(job_id, ready_project)
        assert result["status"] == "running"
        assert result["pid"] == live_pid

    def test_dead_pid_no_error_in_log_returns_done(self, ready_project, tmp_path):
        """Process exited, log shows success → status becomes 'done'."""
        job_id = self._launch_job(ready_project, pid=88888)

        # Write a success log
        project = Project.load(ready_project)
        job_files = list(project.jobs_dir().glob("*.json"))
        data = json.loads(job_files[0].read_text())
        log_path = Path(data["log_path"])
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("Processing complete.\nWorkflow finished successfully.\n")

        with patch("insar_agent.mcp.server.os.kill", side_effect=ProcessLookupError):
            result = insar_get_job_status(job_id, ready_project)

        assert result["status"] == "done"
        assert result["exit_code"] == 0
        assert result["finished_at"] is not None

    def test_dead_pid_error_in_log_returns_failed(self, ready_project, tmp_path):
        """Process exited, log shows error: → status becomes 'failed'."""
        job_id = self._launch_job(ready_project, pid=77777)

        project = Project.load(ready_project)
        job_files = list(project.jobs_dir().glob("*.json"))
        data = json.loads(job_files[0].read_text())
        log_path = Path(data["log_path"])
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("Running...\nError: DEM file not found\nTraceback...\n")

        with patch("insar_agent.mcp.server.os.kill", side_effect=ProcessLookupError):
            result = insar_get_job_status(job_id, ready_project)

        assert result["status"] == "failed"
        assert result["exit_code"] == 1

    def test_dead_pid_nonzero_exit_code_file_returns_failed(self, ready_project):
        """A recorded non-zero exit code must override an empty log."""
        job_id = self._launch_job(ready_project, pid=77666)

        project = Project.load(ready_project)
        job_files = list(project.jobs_dir().glob("*.json"))
        data = json.loads(job_files[0].read_text())
        exit_code_path = Path(data["log_path"]).with_suffix(".exitcode")
        exit_code_path.write_text("1")
        data["exit_code_path"] = str(exit_code_path)
        job_files[0].write_text(json.dumps(data))

        with patch("insar_agent.mcp.server.os.kill", side_effect=ProcessLookupError):
            result = insar_get_job(job_id=job_id, project_id=ready_project)

        assert result["status"] == "failed"
        assert result["exit_code"] == 1

    def test_dead_pid_zero_exit_code_file_returns_done(self, ready_project):
        """A recorded zero exit code should mark completion even with an empty log."""
        job_id = self._launch_job(ready_project, pid=77665)

        project = Project.load(ready_project)
        job_files = list(project.jobs_dir().glob("*.json"))
        data = json.loads(job_files[0].read_text())
        exit_code_path = Path(data["log_path"]).with_suffix(".exitcode")
        exit_code_path.write_text("0")
        data["exit_code_path"] = str(exit_code_path)
        job_files[0].write_text(json.dumps(data))

        with patch("insar_agent.mcp.server.os.kill", side_effect=ProcessLookupError):
            result = insar_get_job_status(job_id, ready_project)

        assert result["status"] == "done"
        assert result["exit_code"] == 0

    def test_dead_pid_critical_in_log_returns_failed(self, ready_project, tmp_path):
        """ISCE3 CRITICAL log level triggers failed status."""
        job_id = self._launch_job(ready_project, pid=66666)

        project = Project.load(ready_project)
        job_files = list(project.jobs_dir().glob("*.json"))
        data = json.loads(job_files[0].read_text())
        log_path = Path(data["log_path"])
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("Starting...\nCritical: unhandled exception in worker\n")

        with patch("insar_agent.mcp.server.os.kill", side_effect=ProcessLookupError):
            result = insar_get_job_status(job_id, ready_project)

        assert result["status"] == "failed"

    def test_already_done_job_not_reprocessed(self, ready_project):
        """If job.status is already 'done', os.kill is never called."""
        job_id = self._launch_job(ready_project, pid=55555)

        # Manually set job to done
        project = Project.load(ready_project)
        job_files = list(project.jobs_dir().glob("*.json"))
        data = json.loads(job_files[0].read_text())
        data["status"] = "done"
        data["finished_at"] = "2026-01-01T00:00:00+00:00"
        data["exit_code"] = 0
        job_files[0].write_text(json.dumps(data))

        with patch("insar_agent.mcp.server.os.kill") as mock_kill:
            result = insar_get_job_status(job_id, ready_project)

        mock_kill.assert_not_called()
        assert result["status"] == "done"
