from __future__ import annotations

from pathlib import Path

from insar_agent.core.jobs import Job
from insar_agent.core.project import Project
from insar_agent.mcp import server
from insar_agent.engines.isce2.stack import write_stack_topology


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
        output_root=str(tmp_path / "workspace"),
        project_id="project-1",
        runconfig={
            "slc_dir": str(slc_dir),
            "orbit_dir": str(orbit_dir),
            "dem_file": str(dem_file),
        },
        conda_env="isce2",
        task="stack-insar-isce2",
    )


def _make_tops_project(tmp_path: Path) -> Project:
    reference_safe = tmp_path / "ref.SAFE"
    secondary_safe = tmp_path / "sec.SAFE"
    orbit_dir = tmp_path / "orbits"
    dem_file = tmp_path / "dem.tif"
    reference_safe.mkdir()
    secondary_safe.mkdir()
    orbit_dir.mkdir()
    dem_file.write_bytes(b"dem")
    (dem_file.with_suffix(dem_file.suffix + ".xml")).write_text(
        """<image_name>
    <property name="file_name">
        <value>/stale/dem.tif</value>
    </property>
</image_name>
""",
        encoding="utf-8",
    )
    (dem_file.with_suffix(dem_file.suffix + ".vrt")).write_text(
        """<VRTDataset rasterXSize="1" rasterYSize="1">
    <VRTRasterBand dataType="Float32" band="1" subClass="VRTRawRasterBand">
        <SourceFilename relativeToVRT="1">dem.tif</SourceFilename>
    </VRTRasterBand>
</VRTDataset>
""",
        encoding="utf-8",
    )
    return Project(
        name="sentinel-tops",
        engine="isce2",
        workflow="tops",
        output_root=str(tmp_path / "workspace"),
        project_id="project-tops",
        runconfig={
            "reference_safe": str(reference_safe),
            "secondary_safe": str(secondary_safe),
            "orbit_dir": str(orbit_dir),
            "dem_file": str(dem_file),
        },
        conda_env="isce2",
        task="d-insar-isce2",
    )



def _save_job(
    project: Project,
    status: str,
    *,
    pid: int | None = None,
    exit_code_path: str | None = None,
    log_text: str = "",
) -> Job:
    log_path = project.logs_dir() / "existing.log"
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


def test_run_workflow_isce2_materializes_tops_dem_under_prepare_dem(monkeypatch, tmp_path):
    """C3 fix: DEM must land at output_root/prepare/dem/ (not run_root/isce2_dem/)."""
    project = _make_tops_project(tmp_path)

    monkeypatch.setattr(server, "_validate_isce2_safe_annotation_geolocation", lambda _params, _workflow: [], raising=False)
    monkeypatch.setattr(server, "_validate_isce2_dem_scene_overlap", lambda _params, _workflow: [], raising=False)

    result = server._run_workflow_isce2(project, dry_run=True)

    run_root = Path(result["run_root"])
    # C3 fix: DEM lands at output_root/prepare/dem/ using output_root= kwarg
    expected_dem = Path(project.output_root) / "prepare" / "dem" / "dem.tif"
    # New layout: configs live under run_root/insar_product/configs/
    rendered = (run_root / "insar_product" / "configs" / "topsApp.xml").read_text(encoding="utf-8")
    assert f"<property name=\"demfilename\">{expected_dem}</property>" in rendered
    assert (expected_dem.with_suffix(expected_dem.suffix + ".xml")).exists()
    assert (expected_dem.with_suffix(expected_dem.suffix + ".vrt")).exists()
    # Legacy isce2_dem path must NOT be created
    assert not (Path(project.output_root) / "isce2_dem").exists()
    assert not (run_root / "isce2_dem").exists()
    assert not (Path(project.output_root) / "d-insar-isce2" / "configs").exists()


def test_run_workflow_isce2_stack_uses_run_root_stack_dir(monkeypatch, tmp_path):
    project = _make_stack_project(tmp_path)
    popen_calls = []

    class FakeProcess:
        pid = 12345

    def fake_popen(*args, **kwargs):
        popen_calls.append((args, kwargs))
        return FakeProcess()

    monkeypatch.setattr(server.subprocess, "Popen", fake_popen)

    result = server._run_workflow_isce2(project, dry_run=False)

    run_root = Path(result["run_root"])
    stack_dir = run_root / "insar_product" / "stack"
    assert result["status"] == "running"
    assert result["job_id"]
    assert str(stack_dir) in str(result["command"])
    assert (run_root / ".insar_agent" / "jobs" / f"{result['job_id']}.json").exists()
    assert len(popen_calls) == 1
    assert not (Path(project.output_root) / "stack").exists()
    assert not (run_root / "stack").exists()


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


# ---------------------------------------------------------------------------
# Issue 002 — resume_from_run plumbing through _run_workflow_isce2 (RED → GREEN)
# ---------------------------------------------------------------------------

def test_run_workflow_isce2_resume_skips_dedup_and_passes_resume_from_run(monkeypatch, tmp_path):
    """resume_from_run >= 1 bypasses the done/running dedup and launches a fresh job
    whose command resumes from the requested run step."""
    project = _make_stack_project(tmp_path)
    _save_job(project, "done")  # would normally deduplicate and refuse to relaunch

    popen_calls = []

    class FakeProcess:
        pid = 12345

    def fake_popen(*args, **kwargs):
        popen_calls.append((args, kwargs))
        return FakeProcess()

    monkeypatch.setattr(server.subprocess, "Popen", fake_popen)

    result = server._run_workflow_isce2(project, dry_run=False, resume_from_run=11)

    assert result.get("deduplicated") is not True
    assert result["status"] == "running"
    assert "RESUME_FROM=11" in str(result["command"])
    assert len(popen_calls) == 1


def test_run_workflow_isce2_resume_dry_run_command_resumes(monkeypatch, tmp_path):
    """A resume dry-run command must resume (RESUME_FROM=N) and not re-run prep."""
    project = _make_stack_project(tmp_path)

    result = server._run_workflow_isce2(project, dry_run=True, resume_from_run=7)

    assert "RESUME_FROM=7" in str(result["command"])
    assert "stackSentinel.py" not in str(result["command"])


# ---------------------------------------------------------------------------
# PHASE C2 — generate_only handoff + D3 topology-change resume refusal
# ---------------------------------------------------------------------------

def test_run_workflow_isce2_generate_only_command_stops_after_prep(tmp_path):
    """generate_only threads to build_stack_command: prep present, exec loop absent."""
    project = _make_stack_project(tmp_path)

    result = server._run_workflow_isce2(project, dry_run=True, generate_only=True)
    cmd = str(result["command"])

    assert "stackSentinel.py" in cmd
    assert "ls -v run_files/run_*" not in cmd  # no execution loop in the generate phase


def test_run_workflow_isce2_generate_only_writes_topology_signature(monkeypatch, tmp_path):
    """A real generate launch records the topology signature for a later resume guard."""
    project = _make_stack_project(tmp_path)
    project.run_id = "20260101T000000Z"

    class FakeProcess:
        pid = 4242

    monkeypatch.setattr(server.subprocess, "Popen", lambda *a, **k: FakeProcess())

    result = server._run_workflow_isce2(project, dry_run=False, generate_only=True)

    assert result["status"] == "running"
    stack_dir = server._resolve_run_layout(project).stack_dir
    assert (stack_dir / ".insar_stack_topology.json").exists()


def test_run_workflow_isce2_resume_refuses_on_topology_change(monkeypatch, tmp_path):
    """D3: resume must refuse when a topology param differs from the recorded run_files."""
    project = _make_stack_project(tmp_path)
    project.run_id = "20260101T000000Z"

    stack_dir = server._resolve_run_layout(project).stack_dir
    # run_files were generated earlier with num_connections=3 ...
    write_stack_topology(str(stack_dir), {**project.runconfig, "num_connections": 3})
    # ... the user then edits the topology param and tries to resume.
    project.runconfig["num_connections"] = 5

    def fail_popen(*args, **kwargs):
        del args, kwargs
        raise AssertionError("topology change must be refused before any launch")

    monkeypatch.setattr(server.subprocess, "Popen", fail_popen)

    result = server._run_workflow_isce2(project, dry_run=False, resume_from_run=1)

    assert result["error"] == "topology_changed"
    assert "num_connections" in result["changed_fields"]
    assert "generate_only=True" in result["message"]
    assert "resume_from_run=1" in result["message"]


def test_run_workflow_isce2_resume_allows_when_topology_unchanged(monkeypatch, tmp_path):
    """Resume proceeds when the recorded signature matches the current topology params."""
    project = _make_stack_project(tmp_path)
    project.run_id = "20260101T000000Z"

    stack_dir = server._resolve_run_layout(project).stack_dir
    write_stack_topology(str(stack_dir), project.runconfig)  # identical topology

    popen_calls = []

    class FakeProcess:
        pid = 777

    def fake_popen(*args, **kwargs):
        popen_calls.append((args, kwargs))
        return FakeProcess()

    monkeypatch.setattr(server.subprocess, "Popen", fake_popen)

    result = server._run_workflow_isce2(project, dry_run=False, resume_from_run=1)

    assert result.get("error") != "topology_changed"
    assert result["status"] == "running"
    assert "RESUME_FROM=1" in str(result["command"])
    assert len(popen_calls) == 1


def test_run_workflow_isce2_generate_only_skips_dedup_and_relaunches(monkeypatch, tmp_path):
    """generate_only=True must bypass the done/running dedup (like resume_from_run>=1
    already does): after a prior job for this run already reached 'done', calling
    generate_only=True again must regenerate run_files/configs + refresh the topology
    signature rather than silently short-circuiting to the stale done job. Without this,
    the D3 refusal's prescribed recovery (re-run to regenerate, then resume_from_run=1)
    is a silent no-op whenever a prior generate_only run already finished."""
    project = _make_stack_project(tmp_path)
    project.run_id = "20260101T000000Z"
    _save_job(project, "done")  # a prior generate_only launch already reached "done"

    popen_calls = []

    class FakeProcess:
        pid = 24680

    def fake_popen(*args, **kwargs):
        popen_calls.append((args, kwargs))
        return FakeProcess()

    monkeypatch.setattr(server.subprocess, "Popen", fake_popen)

    result = server._run_workflow_isce2(project, dry_run=False, generate_only=True)

    assert result.get("deduplicated") is not True
    assert result["status"] == "running"
    assert len(popen_calls) == 1
    stack_dir = server._resolve_run_layout(project).stack_dir
    assert (stack_dir / ".insar_stack_topology.json").exists()


def test_insar_run_workflow_generate_only_and_resume_mutually_exclusive(monkeypatch, tmp_path):
    """The public tool rejects generate_only + resume_from_run together."""
    project = _make_stack_project(tmp_path)
    monkeypatch.setattr(server.Project, "load", classmethod(lambda cls, pid: project))

    result = server.insar_run_workflow(
        project.project_id, generate_only=True, resume_from_run=5
    )

    assert result["status"] == "error"
    assert "mutually exclusive" in result["error"]


def test_insar_run_workflow_generate_only_rejected_for_non_stack(monkeypatch, tmp_path):
    """generate_only only applies to ISCE2 stack — a tops project is refused."""
    project = _make_tops_project(tmp_path)
    monkeypatch.setattr(server.Project, "load", classmethod(lambda cls, pid: project))

    result = server.insar_run_workflow(project.project_id, generate_only=True)

    assert result["status"] == "error"
    assert "stack" in result["error"].lower()


# ---------------------------------------------------------------------------
# C4 — tops from_step/to_step wiring through _run_workflow_isce2
# ---------------------------------------------------------------------------

def test_run_workflow_isce2_tops_from_to_step_builds_resume_command(monkeypatch, tmp_path):
    project = _make_tops_project(tmp_path)
    monkeypatch.setattr(server, "_validate_isce2_safe_annotation_geolocation", lambda _p, _w: [], raising=False)
    monkeypatch.setattr(server, "_validate_isce2_dem_scene_overlap", lambda _p, _w: [], raising=False)

    result = server._run_workflow_isce2(project, dry_run=True, from_step="unwrap", to_step="geocode")

    command = str(result["command"])
    assert "--steps --start=unwrap --end=geocode" in command
    assert "topsApp.py" in command


def test_run_workflow_isce2_tops_rejects_unknown_step(monkeypatch, tmp_path):
    project = _make_tops_project(tmp_path)
    monkeypatch.setattr(server, "_validate_isce2_safe_annotation_geolocation", lambda _p, _w: [], raising=False)
    monkeypatch.setattr(server, "_validate_isce2_dem_scene_overlap", lambda _p, _w: [], raising=False)

    result = server._run_workflow_isce2(project, dry_run=True, from_step="bogus")

    assert result["error"] == "params_invalid"
    assert any("bogus" in e for e in result["errors"])


def test_run_workflow_isce2_stack_rejects_from_step(tmp_path):
    project = _make_stack_project(tmp_path)
    result = server._run_workflow_isce2(project, dry_run=True, from_step="unwrap")
    assert result["error"] == "params_invalid"
    assert any("only apply to the ISCE2 tops" in (result["message"] + " ".join(result["errors"]))
               for _ in [0])


def test_run_workflow_isce2_tops_partial_bypasses_dedup(monkeypatch, tmp_path):
    """A tops step-window launch must NOT be deduplicated against a prior done job."""
    project = _make_tops_project(tmp_path)
    _save_job(project, "done")
    monkeypatch.setattr(server, "_validate_isce2_safe_annotation_geolocation", lambda _p, _w: [], raising=False)
    monkeypatch.setattr(server, "_validate_isce2_dem_scene_overlap", lambda _p, _w: [], raising=False)

    popen_calls = []

    class FakeProcess:
        pid = 4242

    def fake_popen(*args, **kwargs):
        popen_calls.append((args, kwargs))
        return FakeProcess()

    monkeypatch.setattr(server.subprocess, "Popen", fake_popen)

    result = server._run_workflow_isce2(project, dry_run=False, from_step="filter", to_step="geocode")

    assert result.get("deduplicated") is not True
    assert result["status"] == "running"
    assert "--start=filter --end=geocode" in str(result["command"])
    assert len(popen_calls) == 1


# ---------------------------------------------------------------------------
# PSF-final — start_step/end_step stack window wiring through
# insar_run_workflow / _run_workflow_isce2
# ---------------------------------------------------------------------------

def test_run_workflow_isce2_stack_start_end_step_builds_windowed_command(tmp_path):
    """start_step/end_step thread into build_stack_command as RESUME_FROM/RESUME_TO."""
    project = _make_stack_project(tmp_path)

    result = server._run_workflow_isce2(project, dry_run=True, start_step=5, end_step=8)

    command = str(result["command"])
    assert "RESUME_FROM=5" in command
    assert "RESUME_TO=8" in command
    assert "stackSentinel.py" not in command


def test_run_workflow_isce2_stack_window_bypasses_dedup(monkeypatch, tmp_path):
    """A stack start_step/end_step window launch must NOT be deduplicated against a
    prior done job — it is a deliberate remediation re-run, same as resume_from_run
    and tops_partial."""
    project = _make_stack_project(tmp_path)
    _save_job(project, "done")

    popen_calls = []

    class FakeProcess:
        pid = 5150

    def fake_popen(*args, **kwargs):
        popen_calls.append((args, kwargs))
        return FakeProcess()

    monkeypatch.setattr(server.subprocess, "Popen", fake_popen)

    result = server._run_workflow_isce2(project, dry_run=False, start_step=5, end_step=8)

    assert result.get("deduplicated") is not True
    assert result["status"] == "running"
    assert "RESUME_FROM=5" in str(result["command"])
    assert "RESUME_TO=8" in str(result["command"])
    assert len(popen_calls) == 1


def test_run_workflow_isce2_stack_window_refuses_on_topology_change(monkeypatch, tmp_path):
    """A start_step/end_step window must be refused, like resume_from_run, when a
    topology-changing param differs from what generated the existing run_files/ —
    otherwise it would silently reuse the old topology."""
    project = _make_stack_project(tmp_path)
    project.run_id = "20260101T000000Z"

    stack_dir = server._resolve_run_layout(project).stack_dir
    write_stack_topology(str(stack_dir), {**project.runconfig, "num_connections": 3})
    project.runconfig["num_connections"] = 5

    def fail_popen(*args, **kwargs):
        del args, kwargs
        raise AssertionError("topology change must be refused before any launch")

    monkeypatch.setattr(server.subprocess, "Popen", fail_popen)

    result = server._run_workflow_isce2(project, dry_run=False, start_step=5, end_step=8)

    assert result["error"] == "topology_changed"
    assert "num_connections" in result["changed_fields"]


def test_insar_run_workflow_stack_window_builds_resume_command(monkeypatch, tmp_path):
    """Public tool: insar_run_workflow(start_step=5, end_step=8) on a stack project
    builds the windowed command."""
    project = _make_stack_project(tmp_path)
    monkeypatch.setattr(server.Project, "load", classmethod(lambda cls, pid: project))

    result = server.insar_run_workflow(project.project_id, dry_run=True, start_step=5, end_step=8)

    command = str(result["command"])
    assert "RESUME_FROM=5" in command
    assert "RESUME_TO=8" in command


def test_insar_run_workflow_rejects_inverted_window(monkeypatch, tmp_path):
    project = _make_stack_project(tmp_path)
    monkeypatch.setattr(server.Project, "load", classmethod(lambda cls, pid: project))

    result = server.insar_run_workflow(project.project_id, dry_run=True, start_step=8, end_step=5)

    assert result["status"] == "error"
    assert "start_step" in result["error"] and "end_step" in result["error"]


def test_insar_run_workflow_rejects_window_combined_with_generate_only(monkeypatch, tmp_path):
    project = _make_stack_project(tmp_path)
    monkeypatch.setattr(server.Project, "load", classmethod(lambda cls, pid: project))

    result = server.insar_run_workflow(
        project.project_id, dry_run=True, start_step=5, generate_only=True
    )

    assert result["status"] == "error"
    assert "mutually exclusive" in result["error"]


def test_insar_run_workflow_rejects_window_combined_with_resume_from_run(monkeypatch, tmp_path):
    project = _make_stack_project(tmp_path)
    monkeypatch.setattr(server.Project, "load", classmethod(lambda cls, pid: project))

    result = server.insar_run_workflow(
        project.project_id, dry_run=True, start_step=5, resume_from_run=1
    )

    assert result["status"] == "error"
    assert "mutually exclusive" in result["error"]


def test_insar_run_workflow_rejects_window_for_non_stack_workflow(monkeypatch, tmp_path):
    project = _make_tops_project(tmp_path)
    monkeypatch.setattr(server.Project, "load", classmethod(lambda cls, pid: project))

    result = server.insar_run_workflow(project.project_id, dry_run=True, start_step=5, end_step=8)

    assert result["status"] == "error"
    assert "stack" in result["error"].lower()
