from __future__ import annotations

from insar_agent.engines.isce2.mintpy import MINTPY_CFG_NAME, set_mintpy_cfg_value


def test_set_mintpy_cfg_value_replaces_existing_line(tmp_path):
    cfg = tmp_path / MINTPY_CFG_NAME
    cfg.write_text(
        "mintpy.load.processor = isce\n"
        "mintpy.network.tempBaseMax = auto\n"
        "mintpy.deramp = no\n",
        encoding="utf-8",
    )
    out = set_mintpy_cfg_value(cfg, "network.tempBaseMax", 120)
    assert out == cfg
    lines = cfg.read_text(encoding="utf-8").splitlines()
    assert "mintpy.network.tempBaseMax = 120" in lines
    # every other line preserved verbatim
    assert "mintpy.load.processor = isce" in lines
    assert "mintpy.deramp = no" in lines
    # replaced in place, not appended
    assert sum(l.startswith("mintpy.network.tempBaseMax") for l in lines) == 1


def test_set_mintpy_cfg_value_appends_when_absent_and_creates_file(tmp_path):
    cfg = tmp_path / "sub" / MINTPY_CFG_NAME  # parent dir does not exist yet
    out = set_mintpy_cfg_value(cfg, "troposphericDelay.method", "pyaps")
    assert out.exists()
    assert "mintpy.troposphericDelay.method = pyaps" in out.read_text(encoding="utf-8")


def test_set_mintpy_cfg_value_formats_bool_as_yes_no(tmp_path):
    cfg = tmp_path / MINTPY_CFG_NAME
    set_mintpy_cfg_value(cfg, "solidEarthTides", True)
    set_mintpy_cfg_value(cfg, "topographicResidual", False)
    text = cfg.read_text(encoding="utf-8")
    assert "mintpy.solidEarthTides = yes" in text
    assert "mintpy.topographicResidual = no" in text
