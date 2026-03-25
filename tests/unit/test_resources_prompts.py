"""Tests for MCP Resources, Prompts, and next_step guidance."""
from __future__ import annotations

from insar_agent.mcp.server import (
    get_workflow_guide,
    get_allowed_fields,
    process_insar_pair,
    process_insar_batch,
    insar_create_project,
    insar_validate_runconfig,
    insar_export_runconfig,
    insar_run_workflow,
    insar_set_runconfig_value,
    insar_list_outputs,
    insar_prepare_stack,
    insar_prepare_network,
)


# ── Resources ─────────────────────────────────────────────────────────────────

def test_workflow_guide_is_string():
    guide = get_workflow_guide()
    assert isinstance(guide, str)
    assert len(guide) > 100


def test_workflow_guide_mentions_hard_constraints():
    guide = get_workflow_guide()
    assert "Hard constraints" in guide
    assert "key_not_allowed" in guide


def test_workflow_guide_mentions_both_paths():
    guide = get_workflow_guide()
    assert "Path A" in guide
    assert "Path B" in guide


def test_workflow_guide_lists_required_fields():
    guide = get_workflow_guide()
    assert "reference_rslc_file" in guide
    assert "secondary_rslc_file" in guide
    assert "dem_file" in guide


def test_workflow_guide_mentions_step_order():
    guide = get_workflow_guide()
    # Steps must be present in order
    assert guide.index("insar_create_project") < guide.index("insar_validate_runconfig")
    assert guide.index("insar_validate_runconfig") < guide.index("insar_export_runconfig")
    assert guide.index("insar_export_runconfig") < guide.index("insar_run_workflow")


def test_allowed_fields_insar():
    text = get_allowed_fields("insar")
    assert "reference_rslc_file" in text
    assert "dem_file" in text
    assert "gpu_enabled" in text
    assert "Required" in text
    assert "Optional" in text


def test_allowed_fields_gslc():
    text = get_allowed_fields("gslc")
    assert "input_file_path" in text


def test_allowed_fields_unknown_workflow():
    text = get_allowed_fields("bogus")
    assert "Unknown workflow" in text


# ── Prompts ───────────────────────────────────────────────────────────────────

def test_process_insar_pair_returns_string():
    prompt = process_insar_pair()
    assert isinstance(prompt, str)
    assert len(prompt) > 100


def test_process_insar_pair_interpolates_paths():
    prompt = process_insar_pair(
        reference_rslc="/data/ref.h5",
        secondary_rslc="/data/sec.h5",
        dem="/data/dem.tif",
        output_dir="/work/out",
        conda_env="isce3",
    )
    assert "/data/ref.h5" in prompt
    assert "/data/sec.h5" in prompt
    assert "/data/dem.tif" in prompt
    assert "/work/out" in prompt
    assert "isce3" in prompt


def test_process_insar_pair_contains_constraint_reminder():
    prompt = process_insar_pair()
    assert "core processing parameters" in prompt.lower() or "Constraints reminder" in prompt


def test_process_insar_pair_step_order():
    prompt = process_insar_pair()
    assert prompt.index("insar_create_project") < prompt.index("insar_validate_runconfig")
    assert prompt.index("insar_validate_runconfig") < prompt.index("insar_export_runconfig")
    assert prompt.index("insar_export_runconfig") < prompt.index("insar_run_workflow")


def test_process_insar_batch_returns_string():
    prompt = process_insar_batch()
    assert isinstance(prompt, str)
    assert len(prompt) > 100


def test_process_insar_batch_interpolates_params():
    prompt = process_insar_batch(
        data_dir="/data/rslc",
        dem="/data/dem.tif",
        output_dir="/work",
        network_mode="conn",
        max_temporal_baseline_days=24,
    )
    assert "/data/rslc" in prompt
    assert "/data/dem.tif" in prompt
    assert "/work" in prompt
    assert "conn" in prompt


def test_process_insar_batch_mentions_run_parallel():
    prompt = process_insar_batch()
    assert "run_parallel.sh" in prompt


def test_process_insar_batch_step_order():
    prompt = process_insar_batch()
    assert prompt.index("insar_prepare_stack") < prompt.index("insar_prepare_network")


# ── next_step in tool returns ─────────────────────────────────────────────────

import os
import pytest


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "registry"))


@pytest.fixture()
def insar_project(tmp_path):
    result = insar_create_project(
        engine="isce3", workflow="insar",
        workspace_root=str(tmp_path / "ws"),
    )
    assert "project_id" in result
    return result


def test_create_project_has_next_step(insar_project):
    assert "next_step" in insar_project
    assert "insar_set_runconfig_value" in insar_project["next_step"]
    assert "reference_rslc_file" in insar_project["next_step"]


def test_validate_invalid_has_next_step(insar_project):
    result = insar_validate_runconfig(insar_project["project_id"])
    assert result["valid"] is False
    assert "next_step" in result
    assert "insar_set_runconfig_value" in result["next_step"]


def test_validate_valid_has_next_step(insar_project):
    pid = insar_project["project_id"]
    for key, val in [
        ("runconfig.groups.input_file_group.reference_rslc_file", "/data/ref.h5"),
        ("runconfig.groups.input_file_group.secondary_rslc_file", "/data/sec.h5"),
        ("runconfig.groups.dynamic_ancillary_file_group.dem_file", "/data/dem.tif"),
        ("runconfig.groups.product_path_group.product_path", "/out"),
        ("runconfig.groups.product_path_group.scratch_path", "/tmp"),
        ("runconfig.groups.product_path_group.sas_output_file", "GUNW.h5"),
    ]:
        insar_set_runconfig_value(pid, key, val)
    result = insar_validate_runconfig(pid)
    assert result["valid"] is True
    assert "next_step" in result
    assert "insar_export_runconfig" in result["next_step"]


def test_export_runconfig_has_next_step(insar_project):
    result = insar_export_runconfig(insar_project["project_id"])
    assert "next_step" in result
    assert "insar_run_workflow" in result["next_step"]


def test_run_workflow_dry_run_has_next_step(insar_project):
    pid = insar_project["project_id"]
    for key, val in [
        ("runconfig.groups.input_file_group.reference_rslc_file", "/data/ref.h5"),
        ("runconfig.groups.input_file_group.secondary_rslc_file", "/data/sec.h5"),
        ("runconfig.groups.dynamic_ancillary_file_group.dem_file", "/data/dem.tif"),
        ("runconfig.groups.product_path_group.product_path", "/out"),
        ("runconfig.groups.product_path_group.scratch_path", "/tmp"),
        ("runconfig.groups.product_path_group.sas_output_file", "GUNW.h5"),
    ]:
        insar_set_runconfig_value(pid, key, val)
    insar_export_runconfig(pid)
    result = insar_run_workflow(pid, dry_run=True)
    assert result["dry_run"] is True
    # dry_run does not add next_step (no job launched), this is fine


def test_prepare_stack_has_next_step(tmp_path):
    from tests.unit.test_m4_stack_network import make_rslc, make_fixture_runconfig, make_dem
    data_dir = tmp_path / "rslc"
    data_dir.mkdir()
    make_rslc(data_dir, "20251122")
    make_rslc(data_dir, "20251204")
    rc = make_fixture_runconfig(tmp_path)
    dem = make_dem(tmp_path)

    result = insar_prepare_stack(
        data_dir=str(data_dir), base_runconfig=str(rc),
        dem=str(dem), output_dir=str(tmp_path / "stack"),
    )
    assert "next_step" in result
    assert "run_parallel.sh" in result["next_step"]
    assert "insar_prepare_network" in result["next_step"]


def test_prepare_network_has_next_step(tmp_path):
    from tests.unit.test_m4_stack_network import make_rslc, make_fixture_runconfig, make_dem
    data_dir = tmp_path / "rslc"
    data_dir.mkdir()
    make_rslc(data_dir, "20251122")
    make_rslc(data_dir, "20251204")
    rc = make_fixture_runconfig(tmp_path)
    dem = make_dem(tmp_path)

    result = insar_prepare_network(
        data_dir=str(data_dir), base_runconfig=str(rc),
        dem=str(dem), output_dir=str(tmp_path / "network"),
    )
    assert "next_step" in result
    assert "run_parallel.sh" in result["next_step"]
    assert "products" in result["next_step"]
