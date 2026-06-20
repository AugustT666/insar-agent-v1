"""Task 2.1: Project state lives inside the run dir.

Tests verify that `Project` uses `output_root` (not `workspace_root`) and
that `insar_dir()` / `jobs_dir()` / `configs_dir()` / `logs_dir()` all resolve
to paths under `<output_root>/<task>_<run_id>/.insar_agent`.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from insar_agent.core.project import new_project, Project


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    reg_dir = tmp_path / "reg"
    reg_dir.mkdir()
    monkeypatch.setenv("XDG_DATA_HOME", str(reg_dir))


# ---------------------------------------------------------------------------
# Core layout test (verbatim from brief)
# ---------------------------------------------------------------------------

def test_project_state_inside_run_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "reg"))
    (tmp_path / "reg").mkdir(exist_ok=True)
    from insar_agent.core.project import new_project
    p = new_project(name="t", engine="isce2", workflow="stack", output_root=str(tmp_path / "out"))
    p.save()
    assert p.insar_dir() == p.run_root() / ".insar_agent"
    assert (p.insar_dir() / "project.json").exists()


# ---------------------------------------------------------------------------
# Field rename: output_root replaces workspace_root
# ---------------------------------------------------------------------------

def test_project_has_output_root_field(tmp_path):
    p = new_project(
        name="t",
        engine="isce2",
        workflow="stack",
        output_root=str(tmp_path / "out"),
    )
    assert hasattr(p, "output_root")
    assert p.output_root == str(tmp_path / "out")


def test_project_workspace_root_is_not_a_dataclass_field(tmp_path):
    """workspace_root must NOT be a stored dataclass field (only output_root is)."""
    p = new_project(
        name="t",
        engine="isce2",
        workflow="stack",
        output_root=str(tmp_path / "out"),
    )
    # workspace_root must not appear in the dataclass fields
    assert "workspace_root" not in p.__dataclass_fields__


# ---------------------------------------------------------------------------
# run_root() method
# ---------------------------------------------------------------------------

def test_run_root_is_output_root_task_run_id(tmp_path):
    p = new_project(
        name="t",
        engine="isce2",
        workflow="stack",
        output_root=str(tmp_path / "out"),
        task="stack-insar-isce2",
        run_id="20260620T010203Z",
    )
    assert p.run_root() == Path(tmp_path / "out" / "stack-insar-isce2_20260620T010203Z")


# ---------------------------------------------------------------------------
# insar_dir(), jobs_dir() under run_root
# ---------------------------------------------------------------------------

def test_insar_dir_is_run_root_dot_insar_agent(tmp_path):
    p = new_project(
        name="t",
        engine="isce2",
        workflow="stack",
        output_root=str(tmp_path / "out"),
        task="stack-insar-isce2",
        run_id="20260620T010203Z",
    )
    assert p.insar_dir() == p.run_root() / ".insar_agent"


def test_jobs_dir_is_under_insar_dir(tmp_path):
    p = new_project(
        name="t",
        engine="isce2",
        workflow="stack",
        output_root=str(tmp_path / "out"),
        task="stack-insar-isce2",
        run_id="20260620T010203Z",
    )
    assert p.jobs_dir() == p.insar_dir() / "jobs"


# ---------------------------------------------------------------------------
# configs_dir() and logs_dir() via RunLayout (under insar_product/)
# ---------------------------------------------------------------------------

def test_configs_dir_is_under_insar_product(tmp_path):
    p = new_project(
        name="t",
        engine="isce2",
        workflow="stack",
        output_root=str(tmp_path / "out"),
        task="stack-insar-isce2",
        run_id="20260620T010203Z",
    )
    # configs_dir must be inside <run_root>/insar_product/
    assert p.configs_dir().is_relative_to(p.run_root() / "insar_product")


def test_logs_dir_is_under_insar_product(tmp_path):
    p = new_project(
        name="t",
        engine="isce2",
        workflow="stack",
        output_root=str(tmp_path / "out"),
        task="stack-insar-isce2",
        run_id="20260620T010203Z",
    )
    assert p.logs_dir().is_relative_to(p.run_root() / "insar_product")


# ---------------------------------------------------------------------------
# save() writes project.json into insar_dir()
# ---------------------------------------------------------------------------

def test_save_writes_project_json_into_insar_dir(tmp_path):
    p = new_project(
        name="t",
        engine="isce2",
        workflow="stack",
        output_root=str(tmp_path / "out"),
        task="stack-insar-isce2",
        run_id="20260620T010203Z",
    )
    p.save()
    project_file = p.insar_dir() / "project.json"
    assert project_file.exists()


def test_project_json_contains_required_keys(tmp_path):
    p = new_project(
        name="t",
        engine="isce2",
        workflow="stack",
        output_root=str(tmp_path / "out"),
        task="stack-insar-isce2",
        run_id="20260620T010203Z",
    )
    p.save()
    data = json.loads((p.insar_dir() / "project.json").read_text())
    assert "output_root" in data
    assert "task" in data
    assert "run_id" in data
    assert data["output_root"] == str(tmp_path / "out")
    assert data["task"] == "stack-insar-isce2"
    assert data["run_id"] == "20260620T010203Z"


def test_project_json_no_workspace_root_key(tmp_path):
    p = new_project(
        name="t",
        engine="isce2",
        workflow="stack",
        output_root=str(tmp_path / "out"),
        task="stack-insar-isce2",
        run_id="20260620T010203Z",
    )
    p.save()
    data = json.loads((p.insar_dir() / "project.json").read_text())
    assert "workspace_root" not in data


# ---------------------------------------------------------------------------
# Project.load() round-trips through registry
# ---------------------------------------------------------------------------

def test_project_load_roundtrip(tmp_path):
    p = new_project(
        name="t",
        engine="isce2",
        workflow="stack",
        output_root=str(tmp_path / "out"),
        task="stack-insar-isce2",
        run_id="20260620T010203Z",
    )
    p.save()
    loaded = Project.load(p.project_id)
    assert loaded.output_root == str(tmp_path / "out")
    assert loaded.task == "stack-insar-isce2"
    assert loaded.run_id == "20260620T010203Z"
    assert loaded.run_root() == p.run_root()


def test_project_load_drops_unknown_keys(tmp_path):
    """Old project.json with extra unknown keys must load without error."""
    p = new_project(
        name="t",
        engine="isce2",
        workflow="stack",
        output_root=str(tmp_path / "out"),
        task="stack-insar-isce2",
        run_id="20260620T010203Z",
    )
    p.save()
    project_file = p.insar_dir() / "project.json"
    data = json.loads(project_file.read_text())
    data["unknown_future_key"] = "some_value"
    project_file.write_text(json.dumps(data))

    loaded = Project.load(p.project_id)
    assert loaded.output_root == str(tmp_path / "out")
