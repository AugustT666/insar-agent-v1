from __future__ import annotations

from pathlib import Path

import pytest

from insar_agent.mcp.server import insar_create_project, insar_describe_rslc, insar_set_runconfig_value


NAS_ROOT = Path("/home/august/NAS/NISAR_wangshuai_data")
REF_RSLC = NAS_ROOT / "NISAR_L1_PR_RSLC_005_172_A_008_2005_DHDH_A_20251122T024618_20251122T024652_X05007_N_F_J_001_cropped.h5"
SEC_RSLC = NAS_ROOT / "NISAR_L1_PR_RSLC_006_172_A_008_2005_DHDH_A_20251204T024618_20251204T024653_X05007_N_F_J_001_cropped.h5"
DEM_FILE = NAS_ROOT / "dem.wgs84"

NAS_AVAILABLE = REF_RSLC.exists() and SEC_RSLC.exists() and DEM_FILE.exists()

pytestmark = [
    pytest.mark.real_data,
    pytest.mark.skipif(
        not NAS_AVAILABLE,
        reason="NAS data not available; mount /home/august/NAS/NISAR_wangshuai_data/",
    ),
]


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "registry"))


def test_insar_describe_rslc_reads_real_nas_pair(tmp_path):
    project = insar_create_project(
        engine="isce3",
        workflow="insar",
        workspace_root=str(tmp_path / "ws"),
        name="real-param-advisor-metadata",
    )
    pid = project["project_id"]
    for key, value in [
        ("runconfig.groups.input_file_group.reference_rslc_file", str(REF_RSLC)),
        ("runconfig.groups.input_file_group.secondary_rslc_file", str(SEC_RSLC)),
        ("runconfig.groups.dynamic_ancillary_file_group.dem_file", str(DEM_FILE)),
    ]:
        result = insar_set_runconfig_value(pid, key, value)
        assert "error" not in result, result

    summary = insar_describe_rslc(
        reference_rslc=str(REF_RSLC),
        secondary_rslc=str(SEC_RSLC),
        project_id=pid,
    )

    assert "error" not in summary, summary
    assert summary["pair_metadata"]["sensor"] == "NISAR"
    assert summary["pair_metadata"]["band"] == "L"
    assert summary["pair_metadata"]["temporal_baseline_days"] == 12
    assert summary["pair_metadata"]["union_bbox"]["min_lon"] < summary["pair_metadata"]["union_bbox"]["max_lon"]
    assert summary["processing_context"]["dem_file_provided"] is True
