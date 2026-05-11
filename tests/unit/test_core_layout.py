"""Unit tests for src/insar_agent/core/layout.py."""
from __future__ import annotations

import pytest

from insar_agent.core.layout import (
    RunLayout,
    make_run_id,
    sanitize_identifier,
    validate_workspace_root,
)


# ---------------------------------------------------------------------------
# make_run_id
# ---------------------------------------------------------------------------

def test_make_run_id_format():
    rid = make_run_id("E1")
    # Must start with task_id
    assert rid.startswith("E1_")
    # Timestamp part: 15 chars YYYYMMDDTHHMMSSz
    parts = rid.split("_", 1)
    assert len(parts) == 2
    ts = parts[1]
    assert len(ts) == 16  # YYYYMMDDTHHMMSSz
    assert ts.endswith("Z")


def test_make_run_id_sanitizes():
    rid = make_run_id("E1 task/test")
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


def test_validate_workspace_root_rejects_outputs_nested(tmp_path):
    bad = tmp_path / "outputs" / "E1" / "E1_20260511T000000Z"
    with pytest.raises(ValueError, match="outputs"):
        validate_workspace_root(bad)


def test_validate_workspace_root_rejects_products_nested(tmp_path):
    bad = tmp_path / "outputs" / "E1" / "run1" / "products"
    with pytest.raises(ValueError, match="outputs"):
        validate_workspace_root(bad)


# ---------------------------------------------------------------------------
# RunLayout path generation
# ---------------------------------------------------------------------------

def test_run_layout_paths(tmp_path):
    layout = RunLayout(workspace_root=tmp_path, task_id="E1", run_id="E1_test")
    assert layout.run_root == tmp_path / "outputs" / "E1" / "E1_test"
    assert layout.products_dir == layout.run_root / "products"
    assert layout.scratch_dir == layout.run_root / "scratch"
    assert layout.configs_dir == layout.run_root / "configs"
    assert layout.logs_dir == layout.run_root / "logs"
    assert layout.param_advisor_dir == layout.run_root / "param_advisor"
    assert layout.metrics_dir == layout.run_root / "metrics"
    assert layout.browse_dir == layout.run_root / "browse"
    assert layout.stack_dir == layout.run_root / "stack"
    assert layout.mintpy_dir == layout.run_root / "mintpy"


def test_run_layout_auto_run_id(tmp_path):
    layout = RunLayout(workspace_root=tmp_path, task_id="E2")
    assert layout.run_id.startswith("E2_")
    assert layout.run_root.parent.name == "E2"


def test_run_layout_sanitizes_task_id(tmp_path):
    layout = RunLayout(workspace_root=tmp_path, task_id="E 1/test", run_id="myrun")
    assert layout.task_id == "E_1_test"


# ---------------------------------------------------------------------------
# workspace root safety via RunLayout
# ---------------------------------------------------------------------------

def test_run_layout_rejects_nested_workspace(tmp_path):
    bad_ws = tmp_path / "outputs" / "E1" / "runid"
    with pytest.raises(ValueError):
        RunLayout(workspace_root=bad_ws, task_id="E1", run_id="x")


# ---------------------------------------------------------------------------
# validate_path_inside_workspace
# ---------------------------------------------------------------------------

def test_validate_path_inside_workspace_ok(tmp_path):
    layout = RunLayout(workspace_root=tmp_path, task_id="E1", run_id="r1")
    p = layout.validate_path_inside_workspace(layout.products_dir)
    assert p == layout.products_dir.resolve()


def test_validate_path_inside_workspace_rejects_outside(tmp_path, tmp_path_factory):
    other = tmp_path_factory.mktemp("other")
    layout = RunLayout(workspace_root=tmp_path, task_id="E1", run_id="r1")
    with pytest.raises(ValueError, match="outside workspace_root"):
        layout.validate_path_inside_workspace(other / "evil.h5")


# ---------------------------------------------------------------------------
# to_dict
# ---------------------------------------------------------------------------

def test_run_layout_to_dict(tmp_path):
    layout = RunLayout(workspace_root=tmp_path, task_id="E1", run_id="E1_run")
    d = layout.to_dict()
    assert d["task_id"] == "E1"
    assert d["run_id"] == "E1_run"
    assert d["run_root"] == str(tmp_path / "outputs" / "E1" / "E1_run")
    assert "products_dir" in d
    assert "mintpy_dir" in d


# ---------------------------------------------------------------------------
# from_job_metadata / infer_from_project
# ---------------------------------------------------------------------------

def test_from_job_metadata(tmp_path):
    layout = RunLayout.from_job_metadata(tmp_path, task_id="E3", run_id="E3_abc")
    assert layout.task_id == "E3"
    assert layout.run_id == "E3_abc"


def test_infer_from_project_name(tmp_path):
    layout = RunLayout.infer_from_project(tmp_path, project_name="nisar_test")
    assert layout.task_id == "nisar_test"
    assert layout.run_id.startswith("nisar_test_")


def test_infer_from_project_id_fallback(tmp_path):
    layout = RunLayout.infer_from_project(tmp_path, project_id="proj_abc")
    assert layout.task_id == "proj_abc"
