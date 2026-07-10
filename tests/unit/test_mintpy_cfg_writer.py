from __future__ import annotations

from insar_agent.engines.isce2.mintpy import (
    MANAGED_MINTPY_CFG_NAME,
    managed_mintpy_cfg_path,
    set_mintpy_cfg_value,
)


def test_set_mintpy_cfg_value_replaces_existing_line(tmp_path):
    work_dir = tmp_path
    cfg = managed_mintpy_cfg_path(work_dir)
    cfg.write_text(
        "mintpy.load.processor = isce\n"
        "mintpy.network.tempBaseMax = auto\n"
        "mintpy.deramp = no\n",
        encoding="utf-8",
    )
    out = set_mintpy_cfg_value(work_dir, "network.tempBaseMax", 120)
    assert out == cfg
    assert out.name == MANAGED_MINTPY_CFG_NAME
    lines = cfg.read_text(encoding="utf-8").splitlines()
    assert "mintpy.network.tempBaseMax = 120" in lines
    # every other line preserved verbatim
    assert "mintpy.load.processor = isce" in lines
    assert "mintpy.deramp = no" in lines
    # replaced in place, not appended
    assert sum(l.startswith("mintpy.network.tempBaseMax") for l in lines) == 1


def test_set_mintpy_cfg_value_appends_when_absent_and_creates_file(tmp_path):
    work_dir = tmp_path / "sub"  # parent dir does not exist yet
    out = set_mintpy_cfg_value(work_dir, "troposphericDelay.method", "pyaps")
    assert out.exists()
    assert out == managed_mintpy_cfg_path(work_dir)
    assert "mintpy.troposphericDelay.method = pyaps" in out.read_text(encoding="utf-8")


def test_set_mintpy_cfg_value_formats_bool_as_yes_no(tmp_path):
    work_dir = tmp_path
    set_mintpy_cfg_value(work_dir, "solidEarthTides", True)
    set_mintpy_cfg_value(work_dir, "topographicResidual", False)
    text = managed_mintpy_cfg_path(work_dir).read_text(encoding="utf-8")
    assert "mintpy.solidEarthTides = yes" in text
    assert "mintpy.topographicResidual = no" in text
