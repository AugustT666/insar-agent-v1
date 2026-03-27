"""
End-to-end integration test: real NISAR DInSAR processing via the MCP layer.

Requires:
- NAS mounted at /home/august/NAS/NISAR_wangshuai_data/ with REF/SEC RSLC + DEM
- conda environment 'isce3gpu' with nisar.workflows.insar available

Run with:
    pytest tests/integration/test_real_dinsar.py -v -s --timeout=3600

The test produces a GUNW_product.h5 in a temporary directory and verifies that
key output layers (wrapped phase, coherence, unwrapped phase) are present.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from insar_agent.mcp.server import (
    insar_create_project,
    insar_export_runconfig,
    insar_export_geotiff,
    insar_extract_bbox,
    insar_get_job_logs,
    insar_get_job_status,
    insar_run_workflow,
    insar_set_runconfig_value,
    insar_validate_runconfig,
)

# ── data paths ────────────────────────────────────────────────────────────────

NAS_ROOT = Path("/home/august/NAS/NISAR_wangshuai_data")
REF_RSLC = NAS_ROOT / "NISAR_L1_PR_RSLC_005_172_A_008_2005_DHDH_A_20251122T024618_20251122T024652_X05007_N_F_J_001_cropped.h5"
SEC_RSLC = NAS_ROOT / "NISAR_L1_PR_RSLC_006_172_A_008_2005_DHDH_A_20251204T024618_20251204T024653_X05007_N_F_J_001_cropped.h5"
DEM_FILE = NAS_ROOT / "dem.wgs84"
NAS_GUNW = NAS_ROOT / "insar_out2" / "GUNW_product.h5"
CONDA_ENV = "isce3gpu"

NAS_AVAILABLE = REF_RSLC.exists() and SEC_RSLC.exists() and DEM_FILE.exists()

pytestmark = pytest.mark.skipif(
    not NAS_AVAILABLE,
    reason="NAS data not available; mount /home/august/NAS/NISAR_wangshuai_data/",
)

# ── helpers ───────────────────────────────────────────────────────────────────

POLL_INTERVAL = 30   # seconds between status polls
TIMEOUT = 3600       # 1 hour max


def poll_until_done(job_id: str, project_id: str, timeout: int = TIMEOUT) -> dict:
    """Poll insar_get_job_status until status is done or failed (or timeout)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = insar_get_job_status(job_id, project_id)
        if status["status"] in ("done", "failed"):
            return status
        print(f"  [poll] status={status['status']}  (waiting {POLL_INTERVAL}s)")
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"Job {job_id} did not finish within {timeout}s")


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "registry"))


@pytest.fixture()
def dinsar_project(tmp_path):
    """Create and configure a DInSAR project using NAS data."""
    ws = str(tmp_path / "dinsar_workspace")
    result = insar_create_project(
        engine="isce3",
        workflow="insar",
        workspace_root=ws,
        name="real-dinsar-test",
        conda_env=CONDA_ENV,
    )
    pid = result["project_id"]

    # Create directories that ISCE3 expects to already exist
    for d in ("outputs", "scratch", "logs"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)

    fields = {
        "runconfig.groups.input_file_group.reference_rslc_file": str(REF_RSLC),
        "runconfig.groups.input_file_group.secondary_rslc_file": str(SEC_RSLC),
        "runconfig.groups.dynamic_ancillary_file_group.dem_file": str(DEM_FILE),
        "runconfig.groups.product_path_group.product_path": str(tmp_path / "outputs"),
        "runconfig.groups.product_path_group.scratch_path": str(tmp_path / "scratch"),
        "runconfig.groups.product_path_group.sas_output_file": str(tmp_path / "outputs" / "GUNW_product.h5"),
        "runconfig.groups.logging.path": str(tmp_path / "logs" / "insar.log"),
        "runconfig.groups.worker.gpu_enabled": False,
    }
    for key, val in fields.items():
        r = insar_set_runconfig_value(pid, key, val)
        assert "error" not in r, f"Failed to set {key}: {r}"

    return pid


# ── pre-execution checks ──────────────────────────────────────────────────────

def test_runconfig_validates_with_real_paths(dinsar_project):
    """Runconfig must pass validation before we attempt to launch."""
    result = insar_validate_runconfig(dinsar_project)
    assert result["valid"] is True, f"Validation errors: {result['errors']}"


def test_export_produces_yaml(dinsar_project, tmp_path):
    """Export must write a parseable YAML referencing the NAS files."""
    import yaml
    result = insar_export_runconfig(dinsar_project)
    yaml_path = Path(result["yaml_path"])
    assert yaml_path.exists()
    content = yaml.safe_load(yaml_path.read_text())
    ref = content["runconfig"]["groups"]["input_file_group"]["reference_rslc_file"]
    assert str(REF_RSLC) in ref


def test_dry_run_command_targets_isce3gpu(dinsar_project):
    """Dry-run command must reference the isce3gpu conda env and insar workflow."""
    insar_export_runconfig(dinsar_project)
    result = insar_run_workflow(dinsar_project, dry_run=True)
    assert result["dry_run"] is True
    cmd = result["command"]
    assert CONDA_ENV in cmd
    assert any("nisar.workflows.insar" in c for c in cmd)


# ── real execution ────────────────────────────────────────────────────────────

def test_full_dinsar_produces_gunw(dinsar_project, tmp_path):
    """
    Run the full DInSAR workflow and verify the GUNW output.

    This test launches ISCE3 via conda run, polls until completion,
    and checks that GUNW_product.h5 exists and is non-empty.
    """
    insar_export_runconfig(dinsar_project)

    launch = insar_run_workflow(dinsar_project, dry_run=False)
    assert "error" not in launch, f"Launch failed: {launch}"
    job_id = launch["job_id"]
    pid = launch["pid"]
    print(f"\n  Launched job {job_id} (PID {pid})")
    print(f"  Log: {launch['log_path']}")

    # Poll until done or failed
    final = poll_until_done(job_id, dinsar_project)
    print(f"  Final status: {final['status']}  exit_code={final['exit_code']}")

    if final["status"] == "failed":
        logs = insar_get_job_logs(job_id, dinsar_project, tail=50)
        print("\n  === last 50 log lines ===")
        print(logs.get("content", "(no log)"))
        pytest.fail(f"ISCE3 workflow failed. See log above.")

    # Verify GUNW output
    gunw = tmp_path / "outputs" / "GUNW_product.h5"
    assert gunw.exists(), f"GUNW_product.h5 not found at {gunw}"
    assert gunw.stat().st_size > 1_000_000, "GUNW file too small — likely empty/corrupt"
    print(f"  GUNW size: {gunw.stat().st_size / 1e6:.1f} MB")

    # Verify core HDF5 datasets
    h5py = pytest.importorskip("h5py", reason="h5py required for HDF5 inspection")
    EXPECTED = [
        "science/LSAR/GUNW/grids/frequencyA/wrappedInterferogram/HH/wrappedInterferogram",
        "science/LSAR/GUNW/grids/frequencyA/wrappedInterferogram/HH/coherenceMagnitude",
        "science/LSAR/GUNW/grids/frequencyA/unwrappedInterferogram/HH/unwrappedPhase",
        "science/LSAR/GUNW/grids/frequencyA/unwrappedInterferogram/HH/coherenceMagnitude",
    ]
    with h5py.File(gunw, "r") as f:
        for path in EXPECTED:
            assert path in f, f"Missing HDF5 dataset: {path}"
    print(f"  All {len(EXPECTED)} expected HDF5 datasets present.")


# ── M5 utilities: bbox + geotiff ──────────────────────────────────────────────

def test_extract_bbox_real_rslcs():
    """insar_extract_bbox must return a valid union bounding box for the two NAS RSLCs."""
    result = insar_extract_bbox(rslc_paths=[str(REF_RSLC), str(SEC_RSLC)])
    assert "error" not in result, f"Unexpected error: {result}"
    assert result["min_lon"] < result["max_lon"], "min_lon must be less than max_lon"
    assert result["min_lat"] < result["max_lat"], "min_lat must be less than max_lat"
    # Area is in Ethiopia / Horn of Africa (~40–42°E, 13–15°N)
    assert 30 < result["min_lon"] < 50, f"Unexpected longitude: {result['min_lon']}"
    assert 10 < result["min_lat"] < 20, f"Unexpected latitude: {result['min_lat']}"
    print(f"  BBox: lon [{result['min_lon']:.3f}, {result['max_lon']:.3f}]  "
          f"lat [{result['min_lat']:.3f}, {result['max_lat']:.3f}]")


def test_export_geotiff_real_gunw(tmp_path):
    """insar_export_geotiff must produce GeoTIFF and PNG files from a real GUNW product."""
    if not NAS_GUNW.exists():
        pytest.skip(f"NAS GUNW not available: {NAS_GUNW}")

    result = insar_export_geotiff(h5_path=str(NAS_GUNW), output_dir=str(tmp_path))
    assert "error" not in result, f"Unexpected error: {result}"

    tifs = list(tmp_path.rglob("*.tif"))
    pngs = list(tmp_path.rglob("*.png"))
    assert len(tifs) > 0, "No GeoTIFF files produced"
    assert len(pngs) > 0, "No PNG preview files produced"
    print(f"  GeoTIFFs: {len(tifs)}  PNGs: {len(pngs)}")
