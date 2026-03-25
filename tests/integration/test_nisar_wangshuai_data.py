"""
Integration tests using wangshuai's real NISAR test data on the NAS.

These tests verify that the MCP tools correctly handle real NISAR RSLC files
and produce valid runconfigs ready for ISCE3 execution.

Run only when NAS data is mounted:
    pytest tests/integration/test_nisar_wangshuai_data.py -v

Skip automatically if data is not available.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from insar_agent.mcp.server import (
    insar_create_project,
    insar_export_runconfig,
    insar_run_workflow,
    insar_set_runconfig_value,
    insar_validate_runconfig,
)

# ── data paths (NAS) ──────────────────────────────────────────────────────────

NAS_ROOT = Path("/home/august/NAS/NISAR_wangshuai_data")

REF_RSLC = NAS_ROOT / "NISAR_L1_PR_RSLC_005_172_A_008_2005_DHDH_A_20251122T024618_20251122T024652_X05007_N_F_J_001_cropped.h5"
SEC_RSLC = NAS_ROOT / "NISAR_L1_PR_RSLC_006_172_A_008_2005_DHDH_A_20251204T024618_20251204T024653_X05007_N_F_J_001_cropped.h5"
DEM_FILE = NAS_ROOT / "dem.wgs84"

NAS_AVAILABLE = REF_RSLC.exists() and SEC_RSLC.exists() and DEM_FILE.exists()

pytestmark = pytest.mark.skipif(
    not NAS_AVAILABLE, reason="NAS test data not available at /home/august/NAS/NISAR_wangshuai_data/"
)

# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "registry"))


@pytest.fixture()
def workspace(tmp_path):
    return str(tmp_path / "nisar_workspace")


@pytest.fixture()
def configured_project(workspace):
    """Create and fully configure an insar project with real NAS data paths."""
    result = insar_create_project(
        engine="isce3",
        workflow="insar",
        workspace_root=workspace,
        name="wangshuai-nisar-test",
        conda_env="isce3",
    )
    pid = result["project_id"]

    fields = {
        "runconfig.groups.input_file_group.reference_rslc_file": str(REF_RSLC),
        "runconfig.groups.input_file_group.secondary_rslc_file": str(SEC_RSLC),
        "runconfig.groups.dynamic_ancillary_file_group.dem_file": str(DEM_FILE),
        "runconfig.groups.product_path_group.product_path": str(Path(workspace) / "outputs"),
        "runconfig.groups.product_path_group.scratch_path": str(Path(workspace) / "scratch"),
        "runconfig.groups.product_path_group.sas_output_file": "GUNW_product.h5",
        "runconfig.groups.logging.path": str(Path(workspace) / "logs" / "insar_process.log"),
        "runconfig.groups.worker.gpu_enabled": True,
    }
    for key, val in fields.items():
        r = insar_set_runconfig_value(pid, key, val)
        assert "error" not in r, f"Failed to set {key}: {r}"

    return pid


# ── tests ─────────────────────────────────────────────────────────────────────

def test_project_created_with_real_data(configured_project):
    """Project can be created with NAS data paths."""
    assert configured_project is not None


def test_validate_passes_with_real_paths(configured_project):
    """Runconfig validates cleanly when all required paths point to real files."""
    result = insar_validate_runconfig(configured_project)
    assert result["valid"] is True, result["errors"]


def test_export_produces_valid_yaml(configured_project, tmp_path):
    """Exported YAML is parseable and contains the set paths."""
    result = insar_export_runconfig(configured_project)
    assert "yaml_path" in result

    yaml_path = Path(result["yaml_path"])
    assert yaml_path.exists()

    content = yaml.safe_load(yaml_path.read_text())
    ref_file = content["runconfig"]["groups"]["input_file_group"]["reference_rslc_file"]
    assert str(REF_RSLC) in ref_file


def test_dry_run_produces_correct_command(configured_project):
    """Dry-run returns an ISCE3 conda command with the exported runconfig."""
    insar_export_runconfig(configured_project)
    result = insar_run_workflow(configured_project, dry_run=True)

    assert result["dry_run"] is True
    assert result["status"] == "dry_run"

    cmd = result["command"]
    assert "conda" in cmd[0]
    assert "isce3" in cmd        # conda env name
    assert any("nisar.workflows.insar" in c for c in cmd)
    assert any("runconfig.yaml" in c for c in cmd)


def test_wangshuai_fixture_runconfig_compatible(tmp_path):
    """The wangshuai fixture runconfig (tests/fixtures/insar_nisar.yaml) is
    structurally compatible with our default template."""
    fixture = Path("tests/fixtures/insar_nisar.yaml")
    if not fixture.exists():
        pytest.skip("Fixture not found")

    content = yaml.safe_load(fixture.read_text())
    assert "runconfig" in content
    groups = content["runconfig"]["groups"]
    assert "input_file_group" in groups
    assert "dynamic_ancillary_file_group" in groups
    assert "product_path_group" in groups
