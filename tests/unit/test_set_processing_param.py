"""Unit tests for M7: insar_set_processing_param and processing parameter registry."""
from __future__ import annotations

import pytest

from insar_agent.engines.isce3.defaults import (
    get_processing_param_keys,
    load_processing_params,
)
from insar_agent.mcp.server import (
    insar_create_project,
    insar_get_runconfig,
    insar_set_processing_param,
    insar_set_runconfig_value,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "registry"))
    (tmp_path / "registry").mkdir()


@pytest.fixture()
def insar_project(tmp_path):
    result = insar_create_project(
        engine="isce3",
        workflow="insar",
        workspace_root=str(tmp_path / "workspace"),
    )
    assert "project_id" in result, result
    return result


# ── registry loader tests ─────────────────────────────────────────────────────

def test_load_processing_params_returns_list():
    params = load_processing_params("insar")
    assert isinstance(params, list)
    assert len(params) > 0


def test_load_processing_params_schema():
    params = load_processing_params("insar")
    for p in params:
        assert "key" in p, f"Missing 'key' in entry: {p}"
        assert "label" in p, f"Missing 'label' in entry: {p}"
        assert "default" in p, f"Missing 'default' in entry: {p}"
        assert "type" in p, f"Missing 'type' in entry: {p}"
        assert "risk_level" in p, f"Missing 'risk_level' in entry: {p}"
        assert p["risk_level"] in ("low", "medium", "high"), f"Invalid risk_level in {p}"


def test_get_processing_param_keys_returns_list():
    keys = get_processing_param_keys("insar")
    assert isinstance(keys, list)
    assert len(keys) > 0


def test_known_keys_present():
    keys = get_processing_param_keys("insar")
    assert "runconfig.groups.processing.crossmul.range_looks" in keys
    assert "runconfig.groups.processing.crossmul.azimuth_looks" in keys
    assert "runconfig.groups.processing.phase_unwrap.algorithm" in keys
    assert "runconfig.groups.processing.phase_unwrap.snaphu.cost_mode" in keys
    assert "runconfig.groups.processing.ionosphere_phase_correction.enabled" in keys
    assert "runconfig.groups.processing.troposphere_delay.enabled" in keys


def test_load_processing_params_unknown_workflow():
    with pytest.raises(FileNotFoundError):
        load_processing_params("nonexistent")


# ── insar_set_processing_param — success cases ────────────────────────────────

def test_set_range_looks(insar_project):
    pid = insar_project["project_id"]
    result = insar_set_processing_param(
        project_id=pid,
        key="runconfig.groups.processing.crossmul.range_looks",
        value=5,
        justification="城市L波段高相干，减少多视以保留分辨率",
    )
    assert result.get("error") is None, result
    assert result["new_value"] == 5
    assert result["key"] == "runconfig.groups.processing.crossmul.range_looks"
    assert result["justification"] == "城市L波段高相干，减少多视以保留分辨率"
    assert result["risk_level"] == "medium"
    assert "old_value" in result
    assert "updated_at" in result


def test_set_snaphu_cost_mode(insar_project):
    pid = insar_project["project_id"]
    result = insar_set_processing_param(
        project_id=pid,
        key="runconfig.groups.processing.phase_unwrap.snaphu.cost_mode",
        value="defo",
        justification="同震场景，形变梯度大，需要defo代价函数",
    )
    assert result.get("error") is None, result
    assert result["new_value"] == "defo"


def test_set_bool_param(insar_project):
    pid = insar_project["project_id"]
    result = insar_set_processing_param(
        project_id=pid,
        key="runconfig.groups.processing.ionosphere_phase_correction.enabled",
        value=True,
        justification="L波段高纬度区域，电离层影响显著",
    )
    assert result.get("error") is None, result
    assert result["new_value"] is True


def test_set_null_param(insar_project):
    """Setting a nullable param to None should succeed."""
    pid = insar_project["project_id"]
    result = insar_set_processing_param(
        project_id=pid,
        key="runconfig.groups.processing.phase_unwrap.snaphu.nlooks",
        value=None,
        justification="恢复默认，让Snaphu自动估计等效视数",
    )
    assert result.get("error") is None, result


def test_set_processing_param_value_reflected_in_runconfig(insar_project):
    """The new value should be visible in the runconfig after setting."""
    pid = insar_project["project_id"]
    insar_set_processing_param(
        project_id=pid,
        key="runconfig.groups.processing.crossmul.azimuth_looks",
        value=7,
        justification="测试验证：减小方位向多视数",
    )
    rc = insar_get_runconfig(project_id=pid, format="json")
    assert rc.get("error") is None, rc
    # runconfig is the full dict: {"runconfig": {"groups": ...}}
    val = rc["runconfig"]["runconfig"]["groups"]["processing"]["crossmul"]["azimuth_looks"]
    assert val == 7


# ── insar_set_processing_param — error cases ──────────────────────────────────

def test_set_processing_param_empty_justification(insar_project):
    pid = insar_project["project_id"]
    result = insar_set_processing_param(
        project_id=pid,
        key="runconfig.groups.processing.crossmul.range_looks",
        value=5,
        justification="",
    )
    assert result["error"] == "justification_required"


def test_set_processing_param_whitespace_justification(insar_project):
    pid = insar_project["project_id"]
    result = insar_set_processing_param(
        project_id=pid,
        key="runconfig.groups.processing.crossmul.range_looks",
        value=5,
        justification="   ",
    )
    assert result["error"] == "justification_required"


def test_set_processing_param_key_not_allowed(insar_project):
    pid = insar_project["project_id"]
    result = insar_set_processing_param(
        project_id=pid,
        key="runconfig.groups.input_file_group.reference_rslc_file",
        value="/some/path.h5",
        justification="尝试通过处理参数接口修改路径字段",
    )
    assert result["error"] == "key_not_allowed"


def test_set_processing_param_invalid_valid_values(insar_project):
    pid = insar_project["project_id"]
    result = insar_set_processing_param(
        project_id=pid,
        key="runconfig.groups.processing.phase_unwrap.snaphu.cost_mode",
        value="invalid_mode",
        justification="测试非法cost_mode值",
    )
    assert result["error"] == "value_not_allowed"


def test_set_processing_param_out_of_range(insar_project):
    pid = insar_project["project_id"]
    result = insar_set_processing_param(
        project_id=pid,
        key="runconfig.groups.processing.crossmul.range_looks",
        value=999,
        justification="测试超出范围的多视数",
    )
    assert result["error"] == "value_out_of_range"


def test_set_processing_param_unknown_project():
    result = insar_set_processing_param(
        project_id="00000000-0000-0000-0000-000000000000",
        key="runconfig.groups.processing.crossmul.range_looks",
        value=5,
        justification="测试不存在的project_id",
    )
    assert result.get("error") is not None


# ── separation of concerns ────────────────────────────────────────────────────

def test_set_runconfig_value_cannot_set_processing_params(insar_project):
    """
    insar_set_runconfig_value must still reject processing parameter keys,
    preserving the original behavior.
    """
    pid = insar_project["project_id"]
    result = insar_set_runconfig_value(
        project_id=pid,
        key="runconfig.groups.processing.crossmul.range_looks",
        value=5,
    )
    assert result["error"] == "key_not_allowed"
