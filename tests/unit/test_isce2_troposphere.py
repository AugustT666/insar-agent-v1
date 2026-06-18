"""Unit tests for the ISCE2 ERA5 troposphere correction tool wiring.

Covers the import-light command builder, the MCP tool's input validation, and
its sentinel-tagged stdout parsing — none of which need pyaps3/GDAL/data.
"""
from __future__ import annotations

import json
import subprocess


def test_build_troposphere_command_basic():
    from insar_agent.engines.isce2.runner import build_troposphere_command

    cmd = build_troposphere_command(
        "/runs/r1", "20251025", "20251106",
        ["/era5/a.grib", "/era5/b.grib"], conda_env="isce2",
    )
    assert cmd[:5] == ["conda", "run", "-n", "isce2", "--no-capture-output"]
    assert cmd[5:8] == ["python", "-m", "insar_agent.engines.isce2.troposphere"]
    assert cmd[8:11] == ["/runs/r1", "20251025", "20251106"]
    assert "/era5/a.grib" in cmd and "/era5/b.grib" in cmd
    assert "--out-dir" not in cmd


def test_build_troposphere_command_out_dir_and_env():
    from insar_agent.engines.isce2.runner import build_troposphere_command

    cmd = build_troposphere_command(
        "/runs/r1", "20251025", "20251106", ["/e/a.grib"],
        conda_env="isce3gpu", out_dir="/out/tc",
    )
    assert cmd[3] == "isce3gpu"
    assert cmd[-2:] == ["--out-dir", "/out/tc"]


def test_tool_missing_merged_returns_path_not_found(tmp_path):
    from insar_agent.mcp.tools.product_tools import insar_apply_troposphere_isce2

    grib = tmp_path / "a.grib"
    grib.write_bytes(b"x")
    res = insar_apply_troposphere_isce2(str(tmp_path), "20251025", "20251106", [str(grib)])
    assert res["error"] == "path_not_found"
    assert "merged" in res["message"]


def test_tool_missing_grib_returns_path_not_found(tmp_path):
    from insar_agent.mcp.tools.product_tools import insar_apply_troposphere_isce2

    merged = tmp_path / "merged"
    merged.mkdir()
    (merged / "filt_topophase.unw.geo.vrt").write_text("<VRTDataset/>")
    res = insar_apply_troposphere_isce2(
        str(tmp_path), "20251025", "20251106", ["/nope/missing.grib"]
    )
    assert res["error"] == "path_not_found"
    assert "missing.grib" in str(res["message"])


def test_tool_recovers_sentinel_json_from_noisy_stdout(tmp_path, monkeypatch):
    from insar_agent.engines.isce2.runner import TROPO_RESULT_SENTINEL
    from insar_agent.mcp.tools import product_tools

    merged = tmp_path / "merged"
    merged.mkdir()
    (merged / "filt_topophase.unw.geo.vrt").write_text("<VRTDataset/>")
    grib = tmp_path / "a.grib"
    grib.write_bytes(b"x")

    payload = {"output_dir": "/x/troposphere_correction",
               "stats": {"height_corr_before": 0.53, "height_corr_after": 0.13}}

    class _FakeProc:
        returncode = 0
        stdout = ("INFO: You are using ...\nPROJ: proj_create noise\n"
                  + TROPO_RESULT_SENTINEL + json.dumps(payload) + "\n")
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeProc())
    res = product_tools.insar_apply_troposphere_isce2(
        str(tmp_path), "20251025", "20251106", [str(grib)]
    )
    assert res == payload


def test_tool_reports_failure_when_no_sentinel(tmp_path, monkeypatch):
    from insar_agent.mcp.tools import product_tools

    merged = tmp_path / "merged"
    merged.mkdir()
    (merged / "filt_topophase.unw.geo.vrt").write_text("<VRTDataset/>")
    grib = tmp_path / "a.grib"
    grib.write_bytes(b"x")

    class _FakeProc:
        returncode = 1
        stdout = "some noise without a result line"
        stderr = "Traceback: boom"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeProc())
    res = product_tools.insar_apply_troposphere_isce2(
        str(tmp_path), "20251025", "20251106", [str(grib)]
    )
    assert res["error"] == "correction_failed"
    assert "boom" in res["message"]
