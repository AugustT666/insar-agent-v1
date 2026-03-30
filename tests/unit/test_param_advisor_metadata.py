from __future__ import annotations

from pathlib import Path

import pytest

from insar_agent.core.config import set_path
from insar_agent.engines.isce3.defaults import load_default_runconfig
from insar_agent.engines.isce3.rslc_metadata import (
    describe_rslc_pair,
    summarize_rslc,
)
from insar_agent.mcp.server import insar_create_project, insar_describe_rslc, insar_set_runconfig_value


def _make_rslc(
    tmp_path: Path,
    *,
    start_stamp: str,
    end_stamp: str,
    suffix: str = "001",
    polygon: str | None = None,
) -> Path:
    path = tmp_path / (
        "NISAR_L1_PR_RSLC_005_172_A_008_2005_DHDH_A_"
        f"{start_stamp}_{end_stamp}_X05007_N_F_J_{suffix}_cropped.h5"
    )

    if polygon is None:
        path.write_bytes(b"not-a-real-hdf5")
        return path

    import h5py

    with h5py.File(path, "w") as hf:
        hf.create_dataset(
            "/science/LSAR/identification/boundingPolygon",
            data=polygon.encode("utf-8"),
        )
    return path


def _runconfig_with_pair(reference: str, secondary: str) -> dict:
    runconfig = load_default_runconfig("insar")
    set_path(runconfig, "runconfig.groups.input_file_group.reference_rslc_file", reference)
    set_path(runconfig, "runconfig.groups.input_file_group.secondary_rslc_file", secondary)
    set_path(runconfig, "runconfig.groups.dynamic_ancillary_file_group.dem_file", "/data/dem.tif")
    set_path(runconfig, "runconfig.groups.dynamic_ancillary_file_group.water_mask_file", "/data/water.tif")
    set_path(
        runconfig,
        "runconfig.groups.processing.crossmul.range_looks",
        7,
    )
    return runconfig


def test_summarize_rslc_infers_metadata_and_bbox(tmp_path):
    rslc = _make_rslc(
        tmp_path,
        start_stamp="20251122T024618",
        end_stamp="20251122T024652",
        polygon="POLYGON ((120.0 35.0 0, 121.0 35.0 0, 121.0 36.0 0, 120.0 36.0 0, 120.0 35.0 0))",
    )

    summary = summarize_rslc(rslc)

    assert summary["sensor"] == "NISAR"
    assert summary["product_type"] == "RSLC"
    assert summary["band"] == "L"
    assert summary["orbit_direction"] == "ascending"
    assert summary["polarizations"] == ["HH"]
    assert summary["bbox"]["min_lon"] == pytest.approx(120.0)
    assert "acquisition_start" not in summary["missing_fields"]


def test_describe_rslc_pair_combines_temporal_baseline_and_processing_context(tmp_path):
    reference = _make_rslc(
        tmp_path,
        start_stamp="20251122T024618",
        end_stamp="20251122T024652",
        suffix="001",
        polygon="POLYGON ((120.0 35.0 0, 121.0 35.0 0, 121.0 36.0 0, 120.0 36.0 0, 120.0 35.0 0))",
    )
    secondary = _make_rslc(
        tmp_path,
        start_stamp="20251204T024618",
        end_stamp="20251204T024653",
        suffix="002",
        polygon="POLYGON ((120.5 35.5 0, 122.0 35.5 0, 122.0 37.0 0, 120.5 37.0 0, 120.5 35.5 0))",
    )

    result = describe_rslc_pair(
        reference,
        secondary,
        runconfig=_runconfig_with_pair(str(reference), str(secondary)),
    )

    assert result["pair_metadata"]["temporal_baseline_days"] == 12
    assert result["pair_metadata"]["union_bbox"]["max_lon"] == pytest.approx(122.0)
    assert result["processing_context"]["dem_file_provided"] is True
    assert result["processing_context"]["water_mask_provided"] is True
    assert result["processing_context"]["current_processing_params"]["runconfig.groups.processing.crossmul.range_looks"] == 7


def test_describe_rslc_pair_falls_back_to_filename_when_hdf5_unavailable(tmp_path):
    reference = _make_rslc(
        tmp_path,
        start_stamp="20251122T024618",
        end_stamp="20251122T024652",
        polygon=None,
    )
    secondary = _make_rslc(
        tmp_path,
        start_stamp="20251204T024618",
        end_stamp="20251204T024653",
        suffix="002",
        polygon=None,
    )

    result = describe_rslc_pair(reference, secondary)

    assert result["pair_metadata"]["temporal_baseline_days"] == 12
    assert "bbox" in result["reference_metadata"]["missing_fields"]
    assert result["reference_metadata"]["sensor"] == "NISAR"


def test_insar_describe_rslc_tool_returns_pair_summary_and_project_context(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "registry"))
    reference = _make_rslc(
        tmp_path,
        start_stamp="20251122T024618",
        end_stamp="20251122T024652",
        polygon="POLYGON ((120.0 35.0 0, 121.0 35.0 0, 121.0 36.0 0, 120.0 36.0 0, 120.0 35.0 0))",
    )
    secondary = _make_rslc(
        tmp_path,
        start_stamp="20251204T024618",
        end_stamp="20251204T024653",
        suffix="002",
        polygon="POLYGON ((120.5 35.5 0, 122.0 35.5 0, 122.0 37.0 0, 120.5 37.0 0, 120.5 35.5 0))",
    )
    project = insar_create_project(
        engine="isce3",
        workflow="insar",
        workspace_root=str(tmp_path / "ws"),
    )
    pid = project["project_id"]
    insar_set_runconfig_value(
        pid,
        "runconfig.groups.input_file_group.reference_rslc_file",
        str(reference),
    )
    insar_set_runconfig_value(
        pid,
        "runconfig.groups.input_file_group.secondary_rslc_file",
        str(secondary),
    )
    insar_set_runconfig_value(
        pid,
        "runconfig.groups.dynamic_ancillary_file_group.dem_file",
        "/data/dem.tif",
    )

    result = insar_describe_rslc(
        reference_rslc=str(reference),
        secondary_rslc=str(secondary),
        project_id=pid,
    )

    assert "error" not in result
    assert result["pair_metadata"]["temporal_baseline_days"] == 12
    assert result["processing_context"]["project_id"] == pid
    assert "band" in result["inferred_fields"]

