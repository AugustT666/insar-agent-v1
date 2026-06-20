"""Unit tests for the central output resolver (Task 1.3 new flat layout)."""
from __future__ import annotations

import json

import pytest

from insar_agent.core.layout import RunLayout
from insar_agent.core.output_resolver import (
    OutputEscapeError,
    _layout_from_run_root,
    enforce_inside_run,
    param_advice_output_dir,
    prepare_input_dir,
    resolve_output,
    resolve_run_layout,
    run_logs_dir,
)
from insar_agent.core.project import Project


@pytest.fixture
def output_root(tmp_path):
    oroot = tmp_path / "outputs"
    oroot.mkdir()
    return oroot


def _make_run(output_root, task, run_id):
    """Create a minimal run directory with marker file."""
    layout = RunLayout(output_root=output_root, task=task, run_id=run_id)
    (layout.run_root / ".insar_agent").mkdir(parents=True, exist_ok=True)
    (layout.run_root / ".insar_agent" / "project.json").write_text(
        json.dumps({"output_root": str(output_root), "task": task, "run_id": run_id}),
        encoding="utf-8",
    )
    return layout


# ---------------------------------------------------------------------------
# Core: resolve_output(run_root, subdir) -> Path
# ---------------------------------------------------------------------------

def test_resolve_output_in_insar_product(tmp_path):
    run = tmp_path / "stack-insar-isce2_r1"
    (run / ".insar_agent").mkdir(parents=True)
    (run / ".insar_agent" / "project.json").write_text(
        '{"output_root":"%s","task":"stack-insar-isce2","run_id":"r1"}' % tmp_path
    )
    out = resolve_output(run, "stack")
    assert out == run / "insar_product" / "stack"


def test_resolve_output_returns_path_under_insar_product(output_root):
    layout = _make_run(output_root, "d-insar-isce2", "r1")
    out = resolve_output(layout.run_root, "dem")
    assert out == layout.run_root / "insar_product" / "dem"


def test_resolve_output_any_subdir(output_root):
    layout = _make_run(output_root, "d-insar-isce2", "r1")
    for sub in ("stack", "logs", "network", "mintpy", "exports", "custom"):
        assert resolve_output(layout.run_root, sub) == layout.run_root / "insar_product" / sub


def test_resolve_output_nested_subdir(output_root):
    layout = _make_run(output_root, "d-insar-isce2", "r1")
    out = resolve_output(layout.run_root, "nested/deep")
    assert out == layout.run_root / "insar_product" / "nested/deep"


# ---------------------------------------------------------------------------
# _layout_from_run_root: reads .insar_agent/project.json
# ---------------------------------------------------------------------------

def test_layout_from_run_root_reads_marker(output_root):
    layout = _make_run(output_root, "stack-insar-isce2", "run1")
    recovered = _layout_from_run_root(layout.run_root)
    assert recovered is not None
    assert recovered.output_root == output_root.resolve()
    assert recovered.task == "stack-insar-isce2"
    assert recovered.run_id == "run1"
    assert recovered.run_root == layout.run_root


def test_layout_from_run_root_returns_none_without_marker(tmp_path):
    no_marker = tmp_path / "some-dir"
    no_marker.mkdir()
    assert _layout_from_run_root(no_marker) is None


def test_layout_from_run_root_returns_none_with_incomplete_json(tmp_path):
    run = tmp_path / "task_run1"
    (run / ".insar_agent").mkdir(parents=True)
    (run / ".insar_agent" / "project.json").write_text(
        '{"output_root": "/some/root"}',  # missing task and run_id
        encoding="utf-8",
    )
    assert _layout_from_run_root(run) is None


# ---------------------------------------------------------------------------
# enforce_inside_run
# ---------------------------------------------------------------------------

def test_enforce_inside_run_returns_path_when_contained(output_root):
    layout = _make_run(output_root, "t", "r1")
    child = layout.run_root / "insar_product" / "products" / "x.h5"
    assert enforce_inside_run(child, layout) == child


def test_enforce_inside_run_raises_when_outside(output_root, tmp_path):
    layout = _make_run(output_root, "t", "r1")
    with pytest.raises(OutputEscapeError):
        enforce_inside_run(tmp_path / "nope", layout)


def test_enforce_inside_run_allows_run_root_itself(output_root):
    layout = _make_run(output_root, "t", "r1")
    assert enforce_inside_run(layout.run_root, layout) == layout.run_root


def test_enforce_strict_disabled_allows_escape(output_root, tmp_path, monkeypatch):
    monkeypatch.setenv("INSAR_STRICT_OUTPUT", "0")
    layout = _make_run(output_root, "t", "r1")
    outside = tmp_path / "elsewhere"
    result = enforce_inside_run(outside, layout)
    assert result == outside


# ---------------------------------------------------------------------------
# resolve_child (on RunLayout — tests containment guard)
# ---------------------------------------------------------------------------

def test_resolve_child_blocks_traversal(output_root):
    layout = _make_run(output_root, "t", "r1")
    with pytest.raises(ValueError):
        layout.resolve_child("..", "..", "escape")


# ---------------------------------------------------------------------------
# resolve_run_layout: from Project with pinned run_id
# ---------------------------------------------------------------------------

def test_resolve_run_layout_prefers_pinned_run_id(output_root):
    proj = Project(
        name="t",
        engine="isce3",
        workflow="insar",
        output_root=str(output_root),
        task_id="d-insar-isce3",
        run_id="PINNED",
    )
    layout = resolve_run_layout(proj)
    assert layout is not None
    assert layout.run_id == "PINNED"


def test_resolve_run_layout_recovers_from_runconfig_path(output_root):
    """resolve_run_layout falls back to find_run_root scanning runconfig paths."""
    run_layout = _make_run(output_root, "d-insar-isce2", "run99")
    proj = Project(
        name="d-insar-isce2",
        engine="isce2",
        workflow="d-insar",
        output_root=str(output_root),
        task_id="d-insar-isce2",
    )
    # Stamp a runconfig path that points into the run
    proj.runconfig = {
        "runconfig": {
            "groups": {
                "product_path_group": {
                    "product_path": str(run_layout.products_dir)
                }
            }
        }
    }
    layout = resolve_run_layout(proj)
    assert layout is not None
    assert layout.run_id == "run99"


# ---------------------------------------------------------------------------
# run_logs_dir: new kwargs output_root + task (not workspace_root + task_id)
# ---------------------------------------------------------------------------

def test_run_logs_dir_under_insar_product(output_root):
    p = run_logs_dir(output_root=str(output_root), task="d-insar-isce2", run_id="r1")
    expected = output_root / "d-insar-isce2_r1" / "insar_product" / "logs"
    assert p == expected


def test_run_logs_dir_autogenerated_run_id(output_root):
    p = run_logs_dir(output_root=str(output_root), task="d-insar-isce2")
    assert "insar_product" in p.parts
    assert "logs" in p.parts


# ---------------------------------------------------------------------------
# param_advice_output_dir: must land in insar_product/param_advisor
# ---------------------------------------------------------------------------

def test_param_advice_output_dir_prefers_pinned_run(output_root):
    """param-advisor output must join the project's pinned run."""
    proj = Project(
        name="t",
        engine="isce2",
        workflow="topsapp",
        output_root=str(output_root),
        task_id="d-insar-isce2",
        run_id="PINNED",
    )
    p = param_advice_output_dir(proj, output_dir="", task_id="d-insar-isce2")
    expected = output_root / "d-insar-isce2_PINNED" / "insar_product" / "param_advisor"
    assert p == expected


def test_param_advice_output_dir_explicit_path_is_returned(output_root):
    proj = Project(
        name="t",
        engine="isce2",
        workflow="topsapp",
        output_root=str(output_root),
        task_id="d-insar-isce2",
    )
    explicit = output_root / "custom_dir"
    p = param_advice_output_dir(proj, output_dir=str(explicit), task_id="d-insar-isce2")
    assert p == explicit


def test_param_advice_output_dir_outside_workspace_raises(output_root, tmp_path):
    proj = Project(
        name="t",
        engine="isce2",
        workflow="topsapp",
        output_root=str(output_root),
        task_id="d-insar-isce2",
    )
    outside = tmp_path / "outside"
    with pytest.raises(ValueError, match="outside workspace_root"):
        param_advice_output_dir(proj, output_dir=str(outside), task_id="d-insar-isce2")


# ---------------------------------------------------------------------------
# prepare_input_dir: shared prepare/ input resolver
# ---------------------------------------------------------------------------

def test_prepare_input_dir(tmp_path):
    assert prepare_input_dir(tmp_path, "dem") == tmp_path / "prepare" / "dem"
    assert prepare_input_dir(tmp_path, "safe") == tmp_path / "prepare" / "safe"
