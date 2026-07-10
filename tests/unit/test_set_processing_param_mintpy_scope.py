from __future__ import annotations

import pytest

from insar_agent.mcp.server import insar_set_processing_param


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "registry"))


def test_scope_mintpy_writes_whitelisted_key_into_cfg(tmp_path):
    work = tmp_path / "mintpy"
    work.mkdir()
    cfg = work / "isce2_stack.txt"
    cfg.write_text(
        "mintpy.load.processor = isce\nmintpy.network.tempBaseMax = auto\n",
        encoding="utf-8",
    )

    result = insar_set_processing_param(
        project_id="unused-for-mintpy",
        key="network.tempBaseMax",
        value=120,
        justification="限制时间基线以抑制去相干长跨对",
        scope="mintpy",
        mintpy_work_dir=str(work),
    )

    assert "error" not in result, result
    assert result["scope"] == "mintpy"
    assert result["new_value"] == 120
    assert result["cfg_path"] == str(cfg)
    text = cfg.read_text(encoding="utf-8")
    assert "mintpy.network.tempBaseMax = 120" in text
    assert "mintpy.load.processor = isce" in text  # other lines preserved
    assert text.count("mintpy.network.tempBaseMax") == 1  # replaced, not appended


def test_scope_mintpy_rejects_non_whitelisted_key(tmp_path):
    work = tmp_path / "mintpy"
    work.mkdir()
    cfg = work / "isce2_stack.txt"
    cfg.write_text("mintpy.load.processor = isce\n", encoding="utf-8")

    result = insar_set_processing_param(
        project_id="unused-for-mintpy",
        key="network.notARealKey",
        value=1,
        justification="试图写入不在白名单的键",
        scope="mintpy",
        mintpy_work_dir=str(work),
    )

    assert result["error"] == "key_not_allowed"
    # cfg is left untouched on rejection
    assert cfg.read_text(encoding="utf-8") == "mintpy.load.processor = isce\n"


def test_scope_mintpy_requires_work_dir():
    result = insar_set_processing_param(
        project_id="unused-for-mintpy",
        key="network.tempBaseMax",
        value=120,
        justification="限制时间基线",
        scope="mintpy",
        mintpy_work_dir="",
    )
    assert result["error"] == "mintpy_work_dir_required"
