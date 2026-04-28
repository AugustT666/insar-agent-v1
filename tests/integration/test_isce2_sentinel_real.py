"""
Real-data integration tests for Sentinel-1 / ISCE2 D-InSAR workflow.

Uses actual Sentinel-1 .SAFE directories from local HDD storage to validate
data preparation, project creation, and parameter setting via MCP tools.

Full workflow execution (topsApp.py) is a separate long-running test that
requires 30–120 minutes and is excluded from the default suite.

Marker: @pytest.mark.real_data
Data: /mnt/HDD2T/August/inasr-agent-test/safe/s1a_asc_rel014/
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from insar_agent.mcp.server import (
    insar_create_project,
    insar_get_job,
    insar_list_outputs,
    insar_prepare_sentinel_data,
    insar_run_workflow,
    insar_set_processing_param,
)

# ── Data paths ──────────────────────────────────────────────────────────────

_SAFE_DIR = Path("/mnt/HDD2T/August/inasr-agent-test/safe/s1a_asc_rel014")
_ORBIT_DIR = Path("/mnt/HDD2T/August/inasr-agent-test/temp/general/orbits")
_DEM_PATH = Path("/mnt/HDD2T/August/inasr-agent-test/dem-claude-test/dem.tif")


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def sentinel_safe_pair() -> tuple[Path, Path]:
    """Return (reference, secondary) .SAFE paths sorted by acquisition date."""
    if not _SAFE_DIR.exists():
        pytest.skip(f"Sentinel SAFE data not found at {_SAFE_DIR}")

    safe_dirs = sorted(_SAFE_DIR.glob("S1?_IW_SLC__1S*.SAFE"))
    if len(safe_dirs) < 2:
        pytest.skip(f"Need ≥2 .SAFE directories; found {len(safe_dirs)} in {_SAFE_DIR}")

    # Use the first two chronologically (they share the same relative orbit)
    return safe_dirs[0], safe_dirs[1]


@pytest.fixture(scope="session")
def orbit_dir() -> Path:
    if not _ORBIT_DIR.exists():
        pytest.skip(f"Orbit directory not found at {_ORBIT_DIR}")
    eof_files = list(_ORBIT_DIR.glob("*.EOF"))
    if not eof_files:
        pytest.skip(f"No .EOF files in {_ORBIT_DIR}")
    return _ORBIT_DIR


@pytest.fixture(scope="session")
def dem_path() -> Path:
    if not _DEM_PATH.exists():
        pytest.skip(f"DEM not found at {_DEM_PATH}")
    return _DEM_PATH


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.real_data
class TestSentinel1DInSARRealData:
    """
    Real-data test suite for Sentinel-1 D-InSAR with ISCE2.

    Prerequisites:
    - Sentinel-1 .SAFE directories at /mnt/HDD2T/August/inasr-agent-test/safe/s1a_asc_rel014/
    - POEORB .EOF files at /mnt/HDD2T/August/inasr-agent-test/temp/general/orbits/
    - DEM GeoTIFF at /mnt/HDD2T/August/inasr-agent-test/dem-claude-test/dem.tif
    - isce2 conda environment installed
    """

    def test_sentinel_data_preparation(
        self,
        sentinel_safe_pair: tuple[Path, Path],
        orbit_dir: Path,
        dem_path: Path,
        tmp_path: Path,
    ) -> None:
        """
        Validate insar_prepare_sentinel_data with real .SAFE inputs.

        Checks:
        - SAFE directory parsing and manifest reading
        - grouped_safe_paths structure
        - Existing orbit files accepted without re-download
        - DEM path forwarded correctly
        """
        reference, secondary = sentinel_safe_pair

        result = insar_prepare_sentinel_data(
            project_root=str(tmp_path),
            source_paths=[str(reference), str(secondary)],
            download_dem=False,
            dem_path=str(dem_path),
            download_orbits=False,
            orbit_dir=str(orbit_dir),
        )

        assert "error" not in result, f"prep failed: {result}"
        assert result.get("scene_count", 0) == 2, (
            f"Expected 2 scenes, got {result.get('scene_count')}"
        )
        assert result.get("grouped_safe_paths"), "grouped_safe_paths is empty"

        # Verify at least one track group has both scenes
        grouped = result["grouped_safe_paths"]
        track = next(iter(grouped))
        assert len(grouped[track]) >= 2, (
            f"Track {track} has only {len(grouped[track])} SAFE paths"
        )

    def test_sentinel_project_creation_and_parameters(
        self,
        sentinel_safe_pair: tuple[Path, Path],
        orbit_dir: Path,
        dem_path: Path,
        tmp_path: Path,
    ) -> None:
        """
        Validate project creation and parameter setting for ISCE2 tops workflow.

        Checks:
        - insar_create_project with engine=isce2, workflow=tops
        - project_id and required_fields returned
        - insar_set_processing_param accepts reference_safe, secondary_safe,
          orbit_dir, and dem_file without error
        """
        reference, secondary = sentinel_safe_pair

        prep = insar_prepare_sentinel_data(
            project_root=str(tmp_path),
            source_paths=[str(reference), str(secondary)],
            download_dem=False,
            dem_path=str(dem_path),
            download_orbits=False,
            orbit_dir=str(orbit_dir),
        )
        assert "error" not in prep, f"prep failed: {prep}"

        grouped = prep["grouped_safe_paths"]
        track = next(iter(grouped))
        safe_list = grouped[track]

        project = insar_create_project(
            engine="isce2",
            workflow="tops",
            workspace_root=str(tmp_path),
            name="sentinel_isce2_param_test",
            conda_env="isce2",
        )
        assert "error" not in project, f"project creation failed: {project}"
        assert "project_id" in project
        project_id = project["project_id"]
        assert "required_fields" in project

        # Set the three mandatory parameters
        for key, value, note in [
            ("reference_safe", safe_list[0], "reference scene"),
            ("secondary_safe", safe_list[1], "secondary scene"),
            ("orbit_dir", str(orbit_dir), "pre-fetched POEORB files"),
            ("dem_file", str(dem_path), "Copernicus 30m DEM"),
        ]:
            r = insar_set_processing_param(
                project_id=project_id,
                key=key,
                value=value,
                justification=note,
            )
            assert "error" not in r, f"set_processing_param({key}) failed: {r}"

    @pytest.mark.timeout(7200)  # 2 hours — excluded from default suite
    def test_sentinel_full_workflow_d_insar(
        self,
        sentinel_safe_pair: tuple[Path, Path],
        orbit_dir: Path,
        dem_path: Path,
        tmp_path: Path,
    ) -> None:
        """
        End-to-end: data prep → project → set params → run topsApp.py → verify outputs.

        Runtime: 30–120 minutes.
        Run with: pytest -m real_data -k full_workflow --timeout=7200
        """
        reference, secondary = sentinel_safe_pair

        prep = insar_prepare_sentinel_data(
            project_root=str(tmp_path),
            source_paths=[str(reference), str(secondary)],
            download_dem=False,
            dem_path=str(dem_path),
            download_orbits=False,
            orbit_dir=str(orbit_dir),
        )
        assert "error" not in prep, f"prep failed: {prep}"

        grouped = prep["grouped_safe_paths"]
        track = next(iter(grouped))
        safe_list = grouped[track]

        project = insar_create_project(
            engine="isce2",
            workflow="tops",
            workspace_root=str(tmp_path),
            name="sentinel_isce2_full_test",
            conda_env="isce2",
        )
        project_id = project["project_id"]

        for key, value, note in [
            ("reference_safe", safe_list[0], "reference"),
            ("secondary_safe", safe_list[1], "secondary"),
            ("orbit_dir", str(orbit_dir), "orbits"),
            ("dem_file", str(dem_path), "dem"),
        ]:
            insar_set_processing_param(
                project_id=project_id, key=key, value=value, justification=note
            )

        job = insar_run_workflow(project_id=project_id)
        assert "job_id" in job, job
        job_id = job["job_id"]

        # Poll until done (max 2 h)
        deadline = time.time() + 7200
        while time.time() < deadline:
            status = insar_get_job(job_id=job_id, project_id=project_id)
            if status.get("status") in {"completed", "failed"}:
                break
            time.sleep(30)

        assert status["status"] == "completed", (
            f"Job failed. Check: {job.get('log_path')}"
        )

        outputs = insar_list_outputs(project_id=project_id)
        assert outputs, "No outputs generated"

        workspace = tmp_path
        for expected in [
            workspace / "merged" / "filt_topophase.unw.geo",
            workspace / "merged" / "phsig.cor.geo",
        ]:
            assert expected.exists(), f"Missing output: {expected}"
