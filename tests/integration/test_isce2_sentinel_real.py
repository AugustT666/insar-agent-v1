"""
Real-data integration tests for Sentinel-1 / ISCE2 D-InSAR workflow.

These tests use actual Sentinel-1 SAFE ZIP files to validate end-to-end
InSAR processing with ISCE2 (topsApp.py).

Marker: @pytest.mark.real_data
Status: Scaffold ready; awaiting real Sentinel-1 test dataset
Path to test data: /home/august/NAS/Sentinel1_data/ (to be created)
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

# Import the MCP tool functions
from insar_agent.mcp.server import (
    insar_create_project,
    insar_get_job,
    insar_list_outputs,
    insar_prepare_sentinel_data,
    insar_run_workflow,
    insar_set_processing_param,
)


@pytest.mark.real_data
class TestSentinel1DInSARRealData:
    """
    Real-data test suite for Sentinel-1 D-InSAR with ISCE2.

    Prerequisites:
    1. ISCE2 environment installed and working:
       conda activate isce2
       python -c "import isce2; print(isce2.__version__)"

    2. Two ascending Sentinel-1 SAFE ZIP files with:
       - Same relative orbit (track)
       - Temporal baseline 6–48 days
       - Located at: /home/august/NAS/Sentinel1_data/
       - Example: S1A_IW_SLC__1SDV_<date1>_..._<orbitnum>_*.zip
                  S1A_IW_SLC__1SDV_<date2>_..._<orbitnum>_*.zip

    3. POEORB orbit files (optional; can be auto-downloaded):
       Located in: /home/august/NAS/Sentinel1_data/orbits/

    4. DEM GeoTIFF covering the AOI (optional; can be auto-downloaded):
       Copernicus 30m recommended: /home/august/NAS/Sentinel1_data/dem/

    Test Coverage:
    - Data preparation (SAFE linking, orbit download, DEM crop)
    - Project creation with ISCE2 engine
    - Parameter validation
    - topsApp.py execution
    - Output verification (interferogram, coherence, unwrapped phase)
    """

    @pytest.fixture
    def sentinel_test_dir(self) -> Path:
        """Return path to Sentinel-1 test data directory."""
        test_dir = Path("/home/august/NAS/Sentinel1_data")
        return test_dir

    @pytest.fixture
    def workspace_root(self, tmp_path: Path) -> Path:
        """Create temporary workspace for ISCE2 processing."""
        workspace = tmp_path / "isce2_workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace

    def find_sentinel_pair(
        self, sentinel_dir: Path
    ) -> tuple[Path, Path] | None:
        """
        Search for a valid Sentinel-1 SAFE pair in the test directory.

        Returns:
            Tuple of (reference_path, secondary_path) sorted by acquisition date,
            or None if not enough valid SAFE files found.
        """
        if not sentinel_dir.exists():
            pytest.skip(
                f"Sentinel-1 test data not found at {sentinel_dir}. "
                "Set up test data to enable real-data tests."
            )

        # Find all SAFE ZIP files
        safe_files = sorted(sentinel_dir.glob("**/S1?_IW_SLC__1S*_[0-9]*.zip"))

        if len(safe_files) < 2:
            pytest.skip(
                f"Need at least 2 Sentinel-1 SAFE files; found {len(safe_files)}. "
                f"Download scenes from ASF Vertex and place in {sentinel_dir}/"
            )

        # TODO: Validate that pair is from same relative orbit
        # For now, just use first two files
        return (safe_files[0], safe_files[1])

    @pytest.mark.timeout(3600)  # 1 hour max for full workflow
    def test_sentinel_data_preparation(
        self, sentinel_test_dir: Path, workspace_root: Path
    ) -> None:
        """
        Test Step 1: Data preparation (SAFE linking, orbit download).

        This test validates:
        - SAFE ZIP parsing and linking to track-based directories
        - Orbit file download (with auto-retry on transient failures)
        - DEM download or validation (optional)
        """
        pair = self.find_sentinel_pair(sentinel_test_dir)
        if pair is None:
            pytest.skip("No valid Sentinel pair found")

        reference_path, secondary_path = pair

        # Prepare Sentinel data with orbit download
        result = insar_prepare_sentinel_data(
            project_root=str(workspace_root),
            source_paths=[str(reference_path), str(secondary_path)],
            download_dem=False,  # Optional; requires DEM downloader callback
            download_orbits=True,  # Enable auto-retry orbit download
            orbit_dir=str(workspace_root / "orbits"),
        )

        # Validate preparation result
        assert "error" not in result, result.get("error", "")
        assert result["scene_count"] == 2, f"Expected 2 scenes, got {result['scene_count']}"
        assert (
            len(result["grouped_safe_paths"]) >= 1
        ), "No grouped SAFE paths found"
        assert result["orbit_downloaded_count"] > 0, "No orbits downloaded"

        # Verify orbit directory has EOF files
        orbit_dir = Path(result["orbit_dir"])
        eof_files = list(orbit_dir.glob("*.EOF"))
        assert len(eof_files) >= 2, f"Expected >= 2 orbit files, got {len(eof_files)}"

    @pytest.mark.timeout(3600)
    def test_sentinel_project_creation_and_parameters(
        self, sentinel_test_dir: Path, workspace_root: Path
    ) -> None:
        """
        Test Step 2–5: Project creation and parameter setting.

        This test validates:
        - Project creation with ISCE2 engine
        - Required field identification
        - Parameter validation
        - XML generation (checked indirectly in next test)
        """
        pair = self.find_sentinel_pair(sentinel_test_dir)
        if pair is None:
            pytest.skip("No valid Sentinel pair found")

        reference_path, secondary_path = pair

        # Prepare data first
        prep_result = insar_prepare_sentinel_data(
            project_root=str(workspace_root),
            source_paths=[str(reference_path), str(secondary_path)],
            download_dem=False,
            download_orbits=True,
            orbit_dir=str(workspace_root / "orbits"),
        )

        grouped_safe = prep_result["grouped_safe_paths"]
        track_dir = list(grouped_safe.keys())[0]
        safe_list = grouped_safe[track_dir]

        # Create project
        project = insar_create_project(
            engine="isce2",
            workflow="tops",
            workspace_root=str(workspace_root),
            name="sentinel_s1_dinsar_real_test",
            conda_env="isce2",
        )

        assert "project_id" in project, project
        project_id = project["project_id"]
        assert "required_fields" in project
        assert "reference_safe" in project["required_fields"]
        assert "secondary_safe" in project["required_fields"]

        # Set required parameters
        insar_set_processing_param(
            project_id=project_id,
            key="reference_safe",
            value=safe_list[0],
            justification="reference scene from pair",
        )
        insar_set_processing_param(
            project_id=project_id,
            key="secondary_safe",
            value=safe_list[1],
            justification="secondary scene from pair",
        )
        insar_set_processing_param(
            project_id=project_id,
            key="orbit_dir",
            value=prep_result["orbit_dir"],
            justification="orbits prepared by data-prep-sentinel",
        )

        # DEM is optional; use a prepared one if available
        if prep_result.get("dem_path"):
            insar_set_processing_param(
                project_id=project_id,
                key="dem_file",
                value=prep_result["dem_path"],
                justification="DEM from data-prep-sentinel",
            )

    @pytest.mark.timeout(7200)  # 2 hours for full processing
    def test_sentinel_full_workflow_d_insar(
        self, sentinel_test_dir: Path, workspace_root: Path
    ) -> None:
        """
        Test Steps 6–8: Full workflow execution and output validation.

        This is the comprehensive end-to-end test:
        - Project creation
        - Parameter setting
        - topsApp.py execution
        - Job monitoring (polling)
        - Output validation (interferogram, coherence, unwrapped phase)

        Runtime: 30–120 minutes depending on scene size.
        """
        pair = self.find_sentinel_pair(sentinel_test_dir)
        if pair is None:
            pytest.skip("No valid Sentinel pair found")

        reference_path, secondary_path = pair

        # Step 1: Prepare data
        prep_result = insar_prepare_sentinel_data(
            project_root=str(workspace_root),
            source_paths=[str(reference_path), str(secondary_path)],
            download_dem=False,
            download_orbits=True,
            orbit_dir=str(workspace_root / "orbits"),
        )

        grouped_safe = prep_result["grouped_safe_paths"]
        track_dir = list(grouped_safe.keys())[0]
        safe_list = grouped_safe[track_dir]

        # Step 2: Create project
        project = insar_create_project(
            engine="isce2",
            workflow="tops",
            workspace_root=str(workspace_root),
            name="sentinel_s1_dinsar_full_test",
            conda_env="isce2",
        )
        project_id = project["project_id"]

        # Step 3: Set parameters
        insar_set_processing_param(
            project_id=project_id,
            key="reference_safe",
            value=safe_list[0],
            justification="reference",
        )
        insar_set_processing_param(
            project_id=project_id,
            key="secondary_safe",
            value=safe_list[1],
            justification="secondary",
        )
        insar_set_processing_param(
            project_id=project_id,
            key="orbit_dir",
            value=prep_result["orbit_dir"],
            justification="orbits",
        )

        # Step 4: Run workflow
        job = insar_run_workflow(project_id=project_id)
        assert "job_id" in job, job
        assert "log_path" in job
        job_id = job["job_id"]

        log_path = Path(job["log_path"])
        assert log_path.parent.exists(), f"Log directory does not exist: {log_path.parent}"

        # Step 5: Monitor job with polling
        start_time = time.time()
        max_wait = 7200  # 2 hours
        poll_interval = 30  # 30 seconds

        while time.time() - start_time < max_wait:
            job_status = insar_get_job(job_id=job_id, project_id=project_id)

            status = job_status.get("status", "unknown")
            if status in {"completed", "failed"}:
                break

            # Log progress
            if "percent_complete" in job_status:
                print(f"  Progress: {job_status['percent_complete']}%")

            time.sleep(poll_interval)

        # Validate job completion
        assert job_status["status"] == "completed", (
            f"Job did not complete. Status: {job_status['status']}. "
            f"Check logs at: {log_path}"
        )

        # Step 6: Validate outputs
        outputs = insar_list_outputs(project_id=project_id)
        assert len(outputs) > 0, f"No outputs generated. Check {log_path}"

        # Verify key output files exist
        workspace = Path(workspace_root)
        expected_files = [
            workspace / "merged" / "filt_topophase.unw.geo",
            workspace / "merged" / "phsig.cor.geo",
        ]

        for expected_file in expected_files:
            assert expected_file.exists(), (
                f"Expected output not found: {expected_file}. "
                f"Check {log_path} for processing errors."
            )

        print(f"\n✓ Full workflow completed successfully")
        print(f"  Interferogram: {workspace / 'merged' / 'filt_topophase.unw.geo'}")
        print(f"  Coherence: {workspace / 'merged' / 'phsig.cor.geo'}")


@pytest.mark.real_data
def test_sentinel_data_setup_instructions() -> None:
    """
    Print instructions for setting up Sentinel-1 real-data tests.

    This test always passes but prints setup guidance.
    """
    instructions = """
    ╔══════════════════════════════════════════════════════════════════════╗
    ║  Sentinel-1 Real-Data Test Setup Instructions                       ║
    ╚══════════════════════════════════════════════════════════════════════╝

    To enable real-data tests for Sentinel-1 / ISCE2, follow these steps:

    1. Download Sentinel-1 SAFE ZIP files from ASF Vertex:
       - Login: https://vertex.daac.asf.alaska.edu/
       - Select 2 ascending Sentinel-1A/B scenes from the same track (relative orbit)
       - Temporal baseline: 6–48 days recommended
       - Download as ZIP format

    2. Create test data directory:
       mkdir -p /home/august/NAS/Sentinel1_data/

    3. Place SAFE ZIP files in the test directory:
       cp S1A_IW_SLC__1SDV_<date1>_...zip /home/august/NAS/Sentinel1_data/
       cp S1A_IW_SLC__1SDV_<date2>_...zip /home/august/NAS/Sentinel1_data/

    4. (Optional) Pre-download POEORB orbit files:
       mkdir -p /home/august/NAS/Sentinel1_data/orbits/
       # fetchOrbit.py will auto-download if this is empty

    5. (Optional) Prepare DEM:
       mkdir -p /home/august/NAS/Sentinel1_data/dem/
       # Copy or download Copernicus 30m DEM to this directory

    6. Run real-data tests:
       pytest tests/integration/test_isce2_sentinel_real.py -m real_data -v --timeout=7200

    ════════════════════════════════════════════════════════════════════════

    Expected test runtime (per test):
      - test_sentinel_data_preparation: 5–15 min (orbit download + prep)
      - test_sentinel_project_creation_and_parameters: 1–2 min
      - test_sentinel_full_workflow_d_insar: 30–120 min (topsApp.py)

    Total: ~2 hours for full suite

    Log files will be written to:
      <workspace>/. insar_logs/isce2_*.log
      <workspace>/.insar_logs/sentinel_orbit_*.log
      <workspace>/.insar_logs/sentinel_prep_*.log
    """
    print(instructions)
    assert True  # Always pass


if __name__ == "__main__":
    # Print setup instructions when run directly
    test_sentinel_data_setup_instructions()
