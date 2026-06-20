"""Tool-boundary tests for Phase-3 critical/important fixes.

Each test exercises an ACTUAL tool entry point (not a helper) and specifically
targets a defect that was masked by the green 581-test suite:

C1 — insar_download_rslc(project_id=...) previously returned missing_task_context.
     Fixed: uses project.jobs_dir() directly; includes reuse guard.
C2 — insar_prepare_sentinel_data(project_id=..., background=True) returned
     missing_task_context.  Fixed: _launch_sentinel_prepare_background uses
     project.jobs_dir() when project_id present.
C3 — _run_workflow_isce2 ISCE2 tops caller passed dem_root positionally →
     DEM landed in <run_root>/isce2_dem. Fixed: output_root= kwarg → prepare/dem.
I1 — insar_run_mintpy / insar_run_mintpy_isce2 used .parent.parent depth math.
     Fixed: find_run_root-based check; updated stale recommendation string.
I3 — insar_list_outputs legacy globs scanned output_root (all-runs parent).
     Fixed: scoped to run_root (ISCE2) or insar_product_dir (ISCE3).
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from insar_agent.mcp.server import (
    insar_download_rslc,
    insar_prepare_sentinel_data,
    insar_create_project,
    insar_list_outputs,
)
from insar_agent.mcp import server


# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------

def _make_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    engine: str = "isce3",
    workflow: str = "insar",
):
    """Create a project via the real tool and return (project_id, output_root)."""
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
# C1 — insar_download_rslc project_id branch
# ---------------------------------------------------------------------------

class TestDownloadRslcProjectId:
    """insar_download_rslc(project_id=...) must not return missing_task_context."""

    FAKE_URLS = [
        "https://example.com/NISAR_L1_PR_RSLC_001.h5",
    ]

    def test_project_id_branch_resolves_job_context(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """C1: project_id path must succeed; job file must be saved under project.jobs_dir()."""
        project_id, output_root = _make_project(tmp_path, monkeypatch)

        mock_proc = MagicMock()
        mock_proc.pid = 42000

        with patch("insar_agent.mcp.server.subprocess.Popen", return_value=mock_proc):
            result = insar_download_rslc(
                urls=self.FAKE_URLS,
                project_id=project_id,
                bbox=[35.0, 10.0, 36.0, 11.0],
            )

        # Before fix this returned {"error": "missing_task_context"}.
        assert result.get("error") != "missing_task_context", (
            f"project_id branch returned missing_task_context — C1 not fixed: {result}"
        )
        assert "error" not in result, result
        assert result.get("status") == "running"

    def test_project_id_output_dir_under_prepare_rslc(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """C1: output_dir must be under output_root/prepare/rslc."""
        project_id, output_root = _make_project(tmp_path, monkeypatch)

        mock_proc = MagicMock()
        mock_proc.pid = 42001

        with patch("insar_agent.mcp.server.subprocess.Popen", return_value=mock_proc):
            result = insar_download_rslc(
                urls=self.FAKE_URLS,
                project_id=project_id,
                bbox=[35.0, 10.0, 36.0, 11.0],
            )

        assert "error" not in result, result
        out_dir = Path(result["output_dir"])
        expected_prefix = (output_root / "prepare" / "rslc").resolve()
        assert out_dir.is_relative_to(expected_prefix), (
            f"RSLC output_dir should be under {expected_prefix}, got {out_dir}"
        )

    def test_project_id_job_saved_to_project_jobs_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """C1: DownloadJob must be persisted in project.jobs_dir()."""
        from insar_agent.core.project import Project
        from insar_agent.core.jobs import DownloadJob

        project_id, output_root = _make_project(tmp_path, monkeypatch)

        mock_proc = MagicMock()
        mock_proc.pid = 42002

        with patch("insar_agent.mcp.server.subprocess.Popen", return_value=mock_proc):
            result = insar_download_rslc(
                urls=self.FAKE_URLS,
                project_id=project_id,
                bbox=[35.0, 10.0, 36.0, 11.0],
            )

        assert "error" not in result, result
        proj = Project.load(project_id)
        jobs_dir = proj.jobs_dir()
        job_id = result["job_id"]
        # Job file must exist in project.jobs_dir()
        assert (jobs_dir / f"{job_id}.json").exists(), (
            f"Job {job_id} not found in {jobs_dir} — C1 job tracking broken"
        )

    def test_project_id_reuse_guard_skips_existing_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """C1 reuse guard: if output_dir already has content, skip download."""
        from insar_agent.core.output_resolver import prepare_input_dir
        from insar_agent.core.project import Project

        project_id, output_root = _make_project(tmp_path, monkeypatch)
        proj = Project.load(project_id)
        rslc_dir = prepare_input_dir(proj.output_root, "rslc")
        rslc_dir.mkdir(parents=True, exist_ok=True)
        # Place a dummy file to mark directory as non-empty
        (rslc_dir / "existing.h5").write_bytes(b"fake")

        popen_calls: list = []
        with patch("insar_agent.mcp.server.subprocess.Popen", side_effect=popen_calls.append):
            result = insar_download_rslc(
                urls=self.FAKE_URLS,
                project_id=project_id,
                bbox=[35.0, 10.0, 36.0, 11.0],
            )

        assert "error" not in result, result
        assert result.get("reused") is True, (
            f"Reuse guard not triggered for existing RSLC dir: {result}"
        )
        assert popen_calls == [], "Popen called despite RSLC dir already present"


# ---------------------------------------------------------------------------
# C2 — insar_prepare_sentinel_data project_id + background
# ---------------------------------------------------------------------------

class TestPrepareSentinelBackground:
    """insar_prepare_sentinel_data(project_id=..., background=True) must not error."""

    def test_background_true_does_not_return_missing_task_context(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """C2: project_id + background=True must return a running job, not missing_task_context."""
        project_id, output_root = _make_project(
            tmp_path, monkeypatch, engine="isce2", workflow="tops"
        )

        mock_proc = MagicMock()
        mock_proc.pid = 43000

        with patch("insar_agent.mcp.server.subprocess.Popen", return_value=mock_proc):
            result = insar_prepare_sentinel_data(
                project_id=project_id,
                source_paths=[],
                background=True,
            )

        # Before fix this returned {"error": "missing_task_context"}.
        assert result.get("error") != "missing_task_context", (
            f"project_id + background=True returned missing_task_context — C2 not fixed: {result}"
        )
        assert "error" not in result, result
        assert result.get("status") == "running", result

    def test_background_job_saved_to_project_jobs_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """C2: sentinel background job must be persisted in project.jobs_dir()."""
        from insar_agent.core.project import Project
        from insar_agent.core.jobs import DownloadJob

        project_id, output_root = _make_project(
            tmp_path, monkeypatch, engine="isce2", workflow="tops"
        )

        mock_proc = MagicMock()
        mock_proc.pid = 43001

        with patch("insar_agent.mcp.server.subprocess.Popen", return_value=mock_proc):
            result = insar_prepare_sentinel_data(
                project_id=project_id,
                source_paths=[],
                background=True,
            )

        assert "error" not in result, result
        proj = Project.load(project_id)
        jobs_dir = proj.jobs_dir()
        job_id = result["job_id"]
        assert (jobs_dir / f"{job_id}.json").exists(), (
            f"Sentinel background job {job_id} not saved to {jobs_dir} — C2 broken"
        )


# ---------------------------------------------------------------------------
# C3 — _run_workflow_isce2 DEM caller uses output_root= kwarg
# ---------------------------------------------------------------------------

class TestIsce2DemCaller:
    """DEM must land at output_root/prepare/dem/ not run_root/isce2_dem/."""

    def _make_tops_project(self, tmp_path: Path):
        from insar_agent.core.project import Project
        dem_file = tmp_path / "dem.tif"
        dem_file.write_bytes(b"dem")
        # Create .xml and .vrt sidecars to trigger materialize_dem_for_tops
        dem_file.with_suffix(".tif.xml").write_text(
            """<image_name><property name="file_name"><value>/stale/dem.tif</value></property></image_name>""",
            encoding="utf-8",
        )
        dem_file.with_suffix(".tif.vrt").write_text(
            """<VRTDataset rasterXSize="1" rasterYSize="1">
  <VRTRasterBand dataType="Float32" band="1">
    <SourceFilename relativeToVRT="1">dem.tif</SourceFilename>
  </VRTRasterBand>
</VRTDataset>""",
            encoding="utf-8",
        )
        (tmp_path / "ref.SAFE").mkdir()
        (tmp_path / "sec.SAFE").mkdir()
        (tmp_path / "orbits").mkdir()
        return Project(
            name="test-tops",
            engine="isce2",
            workflow="tops",
            output_root=str(tmp_path / "workspace"),
            project_id="c3-test",
            runconfig={
                "reference_safe": str(tmp_path / "ref.SAFE"),
                "secondary_safe": str(tmp_path / "sec.SAFE"),
                "orbit_dir": str(tmp_path / "orbits"),
                "dem_file": str(dem_file),
            },
            conda_env="isce2",
            task="d-insar-isce2",
        )

    def test_dem_lands_under_prepare_dem_not_isce2_dem(self, monkeypatch, tmp_path):
        """C3: materialize_dem_for_tops caller must use output_root= kwarg.

        materialize_dem_for_tops copies .xml/.vrt sidecars into prepare/dem/
        but leaves the binary DEM in place (VRT points back to source).
        So we verify: (a) sidecar .xml exists in prepare/dem/, (b) topsApp.xml
        references the prepare/dem path, (c) legacy isce2_dem/ is NOT created.
        """
        project = self._make_tops_project(tmp_path)
        monkeypatch.setattr(
            server, "_validate_isce2_safe_annotation_geolocation",
            lambda _p, _w: [], raising=False,
        )
        monkeypatch.setattr(
            server, "_validate_isce2_dem_scene_overlap",
            lambda _p, _w: [], raising=False,
        )

        result = server._run_workflow_isce2(project, dry_run=True)

        assert "error" not in result, result
        run_root = Path(result["run_root"])
        output_root = Path(project.output_root)

        # materialize_dem_for_tops writes sidecars to prepare/dem/
        # (it does NOT copy the binary DEM — VRT points back to source).
        expected_sidecar = output_root / "prepare" / "dem" / "dem.tif.xml"
        assert expected_sidecar.exists(), (
            f"DEM sidecar not found at {expected_sidecar} — C3 caller not using output_root= kwarg"
        )

        # Legacy isce2_dem path must NOT exist
        assert not (run_root / "isce2_dem").exists(), (
            f"Legacy run_root/isce2_dem dir was created — C3 caller still uses legacy path"
        )
        assert not (output_root / "isce2_dem").exists(), (
            f"Legacy output_root/isce2_dem dir was created — C3 caller still uses legacy path"
        )

        # The rendered XML must reference the prepare/dem path
        expected_dem_path = output_root / "prepare" / "dem" / "dem.tif"
        config = (run_root / "insar_product" / "configs" / "topsApp.xml").read_text()
        assert str(expected_dem_path) in config, (
            f"topsApp.xml does not reference prepare/dem DEM path — C3 broken. "
            f"Expected {expected_dem_path} in XML. Config: {config[:300]}"
        )


# ---------------------------------------------------------------------------
# I1 — mintpy depth heuristic replaced with find_run_root
# ---------------------------------------------------------------------------

class TestMintpyLayoutWarning:
    """I1: layout_warning must not use .parent.parent math; updated recommendation string."""

    def _make_fake_mintpy_result(self, job_id: str, mintpy_dir: Path) -> dict:
        return {
            "job_id": job_id,
            "pid": 50000,
            "status": "running",
            "submitted_at": "2026-01-01T00:00:00Z",
            "log_path": str(mintpy_dir / "logs" / f"{job_id}.log"),
            "command": ["smallbaselineApp.py"],
        }

    def test_run_mintpy_no_depth_math_stale_string(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """I1: layout_warning must not contain stale '<workspace>/<task_id>/outputs/<run_id>' string."""
        from insar_agent.mcp.server import insar_run_mintpy

        # Create a minimal dir structure so input validation passes
        mintpy_dir = tmp_path / "mintpy"
        mintpy_dir.mkdir()
        dem = tmp_path / "dem.tif"
        dem.write_bytes(b"fake")

        def fake_run_mintpy(**kwargs):
            return self._make_fake_mintpy_result("job-i1-1", mintpy_dir)

        with patch("insar_agent.mcp.server.run_mintpy", side_effect=fake_run_mintpy):
            result = insar_run_mintpy(
                mintpy_work_dir=str(mintpy_dir),
                gunw_glob=str(tmp_path / "*.h5"),
                dem_path=str(dem),
                conda_env="mintpy",
            )

        assert "error" not in result, result
        warning = result.get("layout_warning", "")
        # Stale path string must not appear
        assert "outputs/" not in warning, (
            f"layout_warning still contains stale 'outputs/' segment (I1 not fixed): {warning!r}"
        )
        # If warning is present, it must use new recommendation format
        if warning:
            assert "insar_product" in warning, (
                f"layout_warning does not mention 'insar_product' (I1 recommendation not updated): {warning!r}"
            )

    def test_run_mintpy_isce2_no_depth_math_stale_string(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """I1: insar_run_mintpy_isce2 layout_warning must not contain stale string."""
        from insar_agent.mcp.server import insar_run_mintpy_isce2

        mintpy_dir = tmp_path / "mintpy"
        mintpy_dir.mkdir()
        stack_dir = tmp_path / "stack"
        stack_dir.mkdir()

        def fake_run_mintpy_isce2(**kwargs):
            return self._make_fake_mintpy_result("job-i1-2", mintpy_dir)

        with (
            patch("insar_agent.mcp.server.run_mintpy_isce2_stack", side_effect=fake_run_mintpy_isce2),
            patch("insar_agent.mcp.server._validate_same_opencode_session_workspace", return_value=None),
        ):
            result = insar_run_mintpy_isce2(
                mintpy_work_dir=str(mintpy_dir),
                stack_work_dir=str(stack_dir),
            )

        assert "error" not in result, result
        warning = result.get("layout_warning", "")
        assert "outputs/" not in warning, (
            f"insar_run_mintpy_isce2 layout_warning still contains stale 'outputs/' (I1 not fixed): {warning!r}"
        )
        if warning:
            assert "insar_product" in warning, (
                f"insar_run_mintpy_isce2 warning does not mention 'insar_product': {warning!r}"
            )


# ---------------------------------------------------------------------------
# I3 — insar_list_outputs scoped to run root, not all-runs output_root
# ---------------------------------------------------------------------------

class TestListOutputsRunScope:
    """I3: legacy globs must scan run_root/merged (ISCE2) and insar_product/*.h5 (ISCE3)."""

    def _make_project_with_job(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        engine: str,
        workflow: str,
    ):
        project_id, output_root = _make_project(
            tmp_path, monkeypatch, engine=engine, workflow=workflow
        )
        # Run the workflow minimally to produce a job so _make_done_job logic works
        from insar_agent.core.project import Project
        from insar_agent.core.jobs import Job
        project = Project.load(project_id)
        job = Job(project_id=project_id, engine=engine, workflow=workflow, status="done")
        job.save(project.jobs_dir())
        return project_id, project, job.job_id

    def test_isce3_glob_scoped_to_run_insar_product(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """I3: ISCE3 .h5 glob must find files in run_root/insar_product/ not output_root."""
        project_id, project, job_id = self._make_project_with_job(
            tmp_path, monkeypatch, "isce3", "insar"
        )
        from insar_agent.core.layout import RunLayout

        layout = RunLayout(project.output_root, project.task, project.run_id)
        insar_product_dir = layout.insar_product_dir
        insar_product_dir.mkdir(parents=True, exist_ok=True)
        # Place .h5 in insar_product/ (new correct location)
        h5_product = insar_product_dir / "GUNW_product.h5"
        h5_product.write_bytes(b"fake")

        result = insar_list_outputs(job_id=job_id, project_id=project_id)
        assert "error" not in result, result
        paths = {item["path"] for item in result["outputs"]}
        assert str(h5_product) in paths, (
            f"ISCE3 .h5 in insar_product/ not found — I3 glob still too broad or wrong dir"
        )

    def test_isce2_merged_scoped_to_run_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """I3: ISCE2 merged/ dirs must be searched under run_root/, not output_root/."""
        project_id, project, job_id = self._make_project_with_job(
            tmp_path, monkeypatch, "isce2", "tops"
        )
        from insar_agent.core.layout import RunLayout

        layout = RunLayout(project.output_root, project.task, project.run_id)
        merged_dir = layout.run_root / "merged"
        merged_dir.mkdir(parents=True, exist_ok=True)
        geo_file = merged_dir / "filt_topophase.unw.geo"
        geo_file.write_bytes(b"fake")

        result = insar_list_outputs(job_id=job_id, project_id=project_id)
        assert "error" not in result, result
        paths = {item["path"] for item in result["outputs"]}
        assert str(geo_file) in paths, (
            f"ISCE2 merged artifact in run_root/merged/ not found — I3 scope broken"
        )

    def test_output_root_h5_not_surfaced_for_isce3(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """I3: .h5 files placed directly in output_root must NOT be returned (too broad)."""
        project_id, project, job_id = self._make_project_with_job(
            tmp_path, monkeypatch, "isce3", "insar"
        )
        # Place stray .h5 at output_root level (should NOT be found)
        stray_h5 = Path(project.output_root) / "stray_product.h5"
        stray_h5.write_bytes(b"stray")

        result = insar_list_outputs(job_id=job_id, project_id=project_id)
        assert "error" not in result, result
        paths = {item["path"] for item in result["outputs"]}
        assert str(stray_h5) not in paths, (
            f"Stray .h5 at output_root was returned — I3 scope still too broad (old behavior)"
        )
