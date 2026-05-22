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
    log_text: str = "",
) -> Job:
    log_path = Path(project.workspace_root) / ".insar_logs" / "existing.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(log_text, encoding="utf-8")
    job = Job(
        project_id=project.project_id,
        engine=project.engine,
        workflow=project.workflow,
        status=status,
        pid=pid,
        log_path=str(log_path),
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
        log_text="[insar-agent] All stack steps completed.\n",
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


def test_run_workflow_isce2_zero_exit_without_stack_success_marker_can_rerun(monkeypatch, tmp_path):
    project = _make_stack_project(tmp_path)
    exit_code_path = tmp_path / "existing.exitcode"
    exit_code_path.write_text("0", encoding="utf-8")
    existing = _save_job(
        project,
        "running",
        pid=999999,
        exit_code_path=str(exit_code_path),
        log_text="[insar-agent] Step: run_files/run_01_unpack_topo_reference\nRunning: topo\n",
    )
    popen_calls = []

    class FakeProcess:
        pid = 12345

    def fake_popen(*args, **kwargs):
        popen_calls.append((args, kwargs))
        return FakeProcess()

    monkeypatch.setattr(server.subprocess, "Popen", fake_popen)

    result = server._run_workflow_isce2(project, dry_run=False)
    refreshed = Job.load(existing.job_id, project.jobs_dir())

    assert result["status"] == "running"
    assert result["job_id"] != existing.job_id
    assert refreshed.status == "failed"
    assert refreshed.exit_code == 1
    assert len(popen_calls) == 1


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


def test_run_workflow_isce2_rejects_stack_dem_without_scene_overlap(monkeypatch, tmp_path):
    project = _make_stack_project(tmp_path)
    (Path(project.runconfig["slc_dir"]) / "scene.SAFE").mkdir()

    monkeypatch.setattr(server, "_read_dem_bbox", lambda _dem_file: [40.45, 13.35, 40.96, 13.82], raising=False)
    monkeypatch.setattr(
        server,
        "_read_safe_metadata",
        lambda safe_path: (Path(safe_path).name, {"bbox": [12.48, 39.70, 14.55, 42.30]}),
    )

    def fail_popen(*args, **kwargs):
        del args, kwargs
        raise AssertionError("workflow should not launch when DEM misses Sentinel-1 coverage")

    monkeypatch.setattr(server.subprocess, "Popen", fail_popen)

    result = server._run_workflow_isce2(project, dry_run=False)

    assert result["error"] == "params_invalid"
    assert any("DEM does not overlap Sentinel-1 scene coverage" in error for error in result["errors"])


def test_run_workflow_isce2_rejects_stack_when_dem_bounds_cannot_be_read(monkeypatch, tmp_path):
    project = _make_stack_project(tmp_path)
    (Path(project.runconfig["slc_dir"]) / "scene.SAFE").mkdir()

    def fail_read_dem_bbox(dem_file: str) -> list[float]:
        raise ValueError(f"Cannot read DEM bounds with gdalinfo for {dem_file!r}: gdalinfo failed")

    monkeypatch.setattr(server, "_read_dem_bbox", fail_read_dem_bbox, raising=False)

    result = server._run_workflow_isce2(project, dry_run=False)

    assert result["error"] == "params_invalid"
    assert any("Cannot read DEM bounds" in error for error in result["errors"])


def test_run_workflow_isce2_validates_dem_overlap_in_dry_run(monkeypatch, tmp_path):
    project = _make_stack_project(tmp_path)
    (Path(project.runconfig["slc_dir"]) / "scene.SAFE").mkdir()

    monkeypatch.setattr(server, "_read_dem_bbox", lambda _dem_file: [40.45, 13.35, 40.96, 13.82], raising=False)
    monkeypatch.setattr(
        server,
        "_read_safe_metadata",
        lambda safe_path: (Path(safe_path).name, {"bbox": [12.48, 39.70, 14.55, 42.30]}),
    )

    result = server._run_workflow_isce2(project, dry_run=True)

    assert result["error"] == "params_invalid"
    assert any("DEM does not overlap Sentinel-1 scene coverage" in error for error in result["errors"])


def test_run_workflow_isce2_validates_stack_zip_scene_dem_overlap(monkeypatch, tmp_path):
    project = _make_stack_project(tmp_path)
    (Path(project.runconfig["slc_dir"]) / "scene.zip").write_bytes(b"zip")

    monkeypatch.setattr(server, "_read_dem_bbox", lambda _dem_file: [40.45, 13.35, 40.96, 13.82], raising=False)
    monkeypatch.setattr(
        server,
        "_read_safe_metadata",
        lambda safe_path: (Path(safe_path).name, {"bbox": [12.48, 39.70, 14.55, 42.30]}),
    )

    result = server._run_workflow_isce2(project, dry_run=False)

    assert result["error"] == "params_invalid"
    assert any("DEM does not overlap Sentinel-1 scene coverage" in error for error in result["errors"])
    assert any("scene.zip" in error for error in result["errors"])
