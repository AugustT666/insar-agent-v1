"""
TDD tests for F1 + F2 robustness fixes.

F2 — pid-liveness crash detection in insar_get_job:
    When a Job has status="running" with a dead pid and no exit_code/finished_at,
    insar_get_job must report "failed" with failure_reason and persist the update.

F1 — run_workflow same-run concurrency guard:
    insar_run_workflow must refuse to launch a second workflow when a live running
    workflow job exists for the same project, but must allow launch when the only
    "running" job has a dead pid.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from insar_agent.core.jobs import Job
from insar_agent.core.project import Project
from insar_agent.mcp.server import (
    insar_create_project,
    insar_export_runconfig,
    insar_get_job,
    insar_run_workflow,
)
from insar_agent.mcp.tools.job_tools import insar_get_job as insar_get_job_tool


# ── helpers ───────────────────────────────────────────────────────────────────

def _dead_pid() -> int:
    """Return a pid that is guaranteed to be dead (spawn + reap a trivial process)."""
    proc = subprocess.Popen(["true"])
    proc.wait()
    return proc.pid


def _live_pid() -> int:
    """Return a pid that is guaranteed to be alive (the current process)."""
    return os.getpid()


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "registry"))


@pytest.fixture()
def ready_project(tmp_path):
    """ISCE3 insar project with valid runconfig, ready to launch."""
    ws = str(tmp_path / "ws")
    result = insar_create_project(
        engine="isce3",
        workflow="insar",
        workspace_root=ws,
        name="f1f2-test",
        conda_env="isce3gpu",
    )
    pid = result["project_id"]

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


def _inject_running_workflow_job(project_id: str, pid: int) -> str:
    """Write a workflow Job JSON with status=running and the given pid, return job_id."""
    project = Project.load(project_id)
    jobs_dir = project.jobs_dir()
    job = Job(
        project_id=project_id,
        engine=project.engine,
        workflow=project.workflow,
        status="running",
        pid=pid,
        tool_name="insar_run_workflow",
        job_type=f"{project.engine}_{project.workflow}_workflow",
    )
    job.log_path = str(jobs_dir / f"{job.job_id}.log")
    job.exit_code_path = str(jobs_dir / f"{job.job_id}.exitcode")
    job.started_at = "2026-01-01T00:00:00+00:00"
    job.save(jobs_dir)
    return job.job_id


# ══════════════════════════════════════════════════════════════════════════════
# F2 TESTS — pid-liveness crash detection in insar_get_job
# ══════════════════════════════════════════════════════════════════════════════

class TestF2PidLivenessCrashDetection:
    """
    When status="running", pid is set, exit_code is null, finished_at is null,
    and the pid process is NOT alive — insar_get_job must classify the job as
    crashed/failed, set failure_reason, and persist the change.
    """

    def test_dead_pid_no_exitcode_no_finished_at_returns_failed(self, ready_project):
        """Core F2 scenario: dead pid, no exit_code, no finished_at → status=failed."""
        dead = _dead_pid()
        job_id = _inject_running_workflow_job(ready_project, pid=dead)

        result = insar_get_job(job_id=job_id, project_id=ready_project)

        assert result["status"] == "failed", (
            f"Expected 'failed' for dead-pid job with no exitcode, got {result['status']!r}"
        )
        assert "failure_reason" in result, "failure_reason must be present in response"
        assert str(dead) in result["failure_reason"], (
            f"failure_reason should mention the dead pid {dead}, got: {result['failure_reason']!r}"
        )

    def test_dead_pid_crash_persisted_to_disk(self, ready_project):
        """After crash detection the job JSON on disk must reflect failed status."""
        dead = _dead_pid()
        job_id = _inject_running_workflow_job(ready_project, pid=dead)

        insar_get_job(job_id=job_id, project_id=ready_project)

        project = Project.load(ready_project)
        job_on_disk = Job.load(job_id, project.jobs_dir())
        assert job_on_disk.status == "failed", (
            f"Job on disk must be 'failed' after crash detection, got {job_on_disk.status!r}"
        )

    def test_dead_pid_crash_idempotent(self, ready_project):
        """Calling insar_get_job twice on a crashed job is idempotent (still failed)."""
        dead = _dead_pid()
        job_id = _inject_running_workflow_job(ready_project, pid=dead)

        result1 = insar_get_job(job_id=job_id, project_id=ready_project)
        result2 = insar_get_job(job_id=job_id, project_id=ready_project)

        assert result1["status"] == "failed"
        assert result2["status"] == "failed"
        # failure_reason should be consistent
        assert result1.get("failure_reason") == result2.get("failure_reason")

    def test_live_pid_stays_running(self, ready_project):
        """A job with a live pid (current process) must NOT be reclassified."""
        live = _live_pid()
        job_id = _inject_running_workflow_job(ready_project, pid=live)

        result = insar_get_job(job_id=job_id, project_id=ready_project)

        assert result["status"] == "running", (
            f"Job with live pid {live} must stay 'running', got {result['status']!r}"
        )

    def test_done_job_is_not_reclassified(self, ready_project):
        """A job that already reached status='done' must stay 'done' regardless of pid."""
        dead = _dead_pid()
        job_id = _inject_running_workflow_job(ready_project, pid=dead)

        # Manually finalize to 'done'
        project = Project.load(ready_project)
        jobs_dir = project.jobs_dir()
        job = Job.load(job_id, jobs_dir)
        job.status = "done"
        job.exit_code = 0
        job.finished_at = "2026-01-01T12:00:00+00:00"
        job.save(jobs_dir)

        result = insar_get_job(job_id=job_id, project_id=ready_project)

        assert result["status"] == "done", (
            f"A 'done' job must stay 'done', got {result['status']!r}"
        )

    def test_failed_job_is_not_reclassified(self, ready_project):
        """A job that already reached status='failed' must stay 'failed'."""
        dead = _dead_pid()
        job_id = _inject_running_workflow_job(ready_project, pid=dead)

        project = Project.load(ready_project)
        jobs_dir = project.jobs_dir()
        job = Job.load(job_id, jobs_dir)
        job.status = "failed"
        job.exit_code = 1
        job.finished_at = "2026-01-01T12:00:00+00:00"
        job.save(jobs_dir)

        result = insar_get_job(job_id=job_id, project_id=ready_project)

        assert result["status"] == "failed"


# ══════════════════════════════════════════════════════════════════════════════
# F1 TESTS — run_workflow same-run concurrency guard
# ══════════════════════════════════════════════════════════════════════════════

class TestF1ConcurrencyGuard:
    """
    insar_run_workflow must refuse a second launch when a live workflow job exists.
    A dead "running" job must NOT block a fresh launch (uses F2 liveness check).
    """

    def test_live_running_job_blocks_second_launch(self, ready_project):
        """With a live running workflow job, a second launch returns a concurrency error."""
        live = _live_pid()
        existing_job_id = _inject_running_workflow_job(ready_project, pid=live)

        mock_proc = MagicMock()
        mock_proc.pid = 99999
        with patch("insar_agent.mcp.server.subprocess.Popen", return_value=mock_proc):
            result = insar_run_workflow(ready_project, dry_run=False)

        assert result.get("status") == "error", (
            f"Expected concurrency error, got: {result}"
        )
        assert "running_job_id" in result, "Response must include running_job_id"
        assert result["running_job_id"] == existing_job_id

    def test_live_running_job_prevents_launch_process(self, ready_project):
        """When blocked, no new subprocess must be started."""
        live = _live_pid()
        _inject_running_workflow_job(ready_project, pid=live)

        with patch("insar_agent.mcp.server.subprocess.Popen") as mock_popen:
            insar_run_workflow(ready_project, dry_run=False)

        mock_popen.assert_not_called()

    def test_dead_running_job_does_not_block_launch(self, ready_project):
        """A running job with a dead pid must NOT block a fresh launch."""
        dead = _dead_pid()
        _inject_running_workflow_job(ready_project, pid=dead)

        mock_proc = MagicMock()
        mock_proc.pid = 11111
        with patch("insar_agent.mcp.server.subprocess.Popen", return_value=mock_proc):
            result = insar_run_workflow(ready_project, dry_run=False)

        # Must succeed (not a concurrency error)
        assert result.get("status") != "error", (
            f"Dead-pid running job must not block launch, got: {result}"
        )
        assert "job_id" in result, f"Expected successful launch, got: {result}"

    def test_done_job_does_not_block_launch(self, ready_project):
        """A completed (done) job must not block a fresh launch."""
        dead = _dead_pid()
        job_id = _inject_running_workflow_job(ready_project, pid=dead)

        # Manually finalize to done
        project = Project.load(ready_project)
        jobs_dir = project.jobs_dir()
        job = Job.load(job_id, jobs_dir)
        job.status = "done"
        job.exit_code = 0
        job.finished_at = "2026-01-01T12:00:00+00:00"
        job.save(jobs_dir)

        mock_proc = MagicMock()
        mock_proc.pid = 22222
        with patch("insar_agent.mcp.server.subprocess.Popen", return_value=mock_proc):
            result = insar_run_workflow(ready_project, dry_run=False)

        assert result.get("status") != "error", (
            f"Done job must not block launch, got: {result}"
        )
        assert "job_id" in result

    def test_concurrency_error_includes_helpful_message(self, ready_project):
        """The error message must tell the user to wait or cancel."""
        live = _live_pid()
        _inject_running_workflow_job(ready_project, pid=live)

        result = insar_run_workflow(ready_project, dry_run=False)

        assert "error" in result
        error_text = result.get("error", "")
        # Should mention polling or cancelling
        assert "insar_get_job" in error_text or "poll" in error_text or "cancel" in error_text, (
            f"Error message should guide user to poll/cancel, got: {error_text!r}"
        )

    def test_dry_run_not_blocked_by_live_job(self, ready_project):
        """dry_run=True is a read-only preflight — it must not be blocked."""
        live = _live_pid()
        _inject_running_workflow_job(ready_project, pid=live)

        result = insar_run_workflow(ready_project, dry_run=True)

        assert result.get("dry_run") is True, (
            f"dry_run must proceed even with live running job, got: {result}"
        )
