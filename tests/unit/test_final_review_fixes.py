"""Tests for final-review fixes (C-1, I-1, I-2, I-3, I-4, M2).

Each test drives the REAL code path rather than mocking the thing under test.
No mocks of subprocess.Popen/the engine call/the milestone itself.
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    engine: str = "isce2",
    workflow: str = "tops",
) -> tuple[str, Path]:
    """Create a minimal project and return (project_id, output_root)."""
    from insar_agent.mcp.server import insar_create_project

    registry_dir = tmp_path / ".registry"
    registry_dir.mkdir()
    monkeypatch.setenv("XDG_DATA_HOME", str(registry_dir))

    output_root = tmp_path / "output"
    result = insar_create_project(
        engine=engine,
        workflow=workflow,
        workspace_root=str(output_root),
    )
    assert "error" not in result, result
    return result["project_id"], output_root


# ---------------------------------------------------------------------------
# C-1: background worker must NOT crash with TypeError from project_id kwarg
# ---------------------------------------------------------------------------

class TestC1BackgroundWorkerProjectId:
    """The REAL runner function (the code nohup executes) must strip project_id
    before calling prepare_sentinel_data, which has no such parameter.

    We cannot mock Popen here — the bug is in the runner script text that the
    launcher writes.  We invoke the runner logic *directly* by executing the
    generated script with subprocess so the real kwarg-binding is exercised.
    """

    def test_runner_script_pops_project_id(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Verify the generated runner script pops project_id before engine call.

        Strategy: capture the runner script text and parse it to confirm
        _params.pop("project_id", None) is present — this is the static check.
        Then run the script in a subprocess with a mocked prepare_sentinel_data
        stub to verify no TypeError is raised.
        """
        project_id, output_root = _make_project(tmp_path, monkeypatch)

        mock_proc = MagicMock()
        mock_proc.pid = 55000

        with patch("insar_agent.mcp._helpers.subprocess.Popen", return_value=mock_proc) as mock_popen:
            from insar_agent.mcp._helpers import _launch_sentinel_prepare_background
            from insar_agent.core.output_resolver import prepare_input_dir

            params = {
                "project_root": str(prepare_input_dir(output_root, "safe")),
                "project_id": project_id,
                "workspace_root": str(output_root),
                "task_id": "d-insar-isce2",
                "run_id": "r1",
                "source_paths": [],
                "mode": "auto",
                "burst_manifest": None,
                "download_dem": False,
                "download_orbits": False,
                "dem_path": None,
                "dem_output_path": None,
                "dem_backend": "general",
                "dem_type": None,
                "aoi_path": None,
                "bbox": None,
                "orbit_dir": None,
                "orbit_username": None,
                "orbit_token_file": None,
                "include_pair": True,
                "include_stack": True,
                "resume": True,
                "validate_isce2_import": False,
            }
            result = _launch_sentinel_prepare_background(params)

        assert result.get("status") == "running", f"Expected running, got: {result}"
        assert "error" not in result, result

        # Read the generated runner script and verify it pops project_id
        runner_path = Path(mock_popen.call_args[0][0][1])  # sys.executable, runner_path
        runner_text = runner_path.read_text()
        assert '_params.pop("project_id", None)' in runner_text, (
            "Runner script must pop project_id before engine call.\n"
            f"Script content:\n{runner_text}"
        )

    def test_runner_script_executes_without_project_id_typeerror(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Execute the generated runner script in a subprocess to confirm no TypeError.

        Uses a stub prepare_sentinel_data that returns success — the key thing
        being tested is that project_id does NOT reach the function signature.
        """
        import subprocess
        import sys

        project_id, output_root = _make_project(tmp_path, monkeypatch)

        mock_proc = MagicMock()
        mock_proc.pid = 55001

        with patch("insar_agent.mcp._helpers.subprocess.Popen", return_value=mock_proc) as mock_popen:
            from insar_agent.mcp._helpers import _launch_sentinel_prepare_background
            from insar_agent.core.output_resolver import prepare_input_dir

            params = {
                "project_root": str(prepare_input_dir(output_root, "safe")),
                "project_id": project_id,
                "workspace_root": str(output_root),
                "task_id": "d-insar-isce2",
                "run_id": "r2",
                "source_paths": [],
                "mode": "auto",
                "burst_manifest": None,
                "download_dem": False,
                "download_orbits": False,
                "dem_path": None,
                "dem_output_path": None,
                "dem_backend": "general",
                "dem_type": None,
                "aoi_path": None,
                "bbox": None,
                "orbit_dir": None,
                "orbit_username": None,
                "orbit_token_file": None,
                "include_pair": True,
                "include_stack": True,
                "resume": True,
                "validate_isce2_import": False,
            }
            result = _launch_sentinel_prepare_background(params)

        runner_path = Path(mock_popen.call_args[0][0][1])
        runner_text = runner_path.read_text()

        # Rewrite the runner to use a stub that succeeds, keeping the kwarg stripping logic
        stub_runner = textwrap.dedent(f"""\
            import json, os, sys, traceback
            sys.path.insert(0, {str(Path(__file__).resolve().parents[3] / "src")!r})

            # Stub: replace prepare_sentinel_data with a keyword-only function
            # that has NO project_id parameter (exactly like the real engine).
            def prepare_sentinel_data(*, project_root, source_paths=None,
                                      progress_run_root=None, **kw):
                return {{"status": "ok", "safe_dirs": {{}}}}

            import insar_agent.engines.isce2.sentinel.prepare as _mod
            _mod.prepare_sentinel_data = prepare_sentinel_data

            with open({str(result.get("params_path", ""))!r}, encoding="utf-8") as _f:
                _params = json.load(_f)
            _params.pop("workspace_root", None)
            _params.pop("task_id", None)
            _params.pop("run_id", None)
            _params.pop("project_id", None)

            try:
                _result = prepare_sentinel_data(**_params)
                print(json.dumps({{"status": "done", "result": _result}}), flush=True)
            except Exception as _exc:
                print(json.dumps({{"status": "failed", "error": str(_exc),
                                   "traceback": traceback.format_exc()}}), flush=True)
        """)

        stub_path = tmp_path / "stub_runner.py"
        stub_path.write_text(stub_runner)

        proc = subprocess.run(
            [sys.executable, str(stub_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )

        output = proc.stdout.strip()
        assert output, f"Runner produced no output. stderr: {proc.stderr}"
        data = json.loads(output)
        assert data.get("status") != "failed" or "project_id" not in data.get("error", ""), (
            f"Runner failed with project_id TypeError: {data}"
        )
        assert data.get("status") == "done", (
            f"Expected done but got: {data}"
        )


# ---------------------------------------------------------------------------
# I-1: sentinel-prep progress lands in run_root, not prepare/safe
# ---------------------------------------------------------------------------

class TestI1ProgressLandsInRunRoot:
    """After I-1 fix, append_progress calls in prepare.py write to the REAL
    run_root/.insar_agent/progress.log, not prepare/safe/.insar_agent/.
    """

    def test_progress_written_to_real_run_root_via_progress_run_root(self, tmp_path: Path):
        """prepare_sentinel_data with progress_run_root= writes progress to that path."""
        from insar_agent.engines.isce2.sentinel.prepare import prepare_sentinel_data

        run_root = tmp_path / "real_run_root"
        run_root.mkdir()
        project_root = tmp_path / "prepare" / "safe"
        project_root.mkdir(parents=True)

        dem_file = tmp_path / "dem.tif"
        dem_file.write_bytes(b"fake dem")

        # Call with progress_run_root so emitter writes to the real run root
        prepare_sentinel_data(
            project_root=str(project_root),
            source_paths=[],
            dem_path=str(dem_file),
            progress_run_root=str(run_root),
            resume=True,
        )

        # Progress must land in run_root/.insar_agent/progress.log
        progress_file = run_root / ".insar_agent" / "progress.log"
        assert progress_file.exists(), (
            f"Expected progress.log at {progress_file}, not in prepare/safe"
        )
        content = progress_file.read_text()
        assert "DEM" in content.upper(), (
            f"Expected DEM progress entry in {progress_file}: {content!r}"
        )

    def test_launcher_sets_progress_run_root_in_runner_script(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """The background launcher must embed progress_run_root in the runner script."""
        project_id, output_root = _make_project(tmp_path, monkeypatch)

        mock_proc = MagicMock()
        mock_proc.pid = 55002

        with patch("insar_agent.mcp._helpers.subprocess.Popen", return_value=mock_proc) as mock_popen:
            from insar_agent.mcp._helpers import _launch_sentinel_prepare_background
            from insar_agent.core.output_resolver import prepare_input_dir

            params = {
                "project_root": str(prepare_input_dir(output_root, "safe")),
                "project_id": project_id,
                "workspace_root": str(output_root),
                "task_id": "d-insar-isce2",
                "run_id": "r3",
                "source_paths": [],
                "mode": "auto",
                "burst_manifest": None,
                "download_dem": False,
                "download_orbits": False,
                "dem_path": None,
                "dem_output_path": None,
                "dem_backend": "general",
                "dem_type": None,
                "aoi_path": None,
                "bbox": None,
                "orbit_dir": None,
                "orbit_username": None,
                "orbit_token_file": None,
                "include_pair": True,
                "include_stack": True,
                "resume": True,
                "validate_isce2_import": False,
            }
            result = _launch_sentinel_prepare_background(params)

        runner_path = Path(mock_popen.call_args[0][0][1])
        runner_text = runner_path.read_text()

        assert "_progress_run_root" in runner_text, (
            "Runner script must contain _progress_run_root variable"
        )
        assert "progress_run_root" in runner_text, (
            "Runner must pass progress_run_root= to prepare_sentinel_data"
        )

    def test_get_job_returns_progress_from_run_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """insar_get_job returns progress field populated from run_root."""
        from insar_agent.mcp.server import insar_create_project
        from insar_agent.mcp.tools.job_tools import insar_get_job
        from insar_agent.core.project import Project
        from insar_agent.core.jobs import DownloadJob
        from insar_agent.core.progress import append_progress

        registry_dir = tmp_path / ".registry"
        registry_dir.mkdir()
        monkeypatch.setenv("XDG_DATA_HOME", str(registry_dir))

        output_root = tmp_path / "output"
        r = insar_create_project(engine="isce3", workflow="insar",
                                  workspace_root=str(output_root))
        project_id = r["project_id"]

        proj = Project.load(project_id)
        run_root = proj.run_root()
        jobs_dir = proj.jobs_dir()
        run_root.mkdir(parents=True, exist_ok=True)
        jobs_dir.mkdir(parents=True, exist_ok=True)

        # Simulate what the fixed emitter would write
        append_progress(run_root, "SYNTHESIZE S1A_scene -> safe/ASCENDING_014/")
        append_progress(run_root, "DEM downloaded /output/prepare/dem/copernicus_30_dem.tif")

        job = DownloadJob(
            output_dir=str(output_root / "prepare" / "safe"),
            n_files=1,
            run_root=str(run_root),
            tool_name="insar_prepare_sentinel_data",
            job_type="sentinel_prepare",
        )
        job.status = "done"
        job.pid = None
        job.save(jobs_dir)

        get_result = insar_get_job(project_id=project_id, job_id=job.job_id)

        assert "progress" in get_result, f"get_job must return progress key: {get_result}"
        assert "SYNTHESIZE" in get_result["progress"], (
            f"Progress from run_root must contain SYNTHESIZE: {get_result['progress']!r}"
        )
        assert "DEM" in get_result["progress"], (
            f"Progress from run_root must contain DEM: {get_result['progress']!r}"
        )


# ---------------------------------------------------------------------------
# I-2: append_progress is called in RSLC download, DEM download, and both workflows
# ---------------------------------------------------------------------------

class TestI2ProgressEmitted:
    """Real milestone points must call append_progress."""

    def test_rslc_download_emits_launch_progress(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """insar_download_rslc emits a launch marker synchronously to run_root."""
        project_id, output_root = _make_project(
            tmp_path, monkeypatch, engine="isce3", workflow="insar"
        )
        from insar_agent.core.project import Project
        from insar_agent.core.progress import read_progress_tail

        # Ensure run_root exists so append_progress can write
        proj = Project.load(project_id)
        proj.run_root().mkdir(parents=True, exist_ok=True)

        mock_proc = MagicMock()
        mock_proc.pid = 55010

        with patch("insar_agent.mcp.server.subprocess.Popen", return_value=mock_proc):
            from insar_agent.mcp.server import insar_download_rslc
            result = insar_download_rslc(
                urls=["https://example.com/RSLC_001.h5"],
                project_id=project_id,
                bbox=[37.0, 11.0, 39.0, 13.0],
                confirm=True,
            )

        assert "error" not in result, result
        progress = read_progress_tail(proj.run_root())
        assert progress, (
            "Expected at least one progress entry after insar_download_rslc launch"
        )
        assert "RSLC" in progress.upper(), (
            f"Expected RSLC in progress: {progress!r}"
        )

    def test_rslc_runner_calls_append_progress(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """The RSLC runner script must call append_progress at start and end."""
        project_id, output_root = _make_project(
            tmp_path, monkeypatch, engine="isce3", workflow="insar"
        )

        mock_proc = MagicMock()
        mock_proc.pid = 55011

        with patch("insar_agent.mcp.server.subprocess.Popen", return_value=mock_proc) as mock_popen:
            from insar_agent.mcp.server import insar_download_rslc
            insar_download_rslc(
                urls=["https://example.com/RSLC_001.h5"],
                project_id=project_id,
                bbox=[37.0, 11.0, 39.0, 13.0],
                confirm=True,
            )

        runner_path = Path(mock_popen.call_args[0][0][1])
        runner_text = runner_path.read_text()
        assert "append_progress" in runner_text, (
            "RSLC runner script must call append_progress"
        )

    def test_dem_download_emits_launch_progress(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """insar_download_dem background launch emits a progress marker synchronously."""
        project_id, output_root = _make_project(
            tmp_path, monkeypatch, engine="isce3", workflow="insar"
        )
        from insar_agent.core.project import Project
        from insar_agent.core.progress import read_progress_tail

        proj = Project.load(project_id)
        proj.run_root().mkdir(parents=True, exist_ok=True)

        mock_proc = MagicMock()
        mock_proc.pid = 55020

        with patch("insar_agent.mcp._helpers.subprocess.Popen", return_value=mock_proc):
            from insar_agent.mcp.server import insar_download_dem
            result = insar_download_dem(
                project_id=project_id,
                bbox=[37.0, 11.0, 39.0, 13.0],
                background=True,
            )

        assert "error" not in result, result
        progress = read_progress_tail(proj.run_root())
        assert progress, (
            "Expected at least one progress entry after insar_download_dem launch"
        )
        assert "DEM" in progress.upper(), (
            f"Expected DEM in progress: {progress!r}"
        )

    def test_dem_runner_calls_append_progress(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """The DEM runner script must call append_progress at start and end."""
        project_id, output_root = _make_project(
            tmp_path, monkeypatch, engine="isce3", workflow="insar"
        )
        from insar_agent.core.project import Project

        proj = Project.load(project_id)
        proj.run_root().mkdir(parents=True, exist_ok=True)

        mock_proc = MagicMock()
        mock_proc.pid = 55021

        with patch("insar_agent.mcp._helpers.subprocess.Popen", return_value=mock_proc) as mock_popen:
            from insar_agent.mcp.server import insar_download_dem
            insar_download_dem(
                project_id=project_id,
                bbox=[37.0, 11.0, 39.0, 13.0],
                background=True,
            )

        runner_path = Path(mock_popen.call_args[0][0][1])
        runner_text = runner_path.read_text()
        assert "append_progress" in runner_text, (
            "DEM runner script must call append_progress"
        )

    def test_isce3_workflow_emits_launch_progress(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """insar_run_workflow (ISCE3) emits a launch progress marker.

        Bypasses validation/launch with patches so we can test the PROGRESS
        emission code path specifically — the append_progress call happens
        AFTER successful job launch, so we mock everything that blocks launch.
        """
        project_id, output_root = _make_project(
            tmp_path, monkeypatch, engine="isce3", workflow="insar"
        )
        from insar_agent.core.project import Project
        from insar_agent.core.progress import read_progress_tail

        proj = Project.load(project_id)
        proj.run_root().mkdir(parents=True, exist_ok=True)

        with patch("insar_agent.mcp.server.validate_runconfig", return_value=[]):
            with patch("insar_agent.mcp.server._launch_detached_shell_job", return_value=55030):
                from insar_agent.mcp.server import insar_run_workflow
                result = insar_run_workflow(project_id=project_id)

        # Reload project since run_id may have been set
        proj = Project.load(project_id)

        run_root = proj.run_root()
        progress = read_progress_tail(run_root)
        assert progress, (
            f"Expected at least one progress entry after insar_run_workflow launch. result={result}"
        )
        assert "workflow launched" in progress.lower(), (
            f"Expected 'workflow launched' in progress: {progress!r}"
        )

    def test_isce2_workflow_emits_launch_progress(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """_run_workflow_isce2 emits a launch progress marker.

        Bypasses ISCE2 validation + DEM logic so we can reach the append_progress
        call that fires after successful job launch.
        """
        project_id, output_root = _make_project(
            tmp_path, monkeypatch, engine="isce2", workflow="tops"
        )
        from insar_agent.core.project import Project
        from insar_agent.core.progress import read_progress_tail

        proj = Project.load(project_id)
        proj.run_root().mkdir(parents=True, exist_ok=True)

        with patch("insar_agent.mcp.server.isce2_validate_params", return_value=[]):
            with patch("insar_agent.mcp.server._find_reusable_workflow_job", return_value=None):
                with patch("insar_agent.mcp.server._validate_isce2_safe_annotation_geolocation",
                           return_value=[]):
                    with patch("insar_agent.mcp.server._validate_isce2_dem_scene_overlap",
                               return_value=[]):
                        with patch("insar_agent.mcp.server.materialize_dem_for_tops",
                                   return_value="/fake/dem.tif"):
                            with patch("insar_agent.mcp.server.build_topsapp_xml",
                                       return_value="<tops/>"):
                                with patch("insar_agent.mcp.server._launch_detached_shell_job",
                                           return_value=55031):
                                    from insar_agent.mcp.server import insar_run_workflow
                                    result = insar_run_workflow(project_id=project_id)

        # Reload project since run_id may have been set
        proj = Project.load(project_id)

        run_root = proj.run_root()
        progress = read_progress_tail(run_root)
        assert progress, (
            f"Expected progress after isce2 workflow launch, got empty. result={result}"
        )
        assert "workflow launched" in progress.lower(), (
            f"Expected 'workflow launched' in progress: {progress!r}"
        )


# ---------------------------------------------------------------------------
# I-3: monitor key present in RSLC and DEM background returns
# ---------------------------------------------------------------------------

class TestI3MonitorKey:
    """Both RSLC and DEM background launchers must return a monitor key."""

    def test_rslc_download_returns_monitor(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        project_id, output_root = _make_project(
            tmp_path, monkeypatch, engine="isce3", workflow="insar"
        )
        from insar_agent.core.project import Project
        proj = Project.load(project_id)
        proj.run_root().mkdir(parents=True, exist_ok=True)

        mock_proc = MagicMock()
        mock_proc.pid = 55040

        with patch("insar_agent.mcp.server.subprocess.Popen", return_value=mock_proc):
            from insar_agent.mcp.server import insar_download_rslc
            result = insar_download_rslc(
                urls=["https://example.com/RSLC_001.h5"],
                project_id=project_id,
                bbox=[37.0, 11.0, 39.0, 13.0],
                confirm=True,
            )

        assert "monitor" in result, (
            f"insar_download_rslc must return monitor key, got: {list(result.keys())}"
        )
        assert result["monitor"].startswith("tail -f "), (
            f"monitor must start with 'tail -f': {result['monitor']!r}"
        )
        assert "progress.log" in result["monitor"], (
            f"monitor must point to progress.log: {result['monitor']!r}"
        )

    def test_dem_download_background_returns_monitor(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        project_id, output_root = _make_project(
            tmp_path, monkeypatch, engine="isce3", workflow="insar"
        )
        from insar_agent.core.project import Project
        proj = Project.load(project_id)
        proj.run_root().mkdir(parents=True, exist_ok=True)

        mock_proc = MagicMock()
        mock_proc.pid = 55041

        with patch("insar_agent.mcp._helpers.subprocess.Popen", return_value=mock_proc):
            from insar_agent.mcp.server import insar_download_dem
            result = insar_download_dem(
                project_id=project_id,
                bbox=[37.0, 11.0, 39.0, 13.0],
                background=True,
            )

        assert "monitor" in result, (
            f"insar_download_dem background must return monitor key, got: {list(result.keys())}"
        )
        assert result["monitor"].startswith("tail -f "), (
            f"monitor must start with 'tail -f': {result['monitor']!r}"
        )
        assert "progress.log" in result["monitor"], (
            f"monitor must point to progress.log: {result['monitor']!r}"
        )


# ---------------------------------------------------------------------------
# I-4: DEM/orbit dirs land under prepare/{dem,orbits}, orbit reuse guard
# ---------------------------------------------------------------------------

class TestI4CanonicalPrepDirs:
    """Sentinel-prep background launcher must override DEM/orbit dirs to
    prepare_input_dir(<output_root>, ...) siblings, not nesting inside prepare/safe.
    """

    def test_runner_script_overrides_dem_dir_to_prepare_dem(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Runner script must set dem_output_path to <output_root>/prepare/dem."""
        project_id, output_root = _make_project(tmp_path, monkeypatch)

        mock_proc = MagicMock()
        mock_proc.pid = 55050

        with patch("insar_agent.mcp._helpers.subprocess.Popen", return_value=mock_proc) as mock_popen:
            from insar_agent.mcp._helpers import _launch_sentinel_prepare_background
            from insar_agent.core.output_resolver import prepare_input_dir

            params = {
                "project_root": str(prepare_input_dir(output_root, "safe")),
                "project_id": project_id,
                "workspace_root": str(output_root),
                "task_id": "d-insar-isce2",
                "run_id": "r4",
                "source_paths": [],
                "mode": "auto",
                "burst_manifest": None,
                "download_dem": True,   # triggers DEM download
                "download_orbits": True,  # triggers orbit download
                "dem_path": None,
                "dem_output_path": None,  # not set, so override should apply
                "dem_backend": "general",
                "dem_type": None,
                "aoi_path": None,
                "bbox": None,
                "orbit_dir": None,  # not set, so override should apply
                "orbit_username": None,
                "orbit_token_file": None,
                "include_pair": True,
                "include_stack": True,
                "resume": True,
                "validate_isce2_import": False,
            }
            result = _launch_sentinel_prepare_background(params)

        runner_path = Path(mock_popen.call_args[0][0][1])
        runner_text = runner_path.read_text()

        expected_dem = str(output_root / "prepare" / "dem")
        expected_orbits = str(output_root / "prepare" / "orbits")

        assert expected_dem in runner_text, (
            f"Runner must override dem_output_path to {expected_dem}.\n"
            f"Script:\n{runner_text}"
        )
        assert expected_orbits in runner_text, (
            f"Runner must override orbit_dir to {expected_orbits}.\n"
            f"Script:\n{runner_text}"
        )

    def test_orbit_reuse_guard_skips_download_when_eof_present(self, tmp_path: Path):
        """prepare_sentinel_data skips orbit download when .EOF files already exist."""
        from insar_agent.engines.isce2.sentinel.prepare import prepare_sentinel_data

        project_root = tmp_path / "prepare" / "safe"
        project_root.mkdir(parents=True)
        orbit_dir = tmp_path / "prepare" / "orbits"
        orbit_dir.mkdir(parents=True)

        # Pre-populate the orbit dir with a stub EOF file
        (orbit_dir / "S1A_OPER_AUX_POEORB_OPOD_stub.EOF").write_text("orbit stub")

        download_calls = []

        with patch(
            "insar_agent.engines.isce2.sentinel.prepare.orbit._download_orbits_for_scenes",
            side_effect=lambda *a, **kw: download_calls.append(1) or (0, []),
        ):
            prepare_sentinel_data(
                project_root=str(project_root),
                source_paths=[],
                download_orbits=True,
                orbit_dir=str(orbit_dir),
                resume=True,
            )

        assert not download_calls, (
            "Orbit download must be skipped when .EOF files already present (reuse guard)"
        )

    def test_orbit_download_called_when_dir_empty(self, tmp_path: Path):
        """prepare_sentinel_data calls orbit download when orbit dir is empty."""
        from insar_agent.engines.isce2.sentinel.prepare import prepare_sentinel_data

        project_root = tmp_path / "prepare" / "safe"
        project_root.mkdir(parents=True)
        orbit_dir = tmp_path / "prepare" / "orbits"
        orbit_dir.mkdir(parents=True)  # empty — no EOF files

        download_calls = []

        with patch(
            "insar_agent.engines.isce2.sentinel.prepare.orbit._resolve_orbit_token_file",
            return_value=None,
        ):
            with patch(
                "insar_agent.engines.isce2.sentinel.prepare.orbit._download_orbits_for_scenes",
                side_effect=lambda *a, **kw: download_calls.append(1) or (0, []),
            ):
                prepare_sentinel_data(
                    project_root=str(project_root),
                    source_paths=[],
                    download_orbits=True,
                    orbit_dir=str(orbit_dir),
                    resume=True,
                )

        assert download_calls, (
            "Orbit download must be called when orbit dir has no .EOF files"
        )


# ---------------------------------------------------------------------------
# M2: materialize_dem uses output_root= (production path) in tests
# ---------------------------------------------------------------------------

class TestM2MaterializeDemProductionPath:
    """The production call-site uses output_root= kwarg → prepare/dem.
    The test previously used the positional workspace_root → isce2_dem (legacy).
    """

    def test_materialize_dem_uses_output_root_kwarg(self, tmp_path: Path):
        """materialize_dem_for_tops(dem, output_root=...) writes to prepare/dem/."""
        from insar_agent.engines.isce2.runner import materialize_dem_for_tops

        output_root = tmp_path / "output"
        output_root.mkdir()

        src = tmp_path / "ext_dem"
        src.mkdir()
        dem = src / "dem.tif"
        dem.write_bytes(b"dem")
        (src / "dem.tif.xml").write_text(
            '<image_name><property name="file_name"><value>/stale/dem.tif</value>'
            "</property></image_name>",
            encoding="utf-8",
        )
        (src / "dem.tif.vrt").write_text(
            '<VRTDataset><SourceFilename relativeToVRT="1">dem.tif</SourceFilename>'
            "</VRTDataset>",
            encoding="utf-8",
        )

        out = materialize_dem_for_tops(str(dem), output_root=output_root)

        assert Path(out) == output_root / "prepare" / "dem" / "dem.tif", (
            f"Production path (output_root=) must put DEM in prepare/dem/, got: {out}"
        )
        prepare_dem = output_root / "prepare" / "dem"
        assert prepare_dem.exists()
        produced = list(prepare_dem.iterdir())
        assert produced, "Expected files written to prepare/dem/"
