from __future__ import annotations

from pathlib import Path

from insar_agent.core.jobs import Job
from insar_agent.core.project import Project
from insar_agent.mcp import server


def _make_stack_project(tmp_path: Path) -> Project:
    slc_dir = tmp_path / "slc"
    orbit_dir = tmp_path / "orbits"
    dem_file = tmp_path / "dem.tif"
    slc_dir.mkdir()
    orbit_dir.mkdir()
    dem_file.write_bytes(b"")
    return Project(
        name="sentinel-stack",
        engine="isce2",
        workflow="stack",
        workspace_root=str(tmp_path / "workspace"),
        project_id="project-1",
        runconfig={
            "slc_dir": str(slc_dir),
            "orbit_dir": str(orbit_dir),
            "dem_file": str(dem_file),
        },
        conda_env="isce2",
    )


def _save_job(
    project: Project,
    status: str,
    *,
    pid: int | None = None,
    exit_code_path: str | None = None,
) -> Job:
    job = Job(
        project_id=project.project_id,
        engine=project.engine,
        workflow=project.workflow,
        status=status,
        pid=pid,
        log_path=str(Path(project.workspace_root) / ".insar_logs" / "existing.log"),
        exit_code_path=exit_code_path,
    )
    job.save(project.jobs_dir())
    return job


def test_run_workflow_isce2_returns_existing_done_job(monkeypatch, tmp_path):
    project = _make_stack_project(tmp_path)
    existing = _save_job(project, "done")

    def fail_popen(*args, **kwargs):
        del args, kwargs
        raise AssertionError("duplicate process launch")

    monkeypatch.setattr(server.subprocess, "Popen", fail_popen)

    result = server._run_workflow_isce2(project, dry_run=False)

    assert result["job_id"] == existing.job_id
    assert result["status"] == "done"
    assert result["deduplicated"] is True


def test_run_workflow_isce2_returns_existing_running_job(monkeypatch, tmp_path):
    project = _make_stack_project(tmp_path)
    existing = _save_job(project, "running")

    def fail_popen(*args, **kwargs):
        del args, kwargs
        raise AssertionError("duplicate process launch")

    monkeypatch.setattr(server.subprocess, "Popen", fail_popen)

    result = server._run_workflow_isce2(project, dry_run=False)

    assert result["job_id"] == existing.job_id
    assert result["status"] == "running"
    assert result["deduplicated"] is True


def test_run_workflow_isce2_finalizes_running_job_with_exit_code(monkeypatch, tmp_path):
    project = _make_stack_project(tmp_path)
    exit_code_path = tmp_path / "existing.exitcode"
    exit_code_path.write_text("0", encoding="utf-8")
    existing = _save_job(
        project,
        "running",
        pid=999999,
        exit_code_path=str(exit_code_path),
    )

    def fail_popen(*args, **kwargs):
        del args, kwargs
        raise AssertionError("duplicate process launch")

    monkeypatch.setattr(server.subprocess, "Popen", fail_popen)

    result = server._run_workflow_isce2(project, dry_run=False)
    refreshed = Job.load(existing.job_id, project.jobs_dir())

    assert result["job_id"] == existing.job_id
    assert result["status"] == "done"
    assert result["exit_code"] == 0
    assert result["deduplicated"] is True
    assert refreshed.status == "done"


def test_run_workflow_isce2_failed_job_can_rerun(monkeypatch, tmp_path):
    project = _make_stack_project(tmp_path)
    failed = _save_job(project, "failed")
    popen_calls = []

    class FakeProcess:
        pid = 12345

    def fake_popen(*args, **kwargs):
        popen_calls.append((args, kwargs))
        return FakeProcess()

    monkeypatch.setattr(server.subprocess, "Popen", fake_popen)

    result = server._run_workflow_isce2(project, dry_run=False)

    assert result["status"] == "running"
    assert result["job_id"] != failed.job_id
    assert len(popen_calls) == 1
