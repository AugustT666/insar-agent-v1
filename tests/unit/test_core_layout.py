"""Unit tests for src/insar_agent/core/layout.py."""
from __future__ import annotations

from pathlib import Path

import pytest

from insar_agent.core.layout import (
    RunLayout,
    infer_run_root,
    make_run_id,
    sanitize_identifier,
    validate_workspace_root,
)


# ---------------------------------------------------------------------------
# make_run_id
# ---------------------------------------------------------------------------

def test_make_run_id_format():
    rid = make_run_id("d-insar-isce2")
    # Hyphens are preserved in sanitize_identifier
    assert rid.startswith("d-insar-isce2_")
    # Timestamp part after the last _: 16 chars YYYYMMDDTHHMMSSz
    ts = rid.rsplit("_", 1)[-1]
    assert len(ts) == 16
    assert ts.endswith("Z")


def test_make_run_id_sanitizes():
    rid = make_run_id("d-insar-isce2 task/test")
    assert " " not in rid
    assert "/" not in rid


def test_sanitize_identifier_removes_path_separators_and_whitespace():
    assert sanitize_identifier(" ../E1 task/test ") == "___E1_task_test"


# ---------------------------------------------------------------------------
# validate_workspace_root
# ---------------------------------------------------------------------------

def test_validate_workspace_root_ok(tmp_path):
    ws = validate_workspace_root(tmp_path)
    assert ws == tmp_path.resolve()


def test_validate_workspace_root_rejects_run_root(tmp_path):
    # <workspace>/<task_id>/outputs/<run_id> — this is a run_root, not a workspace
    bad = tmp_path / "d-insar-isce2" / "outputs" / "d-insar-isce2_20260511T000000Z"
    with pytest.raises(ValueError, match="outputs"):
        validate_workspace_root(bad)


def test_validate_workspace_root_rejects_products_nested(tmp_path):
    bad = tmp_path / "d-insar-isce3" / "outputs" / "run1" / "products"
    with pytest.raises(ValueError, match="outputs"):
        validate_workspace_root(bad)


def test_validate_workspace_root_rejects_task_outputs_dir(tmp_path):
    bad = tmp_path / "d-insar-isce2" / "outputs"
    with pytest.raises(ValueError, match="outputs"):
        validate_workspace_root(bad)


def test_validate_workspace_root_accepts_task_dir(tmp_path):
    # A task_id subdirectory is NOT a run_root — it's valid as a workspace
    good = tmp_path / "d-insar-isce2"
    ws = validate_workspace_root(good)
    assert ws == good.resolve()


# ---------------------------------------------------------------------------
# RunLayout path generation
# ---------------------------------------------------------------------------

def test_run_layout_paths(tmp_path):
    layout = RunLayout(workspace_root=tmp_path, task_id="d-insar-isce3", run_id="d-insar-isce3_test")
    assert layout.run_root == tmp_path / "d-insar-isce3" / "outputs" / "d-insar-isce3_test"
    assert layout.products_dir == layout.run_root / "products"
    assert layout.scratch_dir == layout.run_root / "scratch"
    assert layout.configs_dir == layout.run_root / "configs"
    assert layout.logs_dir == layout.run_root / "logs"
    assert layout.param_advisor_dir == layout.run_root / "param_advisor"
    assert layout.param_tuned_dir == layout.run_root / "param_tuned"
    assert layout.metrics_dir == layout.run_root / "metrics"
    assert layout.browse_dir == layout.run_root / "browse"
    assert layout.dem_dir == layout.run_root / "dem"
    assert layout.isce2_dem_dir == layout.run_root / "isce2_dem"
    assert layout.stack_dir == layout.run_root / "stack"
    assert layout.network_dir == layout.run_root / "network"
    assert layout.mintpy_dir == layout.run_root / "mintpy"


def test_run_layout_helpers_do_not_create_task_root_processing_siblings(tmp_path):
    layout = RunLayout(workspace_root=tmp_path, task_id="d-insar-isce2", run_id="run1")

    layout.mkdir_all()

    task_root = tmp_path / "d-insar-isce2"
    assert layout.run_root.exists()
    for sibling in ("configs", "param_tuned", "dem", "isce2_dem", "stack", "network"):
        assert not (tmp_path / sibling).exists()
        assert not (task_root / sibling).exists()


def test_infer_run_root_from_nested_output_path(tmp_path):
    layout = RunLayout(workspace_root=tmp_path, task_id="d-insar-isce3", run_id="run1")

    assert infer_run_root(layout.dem_dir / "dem.tif") == layout.run_root
    assert infer_run_root(layout.run_root / "logs" / "download.log") == layout.run_root
    assert infer_run_root(tmp_path / "d-insar-isce3" / "dem" / "dem.tif") is None
    assert infer_run_root(Path("/tmp/outputs/run1/dem.tif")) is None


def test_run_layout_auto_run_id(tmp_path):
    layout = RunLayout(workspace_root=tmp_path, task_id="d-insar-isce2")
    # Hyphens are preserved
    assert layout.run_id.startswith("d-insar-isce2_")
    # run_root is <workspace>/<task_id>/outputs/<run_id>
    assert layout.run_root.parent.name == "outputs"
    assert layout.run_root.parent.parent.name == "d-insar-isce2"


def test_run_layout_sanitizes_task_id(tmp_path):
    # Spaces and slashes are replaced; hyphens are preserved
    layout = RunLayout(workspace_root=tmp_path, task_id="d insar/isce3", run_id="myrun")
    assert layout.task_id == "d_insar_isce3"
    layout2 = RunLayout(workspace_root=tmp_path, task_id="d-insar-isce3", run_id="myrun")
    assert layout2.task_id == "d-insar-isce3"


# ---------------------------------------------------------------------------
# workspace root safety via RunLayout
# ---------------------------------------------------------------------------

def test_run_layout_rejects_nested_workspace(tmp_path):
    bad_ws = tmp_path / "d-insar-isce2" / "outputs" / "runid"
    with pytest.raises(ValueError):
        RunLayout(workspace_root=bad_ws, task_id="d-insar-isce2", run_id="x")


# ---------------------------------------------------------------------------
# validate_path_inside_workspace
# ---------------------------------------------------------------------------

def test_validate_path_inside_workspace_ok(tmp_path):
    layout = RunLayout(workspace_root=tmp_path, task_id="d-insar-isce3", run_id="r1")
    p = layout.validate_path_inside_workspace(layout.products_dir)
    assert p == layout.products_dir.resolve()


def test_validate_path_inside_workspace_rejects_outside(tmp_path, tmp_path_factory):
    other = tmp_path_factory.mktemp("other")
    layout = RunLayout(workspace_root=tmp_path, task_id="d-insar-isce3", run_id="r1")
    with pytest.raises(ValueError, match="outside workspace_root"):
        layout.validate_path_inside_workspace(other / "evil.h5")


# ---------------------------------------------------------------------------
# to_dict
# ---------------------------------------------------------------------------

def test_run_layout_to_dict(tmp_path):
    layout = RunLayout(workspace_root=tmp_path, task_id="d-insar-isce3", run_id="d-insar-isce3_run")
    d = layout.to_dict()
    assert d["task_id"] == "d-insar-isce3"
    assert d["run_id"] == "d-insar-isce3_run"
    assert d["run_root"] == str(tmp_path / "d-insar-isce3" / "outputs" / "d-insar-isce3_run")
    assert "products_dir" in d
    assert "mintpy_dir" in d


# ---------------------------------------------------------------------------
# from_job_metadata / infer_from_project
# ---------------------------------------------------------------------------

def test_from_job_metadata(tmp_path):
    layout = RunLayout.from_job_metadata(tmp_path, task_id="stack-insar-isce3", run_id="stack-insar-isce3_abc")
    assert layout.task_id == "stack-insar-isce3"
    assert layout.run_id == "stack-insar-isce3_abc"


def test_infer_from_project_name(tmp_path):
    layout = RunLayout.infer_from_project(tmp_path, project_name="d-insar-isce3")
    assert layout.task_id == "d-insar-isce3"
    assert layout.run_id.startswith("d-insar-isce3_")


def test_infer_from_project_id_fallback(tmp_path):
    layout = RunLayout.infer_from_project(tmp_path, project_id="proj_abc")
    assert layout.task_id == "proj_abc"
