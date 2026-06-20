"""Task 4.4 TDD tests: Layer-1 progress marker emission.

Tests:
1. prepare_sentinel_data emits SYNTHESIZE/DEM/ORBIT markers to progress.log
2. End-to-end: insar_get_job returns progress field for data-prep/DownloadJob branch
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from insar_agent.core.progress import append_progress, read_progress_tail


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Create a minimal project, returning project_id and run_root."""
    from insar_agent.mcp.server import insar_create_project
    registry_dir = tmp_path / ".registry"
    registry_dir.mkdir()
    monkeypatch.setenv("XDG_DATA_HOME", str(registry_dir))
    output_root = tmp_path / "output"
    result = insar_create_project(
        engine="isce3",
        workflow="insar",
        workspace_root=str(output_root),
    )
    assert "error" not in result, result
    return result["project_id"], output_root


def _minimal_scene_meta() -> dict:
    return {
        "satellite": "S1A",
        "pass_direction": "ASCENDING",
        "relative_orbit": 14,
        "absolute_orbit": None,
        "mode": "IW",
        "polarizations": ["VV"],
        "bbox": [37.0, 11.0, 39.0, 13.0],
        "start_time": None,
        "stop_time": None,
    }


# ---------------------------------------------------------------------------
# Test 1: prepare_sentinel_data emits SYNTHESIZE/DEM/ORBIT markers
# ---------------------------------------------------------------------------

class TestPrepareSentinelEmitsProgress:
    """prepare_sentinel_data should call append_progress at key steps."""

    def test_synthesize_emits_progress(self, tmp_path: Path):
        """SYNTHESIZE step should write a progress entry when burst sources are processed."""
        from insar_agent.engines.isce2.sentinel.prepare import prepare_sentinel_data

        run_root = tmp_path / "run"
        project_root = run_root / "prepare"
        project_root.mkdir(parents=True)
        # Create .insar_agent marker so infer_run_root finds run_root
        (run_root / ".insar_agent").mkdir()

        scene_id = "S1A_IW_SLC__1SDV_20230101T000000_20230101T000023_046001_058001_ABCD"
        # Create a minimal burst XML that burst_assembly can discover
        burst_dir = tmp_path / "bursts" / scene_id
        burst_dir.mkdir(parents=True)
        xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<burst>
  <scene_id>{scene_id}</scene_id>
  <subswath>IW1</subswath>
  <burst_index>1</burst_index>
  <satellite>S1A</satellite>
  <mode>IW</mode>
  <pass_direction>ASCENDING</pass_direction>
  <relative_orbit>14</relative_orbit>
  <bbox>37.0 11.0 39.0 13.0</bbox>
  <start_time>2023-01-01T00:00:00</start_time>
  <stop_time>2023-01-01T00:00:23</stop_time>
  <polarization>VV</polarization>
  <lines>1500</lines>
  <samples>25000</samples>
</burst>
"""
        (burst_dir / f"{scene_id}_IW1_VV_burst_001.xml").write_text(xml_content)
        tiff = burst_dir / f"{scene_id}_IW1_VV_burst_001.tiff"
        tiff.write_bytes(b"fake")

        progress_calls: list[tuple] = []

        # Monkeypatch append_progress inside prepare module.
        # We route a source_path through burst_source_paths by patching
        # _collect_burst_source_files to return burst files for our source dir.
        fake_burst_files = [tiff, burst_dir / f"{scene_id}_IW1_VV_burst_001.xml"]
        with patch("insar_agent.engines.isce2.sentinel.prepare.append_progress",
                   side_effect=lambda rr, msg, **kw: progress_calls.append((str(rr), msg))):
            with patch("insar_agent.engines.isce2.sentinel.prepare._collect_burst_source_files",
                       return_value=fake_burst_files):
                with patch("insar_agent.engines.isce2.sentinel.prepare._find_scene_id_from_path",
                           return_value=scene_id):
                    with patch("insar_agent.engines.isce2.sentinel.prepare._extract_manifest_from_burst_sources",
                               return_value=(burst_dir / f"{scene_id}_IW1_VV_burst_001.xml",
                                             b"<manifest/>")):
                        with patch("insar_agent.engines.isce2.sentinel.prepare._parse_manifest_bytes",
                                   return_value=_minimal_scene_meta()):
                            with patch("insar_agent.engines.isce2.sentinel.prepare._to_isce2_manifest_bytes",
                                       return_value=b"<manifest/>"):
                                with patch("insar_agent.engines.isce2.sentinel.prepare._ensure_preview_overlay"):
                                    with patch("insar_agent.engines.isce2.sentinel.prepare._synthesize_annotation_and_measurement"):
                                        with patch("insar_agent.engines.isce2.sentinel.prepare._validate_safe_annotation_geolocation"):
                                            with patch("insar_agent.engines.isce2.sentinel.prepare._link_burst_sources"):
                                                # Pass the burst dir as a source path so
                                                # _collect_burst_source_files is invoked
                                                prepare_sentinel_data(
                                                    project_root=str(project_root),
                                                    source_paths=[str(burst_dir)],
                                                    burst_manifest=None,
                                                    resume=True,
                                                )
        # Should have called append_progress with SYNTHESIZE
        synthesize_calls = [msg for _, msg in progress_calls if "SYNTHESIZE" in msg.upper()]
        assert synthesize_calls, (
            f"Expected append_progress to be called with a SYNTHESIZE message, "
            f"but got: {progress_calls}"
        )

    def test_dem_emits_progress(self, tmp_path: Path):
        """DEM download/resolution step should write a progress entry."""
        from insar_agent.engines.isce2.sentinel.prepare import prepare_sentinel_data

        run_root = tmp_path / "run"
        project_root = run_root / "prepare"
        project_root.mkdir(parents=True)
        (run_root / ".insar_agent").mkdir()

        # Provide an existing DEM
        dem_file = tmp_path / "dem.tif"
        dem_file.write_bytes(b"fake dem")

        progress_calls: list[tuple] = []
        with patch("insar_agent.engines.isce2.sentinel.prepare.append_progress",
                   side_effect=lambda rr, msg, **kw: progress_calls.append((str(rr), msg))):
            prepare_sentinel_data(
                project_root=str(project_root),
                source_paths=[],
                dem_path=str(dem_file),
                resume=True,
            )

        dem_calls = [msg for _, msg in progress_calls if "DEM" in msg.upper()]
        assert dem_calls, (
            f"Expected append_progress called with a DEM message, got: {progress_calls}"
        )

    def test_orbit_emits_progress(self, tmp_path: Path):
        """ORBIT download step should write a progress entry."""
        from insar_agent.engines.isce2.sentinel.prepare import prepare_sentinel_data
        from insar_agent.engines.isce2.sentinel import orbit as orbit_module

        run_root = tmp_path / "run"
        project_root = run_root / "prepare"
        project_root.mkdir(parents=True)
        (run_root / ".insar_agent").mkdir()
        orbit_dir = tmp_path / "orbits"
        orbit_dir.mkdir()

        progress_calls: list[tuple] = []
        with patch("insar_agent.engines.isce2.sentinel.prepare.append_progress",
                   side_effect=lambda rr, msg, **kw: progress_calls.append((str(rr), msg))):
            with patch("insar_agent.engines.isce2.sentinel.prepare.orbit._resolve_orbit_token_file",
                       return_value=None):
                with patch("insar_agent.engines.isce2.sentinel.prepare.orbit._download_orbits_for_scenes",
                           return_value=(0, [])):
                    prepare_sentinel_data(
                        project_root=str(project_root),
                        source_paths=[],
                        download_orbits=True,
                        orbit_dir=str(orbit_dir),
                        resume=True,
                    )

        orbit_calls = [msg for _, msg in progress_calls if "ORBIT" in msg.upper()]
        assert orbit_calls, (
            f"Expected append_progress called with an ORBIT message, got: {progress_calls}"
        )


# ---------------------------------------------------------------------------
# Test 2: End-to-end get_job surfaces progress for data-prep/DownloadJob branch
# This MUST FAIL before the get_job extension in job_tools.py
# ---------------------------------------------------------------------------

class TestGetJobSurfacesProgressForDataPrep:
    """insar_get_job should return progress field for data-prep DownloadJob."""

    def _make_fake_download_job(self, tmp_path: Path, project_id: str, jobs_dir: Path,
                                 run_root: Path) -> str:
        """Create a DownloadJob JSON and write progress lines to run_root."""
        from insar_agent.core.jobs import DownloadJob
        job = DownloadJob(
            output_dir=str(tmp_path / "output"),
            n_files=3,
            task_id="test-task",
            run_id="run001",
            run_root=str(run_root),
            tool_name="insar_prepare_sentinel_data",
            job_type="sentinel_prepare",
        )
        job.status = "running"
        job.pid = None  # treat as zombie — liveness check will mark done
        job.save(jobs_dir)
        return job.job_id

    def test_get_job_returns_progress_for_download_job(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """After emitter wiring, get_job must return progress for DownloadJob."""
        from insar_agent.mcp.server import insar_create_project
        from insar_agent.mcp.tools.job_tools import insar_get_job

        registry_dir = tmp_path / ".registry"
        registry_dir.mkdir()
        monkeypatch.setenv("XDG_DATA_HOME", str(registry_dir))

        output_root = tmp_path / "output"
        result = insar_create_project(
            engine="isce3",
            workflow="insar",
            workspace_root=str(output_root),
        )
        assert "error" not in result, result
        project_id = result["project_id"]

        from insar_agent.core.project import Project
        project = Project.load(project_id)
        run_root = project.run_root()
        jobs_dir = project.jobs_dir()
        run_root.mkdir(parents=True, exist_ok=True)
        jobs_dir.mkdir(parents=True, exist_ok=True)

        # Write synthetic progress lines (as if emitter ran)
        append_progress(run_root, "SYNTHESIZE S1A_scene_001 -> safe/", step=1, total=5)
        append_progress(run_root, "DEM downloaded /path/to/dem.tif")
        append_progress(run_root, "ORBIT dir=/orbits downloaded=17 failed=0")

        job_id = self._make_fake_download_job(tmp_path, project_id, jobs_dir, run_root)

        # Mock liveness check so job looks finished (pid=None triggers zombie path)
        get_result = insar_get_job(project_id=project_id, job_id=job_id)

        # The progress field must exist and contain the emitted lines
        assert "progress" in get_result, (
            f"Expected 'progress' key in insar_get_job result for DownloadJob, "
            f"got keys: {list(get_result.keys())}"
        )
        progress_text = get_result["progress"]
        assert "SYNTHESIZE" in progress_text, f"Expected SYNTHESIZE in progress: {progress_text!r}"
        assert "DEM" in progress_text, f"Expected DEM in progress: {progress_text!r}"
        assert "ORBIT" in progress_text, f"Expected ORBIT in progress: {progress_text!r}"

    def test_get_job_progress_degrades_gracefully_when_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """When no progress.log exists, get_job returns empty string for progress."""
        from insar_agent.mcp.server import insar_create_project
        from insar_agent.mcp.tools.job_tools import insar_get_job

        registry_dir = tmp_path / ".registry"
        registry_dir.mkdir()
        monkeypatch.setenv("XDG_DATA_HOME", str(registry_dir))

        output_root = tmp_path / "output"
        result = insar_create_project(
            engine="isce3",
            workflow="insar",
            workspace_root=str(output_root),
        )
        assert "error" not in result, result
        project_id = result["project_id"]

        from insar_agent.core.project import Project
        from insar_agent.core.jobs import DownloadJob

        project = Project.load(project_id)
        run_root = project.run_root()
        jobs_dir = project.jobs_dir()
        run_root.mkdir(parents=True, exist_ok=True)
        jobs_dir.mkdir(parents=True, exist_ok=True)

        # No progress.log written — graceful degradation
        job = DownloadJob(
            output_dir=str(tmp_path / "output"),
            n_files=1,
            task_id="test-task",
            run_id="run001",
            run_root=str(run_root),
            tool_name="insar_prepare_sentinel_data",
            job_type="sentinel_prepare",
        )
        job.status = "done"
        job.pid = None
        job.save(jobs_dir)

        get_result = insar_get_job(project_id=project_id, job_id=job.job_id)

        assert "progress" in get_result, (
            f"Expected 'progress' key even when no log exists, got: {list(get_result.keys())}"
        )
        assert get_result["progress"] == "", (
            f"Expected empty string when no progress.log, got: {get_result['progress']!r}"
        )
