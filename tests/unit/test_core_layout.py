"""Unit tests for src/insar_agent/core/layout.py."""
from __future__ import annotations

from pathlib import Path

import pytest

from insar_agent.core.layout import (
    RunLayout,
    find_run_root,
    infer_run_root,
    make_run_id,
    sanitize_identifier,
    validate_output_root,
)


# ---------------------------------------------------------------------------
# make_run_id
# ---------------------------------------------------------------------------

def test_make_run_id_format():
    rid = make_run_id()
    # Now returns just a timestamp: YYYYMMDDTHHMMSSz (16 chars)
    assert len(rid) == 16
    assert rid.endswith("Z")
    assert "T" in rid


def test_make_run_id_no_task_prefix():
    """make_run_id must return ONLY the timestamp — no task prefix."""
    rid = make_run_id()
    # Should not contain underscores (no task_<timestamp> folding)
    assert "_" not in rid


def test_sanitize_identifier_removes_path_separators_and_whitespace():
    assert sanitize_identifier(" ../E1 task/test ") == "___E1_task_test"


# ---------------------------------------------------------------------------
# validate_output_root
# ---------------------------------------------------------------------------

def test_validate_output_root_ok(tmp_path):
    out = validate_output_root(tmp_path)
    assert out == tmp_path.resolve()


def test_validate_output_root_rejects_run_root(tmp_path):
    """A path that looks like <output_root>/<task>_<run_id> should be rejected."""
    bad = tmp_path / "d-insar-isce2_20260511T000000Z"
    bad.mkdir(parents=True)
    # Simulate a run dir marker
    (bad / ".insar_agent").mkdir()
    with pytest.raises(ValueError):
        validate_output_root(bad)


def test_validate_output_root_accepts_plain_path(tmp_path):
    good = validate_output_root(tmp_path)
    assert good == tmp_path.resolve()


# ---------------------------------------------------------------------------
# RunLayout path generation — new flat layout
# ---------------------------------------------------------------------------

def test_run_root_flat_under_output_root():
    rl = RunLayout("/out", "stack-insar-isce2", "20260620T010203Z")
    assert rl.run_root == Path("/out/stack-insar-isce2_20260620T010203Z")
    assert rl.insar_product_dir == rl.run_root / "insar_product"
    assert rl.agent_state_dir == rl.run_root / ".insar_agent"
    assert rl.progress_path == rl.run_root / ".insar_agent" / "progress.log"
    assert rl.jobs_dir == rl.run_root / ".insar_agent" / "jobs"
    assert rl.prepare_dir == Path("/out/prepare")
    for n in ("products", "scratch", "configs", "logs", "stack", "network", "mintpy", "exports", "param_advisor"):
        assert getattr(rl, f"{n}_dir") == rl.insar_product_dir / n


def test_run_layout_product_subdirs_under_insar_product(tmp_path):
    layout = RunLayout(output_root=tmp_path, task="d-insar-isce3", run_id="20260620T010203Z")
    ip = layout.insar_product_dir
    assert layout.products_dir == ip / "products"
    assert layout.scratch_dir == ip / "scratch"
    assert layout.configs_dir == ip / "configs"
    assert layout.logs_dir == ip / "logs"
    assert layout.stack_dir == ip / "stack"
    assert layout.network_dir == ip / "network"
    assert layout.mintpy_dir == ip / "mintpy"
    assert layout.exports_dir == ip / "exports"
    assert layout.param_advisor_dir == ip / "param_advisor"
    assert layout.param_tuned_dir == ip / "param_tuned"
    assert layout.troposphere_dir == ip / "troposphere"


def test_run_layout_prepare_dir_sibling(tmp_path):
    layout = RunLayout(output_root=tmp_path, task="stack-insar-isce2", run_id="20260620T010203Z")
    assert layout.prepare_dir == tmp_path / "prepare"
    assert layout.prepare_dir / "dem" == tmp_path / "prepare" / "dem"
    assert layout.prepare_dir / "orbits" == tmp_path / "prepare" / "orbits"
    assert layout.prepare_dir / "safe" == tmp_path / "prepare" / "safe"


def test_run_layout_agent_state_dir_and_progress(tmp_path):
    layout = RunLayout(output_root=tmp_path, task="d-insar-isce2", run_id="20260620T010203Z")
    assert layout.agent_state_dir == layout.run_root / ".insar_agent"
    assert layout.progress_path == layout.agent_state_dir / "progress.log"
    assert layout.jobs_dir == layout.agent_state_dir / "jobs"


def test_browse_dir_alias_returns_exports_dir(tmp_path):
    layout = RunLayout(output_root=tmp_path, task="d-insar-isce2", run_id="20260620T010203Z")
    # browse_dir is a deprecated alias for exports_dir
    assert layout.browse_dir == layout.exports_dir


def test_run_layout_run_root_naming(tmp_path):
    layout = RunLayout(output_root=tmp_path, task="d-insar-isce2", run_id="20260620T010203Z")
    assert layout.run_root == tmp_path / "d-insar-isce2_20260620T010203Z"


def test_run_layout_auto_run_id(tmp_path):
    layout = RunLayout(output_root=tmp_path, task="d-insar-isce2")
    # run_id is a pure timestamp; run_root is <output_root>/<task>_<run_id>
    assert "_" not in layout.run_id  # pure timestamp
    assert layout.run_root == tmp_path / f"d-insar-isce2_{layout.run_id}"


def test_run_layout_sanitizes_task(tmp_path):
    layout = RunLayout(output_root=tmp_path, task="d insar/isce3", run_id="20260620T010203Z")
    assert layout.task == "d_insar_isce3"
    layout2 = RunLayout(output_root=tmp_path, task="d-insar-isce3", run_id="20260620T010203Z")
    assert layout2.task == "d-insar-isce3"


# ---------------------------------------------------------------------------
# validate_path_inside_workspace (now inside output_root)
# ---------------------------------------------------------------------------

def test_validate_path_inside_workspace_ok(tmp_path):
    layout = RunLayout(output_root=tmp_path, task="d-insar-isce3", run_id="20260620T010203Z")
    p = layout.validate_path_inside_workspace(layout.products_dir)
    assert p == layout.products_dir.resolve()


def test_validate_path_inside_workspace_rejects_outside(tmp_path, tmp_path_factory):
    other = tmp_path_factory.mktemp("other")
    layout = RunLayout(output_root=tmp_path, task="d-insar-isce3", run_id="20260620T010203Z")
    with pytest.raises(ValueError, match="outside"):
        layout.validate_path_inside_workspace(other / "evil.h5")


# ---------------------------------------------------------------------------
# to_dict
# ---------------------------------------------------------------------------

def test_run_layout_to_dict(tmp_path):
    layout = RunLayout(output_root=tmp_path, task="d-insar-isce3", run_id="20260620T010203Z")
    d = layout.to_dict()
    assert d["task"] == "d-insar-isce3"
    assert d["run_id"] == "20260620T010203Z"
    assert d["run_root"] == str(tmp_path / "d-insar-isce3_20260620T010203Z")
    assert d["output_root"] == str(tmp_path)
    assert "products_dir" in d
    assert "mintpy_dir" in d
    assert "exports_dir" in d
    assert "agent_state_dir" in d
    assert "prepare_dir" in d


# ---------------------------------------------------------------------------
# from_job_metadata / infer_from_project (updated signatures)
# ---------------------------------------------------------------------------

def test_from_job_metadata(tmp_path):
    layout = RunLayout.from_job_metadata(tmp_path, task="stack-insar-isce3", run_id="20260620T010203Z")
    assert layout.task == "stack-insar-isce3"
    assert layout.run_id == "20260620T010203Z"


def test_infer_from_project_name(tmp_path):
    layout = RunLayout.infer_from_project(tmp_path, project_name="d-insar-isce3")
    assert layout.task == "d-insar-isce3"
    # run_id is pure timestamp
    assert "_" not in layout.run_id


def test_infer_from_project_id_fallback(tmp_path):
    layout = RunLayout.infer_from_project(tmp_path, project_id="proj_abc")
    assert layout.task == "proj_abc"


# ---------------------------------------------------------------------------
# infer_run_root — still works with new layout (no "outputs" segment)
# ---------------------------------------------------------------------------

def test_infer_run_root_returns_none_for_new_layout(tmp_path):
    """find_run_root returns None when no .insar_agent/project.json marker exists above the path,
    and returns the run dir when the marker IS present.
    """
    # Tree with no marker anywhere: find_run_root must return None.
    no_marker_dir = tmp_path / "run_no_marker" / "insar_product" / "stack"
    no_marker_dir.mkdir(parents=True)
    assert find_run_root(no_marker_dir) is None

    # Tree WITH a marker: find_run_root must return the run directory.
    run_dir = tmp_path / "run_with_marker"
    (run_dir / ".insar_agent").mkdir(parents=True)
    (run_dir / ".insar_agent" / "project.json").write_text("{}")
    deep_path = run_dir / "insar_product" / "logs" / "insar_workflow.log"
    deep_path.parent.mkdir(parents=True)
    deep_path.write_text("log")
    assert find_run_root(deep_path) == run_dir


# ---------------------------------------------------------------------------
# mkdir_all creates correct directories under new layout
# ---------------------------------------------------------------------------

def test_mkdir_all_creates_insar_product_subdirs(tmp_path):
    layout = RunLayout(output_root=tmp_path, task="d-insar-isce2", run_id="20260620T010203Z")
    layout.mkdir_all()
    # Core product subdirs should exist under insar_product/
    assert layout.insar_product_dir.exists()
    assert layout.products_dir.exists()
    assert layout.scratch_dir.exists()
    assert layout.configs_dir.exists()
    assert layout.logs_dir.exists()
    # agent_state_dir should also exist
    assert layout.agent_state_dir.exists()


def test_mkdir_all_does_not_pollute_output_root(tmp_path):
    layout = RunLayout(output_root=tmp_path, task="d-insar-isce2", run_id="20260620T010203Z")
    layout.mkdir_all()
    # Sibling dirs like products/, scratch/ should NOT appear in output_root
    for sibling in ("products", "scratch", "configs", "logs"):
        assert not (tmp_path / sibling).exists()


# ---------------------------------------------------------------------------
# find_run_root — marker-file run-root recovery
# ---------------------------------------------------------------------------

def test_find_run_root_walks_to_marker(tmp_path):
    run = tmp_path / "stack-insar-isce2_r1"
    (run / ".insar_agent").mkdir(parents=True)
    (run / ".insar_agent" / "project.json").write_text("{}")
    deep = run / "insar_product" / "stack" / "scratch"
    deep.mkdir(parents=True)
    assert find_run_root(deep) == run
    assert find_run_root(tmp_path) is None
