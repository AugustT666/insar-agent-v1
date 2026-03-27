"""Unit tests for M1: Project creation, runconfig management, and validation."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest
import yaml

from insar_agent.core.config import get_path, set_path, unset_path
from insar_agent.core.project import Project, new_project, _load_registry
from insar_agent.engines.isce3.defaults import (
    ALLOWED_SET_FIELDS,
    REQUIRED_PATH_FIELDS,
    load_default_runconfig,
)
from insar_agent.engines.isce3.validator import validate_runconfig
from insar_agent.engines.isce3.runner import build_workflow_command
from insar_agent.mcp.server import (
    insar_create_project,
    insar_get_project,
    insar_get_runconfig,
    insar_list_outputs,
    insar_set_runconfig_value,
    insar_unset_runconfig_value,
    insar_validate_runconfig,
    insar_export_runconfig,
    insar_list_engines,
    insar_list_workflows,
    insar_run_workflow,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    """Redirect the project registry to a temp dir so tests don't pollute the real one."""
    registry_dir = tmp_path / "registry"
    registry_dir.mkdir()
    monkeypatch.setenv("XDG_DATA_HOME", str(registry_dir))


@pytest.fixture()
def workspace(tmp_path):
    return str(tmp_path / "workspace")


@pytest.fixture()
def insar_project(workspace):
    result = insar_create_project(
        engine="isce3",
        workflow="insar",
        workspace_root=workspace,
    )
    assert "project_id" in result, result
    return result


# ── discovery tools ───────────────────────────────────────────────────────────

def test_list_engines():
    result = insar_list_engines()
    assert "engines" in result
    names = [e["name"] for e in result["engines"]]
    assert "isce3" in names


def test_list_workflows_isce3():
    result = insar_list_workflows("isce3")
    assert result["engine"] == "isce3"
    workflow_names = [w["workflow"] for w in result["workflows"]]
    assert "insar" in workflow_names
    assert "gslc" in workflow_names


def test_list_workflows_unknown_engine():
    result = insar_list_workflows("nonexistent")
    assert result["error"] == "engine_not_found"


# ── project creation ──────────────────────────────────────────────────────────

def test_create_project_returns_id(workspace):
    result = insar_create_project(engine="isce3", workflow="insar", workspace_root=workspace)
    assert "project_id" in result
    assert result["engine"] == "isce3"
    assert result["workflow"] == "insar"


def test_create_project_writes_project_json(workspace):
    result = insar_create_project(engine="isce3", workflow="insar", workspace_root=workspace)
    project_file = Path(workspace) / ".insar_agent" / "project.json"
    assert project_file.exists()
    data = json.loads(project_file.read_text())
    assert data["project_id"] == result["project_id"]


def test_create_project_with_conda_env(workspace):
    result = insar_create_project(
        engine="isce3", workflow="insar", workspace_root=workspace, conda_env="isce3"
    )
    assert result["conda_env"] == "isce3"


def test_create_project_unknown_workflow(workspace):
    result = insar_create_project(engine="isce3", workflow="bogus", workspace_root=workspace)
    assert result["error"] == "workflow_not_found"


def test_create_project_unknown_engine(workspace):
    result = insar_create_project(engine="isce2", workflow="insar", workspace_root=workspace)
    assert result["error"] == "engine_not_found"


def test_create_project_auto_creates_workspace(tmp_path):
    ws = str(tmp_path / "new" / "nested" / "workspace")
    result = insar_create_project(engine="isce3", workflow="insar", workspace_root=ws)
    assert "project_id" in result
    assert Path(ws).exists()


# ── runconfig template ────────────────────────────────────────────────────────

def test_default_insar_runconfig_loads():
    rc = load_default_runconfig("insar")
    assert "runconfig" in rc
    assert "groups" in rc["runconfig"]


def test_default_gslc_runconfig_loads():
    rc = load_default_runconfig("gslc")
    assert "runconfig" in rc


def test_create_project_loads_runconfig_template(insar_project):
    result = insar_get_runconfig(insar_project["project_id"])
    assert "runconfig" in result
    rc = result["runconfig"]
    assert "runconfig" in rc
    assert "groups" in rc["runconfig"]
    assert "input_file_group" in rc["runconfig"]["groups"]


# ── get_runconfig ─────────────────────────────────────────────────────────────

def test_get_runconfig_json(insar_project):
    result = insar_get_runconfig(insar_project["project_id"], format="json")
    assert result["format"] == "json"
    assert "runconfig" in result


def test_get_runconfig_yaml(insar_project):
    result = insar_get_runconfig(insar_project["project_id"], format="yaml")
    assert result["format"] == "yaml"
    assert "runconfig_yaml" in result
    parsed = yaml.safe_load(result["runconfig_yaml"])
    assert "runconfig" in parsed


def test_get_runconfig_unknown_project():
    result = insar_get_runconfig("nonexistent-id")
    assert result["error"] == "project_not_found"


# ── set_runconfig_value ───────────────────────────────────────────────────────

def test_set_runconfig_value_allowed(insar_project):
    pid = insar_project["project_id"]
    key = "runconfig.groups.input_file_group.reference_rslc_file"
    result = insar_set_runconfig_value(pid, key, "/data/ref.h5")
    assert result["key"] == key
    assert result["value"] == "/data/ref.h5"

    # Verify persisted
    rc = insar_get_runconfig(pid)["runconfig"]
    assert get_path(rc, key) == "/data/ref.h5"


def test_set_runconfig_value_gpu_flag(insar_project):
    pid = insar_project["project_id"]
    key = "runconfig.groups.worker.gpu_enabled"
    result = insar_set_runconfig_value(pid, key, True)
    assert "error" not in result


def test_set_runconfig_value_blocked_core_param(insar_project):
    pid = insar_project["project_id"]
    # multilook is a core parameter - not in ALLOWED_SET_FIELDS
    result = insar_set_runconfig_value(
        pid, "runconfig.groups.processing.crossmul.range_looks", 5
    )
    assert result["error"] == "key_not_allowed"


def test_set_runconfig_value_unknown_project():
    result = insar_set_runconfig_value(
        "nonexistent", "runconfig.groups.input_file_group.reference_rslc_file", "/x"
    )
    assert result["error"] == "project_not_found"


# ── unset_runconfig_value ─────────────────────────────────────────────────────

def test_unset_runconfig_value(insar_project):
    pid = insar_project["project_id"]
    key = "runconfig.groups.input_file_group.reference_rslc_file"
    insar_set_runconfig_value(pid, key, "/data/ref.h5")
    result = insar_unset_runconfig_value(pid, key)
    assert result["unset"] is True

    rc = insar_get_runconfig(pid)["runconfig"]
    # After unset the key should be gone
    with pytest.raises(KeyError):
        get_path(rc, key)


def test_unset_missing_key(insar_project):
    result = insar_unset_runconfig_value(insar_project["project_id"], "runconfig.groups.bogus.key")
    assert result["error"] == "key_not_found"


# ── validate_runconfig ────────────────────────────────────────────────────────

def test_validate_runconfig_empty_returns_errors(insar_project):
    result = insar_validate_runconfig(insar_project["project_id"])
    assert result["valid"] is False
    assert len(result["errors"]) > 0
    error_keys = [e["key"] for e in result["errors"]]
    assert "runconfig.groups.input_file_group.reference_rslc_file" in error_keys


def test_validate_runconfig_after_setting_all_required(insar_project):
    pid = insar_project["project_id"]
    for key, val in [
        ("runconfig.groups.input_file_group.reference_rslc_file", "/data/ref.h5"),
        ("runconfig.groups.input_file_group.secondary_rslc_file", "/data/sec.h5"),
        ("runconfig.groups.dynamic_ancillary_file_group.dem_file", "/data/dem.tif"),
        ("runconfig.groups.product_path_group.product_path", "/out/products"),
        ("runconfig.groups.product_path_group.scratch_path", "/out/scratch"),
        ("runconfig.groups.product_path_group.sas_output_file", "GUNW_product.h5"),
    ]:
        insar_set_runconfig_value(pid, key, val)

    result = insar_validate_runconfig(pid)
    assert result["valid"] is True, result["errors"]


# ── export_runconfig ──────────────────────────────────────────────────────────

def test_export_runconfig_default_dir(insar_project):
    pid = insar_project["project_id"]
    result = insar_export_runconfig(pid)
    assert "yaml_path" in result
    yaml_path = Path(result["yaml_path"])
    assert yaml_path.exists()
    content = yaml.safe_load(yaml_path.read_text())
    assert "runconfig" in content


def test_export_runconfig_custom_dir(insar_project, tmp_path):
    pid = insar_project["project_id"]
    custom = str(tmp_path / "custom_export")
    result = insar_export_runconfig(pid, output_dir=custom)
    assert Path(result["yaml_path"]).parent == Path(custom)
    assert Path(result["yaml_path"]).exists()


def test_export_runconfig_records_path_on_project(insar_project):
    pid = insar_project["project_id"]
    result = insar_export_runconfig(pid)
    project = Project.load(pid)
    assert project.runconfig_exported_path == result["yaml_path"]


# ── config utilities ──────────────────────────────────────────────────────────

def test_config_get_set_nested():
    data = {"a": {"b": {"c": 1}}}
    assert get_path(data, "a.b.c") == 1
    set_path(data, "a.b.c", 99)
    assert data["a"]["b"]["c"] == 99


def test_config_set_creates_intermediate():
    data = {}
    set_path(data, "x.y.z", "hello")
    assert data == {"x": {"y": {"z": "hello"}}}


def test_config_get_missing_raises():
    with pytest.raises(KeyError):
        get_path({}, "a.b")


def test_config_unset():
    data = {"a": {"b": 1, "c": 2}}
    unset_path(data, "a.b")
    assert data == {"a": {"c": 2}}


# ── runner ────────────────────────────────────────────────────────────────────

def test_build_command_no_conda():
    cmd = build_workflow_command("insar", "/path/to/runconfig.yaml")
    assert cmd == ["python", "-m", "nisar.workflows.insar", "/path/to/runconfig.yaml"]


def test_build_command_with_conda():
    cmd = build_workflow_command("insar", "/path/to/runconfig.yaml", conda_env="isce3")
    assert cmd[0] == "conda"
    assert "isce3" in cmd
    assert "nisar.workflows.insar" in " ".join(cmd)


# ── dry_run ───────────────────────────────────────────────────────────────────

def test_run_workflow_dry_run(insar_project, tmp_path):
    pid = insar_project["project_id"]
    # Set required fields and export
    for key, val in [
        ("runconfig.groups.input_file_group.reference_rslc_file", "/data/ref.h5"),
        ("runconfig.groups.input_file_group.secondary_rslc_file", "/data/sec.h5"),
        ("runconfig.groups.dynamic_ancillary_file_group.dem_file", "/data/dem.tif"),
        ("runconfig.groups.product_path_group.product_path", "/out/products"),
        ("runconfig.groups.product_path_group.scratch_path", "/out/scratch"),
        ("runconfig.groups.product_path_group.sas_output_file", "GUNW_product.h5"),
    ]:
        insar_set_runconfig_value(pid, key, val)
    insar_export_runconfig(pid)

    result = insar_run_workflow(pid, dry_run=True)
    assert result["dry_run"] is True
    assert result["status"] == "dry_run"
    assert "nisar.workflows.insar" in " ".join(result["command"])


def test_run_workflow_no_export_fails(insar_project):
    result = insar_run_workflow(insar_project["project_id"], dry_run=True)
    assert result["error"] == "runconfig_not_exported"


def test_run_workflow_invalid_runconfig_fails(insar_project):
    pid = insar_project["project_id"]
    insar_export_runconfig(pid)
    result = insar_run_workflow(pid, dry_run=True)
    assert result["error"] == "runconfig_invalid"


# ── insar_get_project ─────────────────────────────────────────────────────────

class TestGetProject:
    def test_returns_metadata(self, insar_project):
        pid = insar_project["project_id"]
        result = insar_get_project(pid)
        assert result["project_id"] == pid
        assert result["engine"] == "isce3"
        assert result["workflow"] == "insar"
        assert "workspace_root" in result

    def test_not_found(self):
        result = insar_get_project("nonexistent-id-000")
        assert result.get("error") == "project_not_found"

    def test_fields_match_create(self, insar_project):
        pid = insar_project["project_id"]
        result = insar_get_project(pid)
        assert result["engine"] == insar_project["engine"]
        assert result["workflow"] == insar_project["workflow"]
        assert result["workspace_root"] == insar_project["workspace_root"]


# ── insar_list_outputs ────────────────────────────────────────────────────────

class TestListOutputs:

    def _make_done_job(self, project_id: str) -> str:
        """Launch a mock job, then manually mark it done in the JSON."""
        from unittest.mock import patch, MagicMock
        from insar_agent.core.project import Project

        # Set required fields and export so insar_run_workflow accepts the project
        for key, val in [
            ("runconfig.groups.input_file_group.reference_rslc_file", "/data/ref.h5"),
            ("runconfig.groups.input_file_group.secondary_rslc_file", "/data/sec.h5"),
            ("runconfig.groups.dynamic_ancillary_file_group.dem_file", "/data/dem.tif"),
            ("runconfig.groups.product_path_group.product_path", "/out"),
            ("runconfig.groups.product_path_group.scratch_path", "/scratch"),
            ("runconfig.groups.product_path_group.sas_output_file", "GUNW.h5"),
        ]:
            insar_set_runconfig_value(project_id, key, val)
        insar_export_runconfig(project_id)

        mock_proc = MagicMock()
        mock_proc.pid = 99999
        with patch("insar_agent.mcp.server.subprocess.Popen", return_value=mock_proc):
            result = insar_run_workflow(project_id, dry_run=False)

        # Manually flip status to "done" so list_outputs won't reject it
        project = Project.load(project_id)
        job_file = project.jobs_dir() / f"{result['job_id']}.json"
        data = json.loads(job_file.read_text())
        data["status"] = "done"
        job_file.write_text(json.dumps(data))
        return result["job_id"]

    def test_empty_outputs_dir(self, insar_project):
        pid = insar_project["project_id"]
        job_id = self._make_done_job(pid)
        result = insar_list_outputs(job_id, pid)
        assert result["job_id"] == job_id
        assert result["status"] == "done"
        assert result["outputs"] == []

    def test_files_typed_correctly(self, insar_project, tmp_path):
        pid = insar_project["project_id"]
        job_id = self._make_done_job(pid)

        # Place test files in the outputs/job_id directory
        from insar_agent.core.project import Project
        out_dir = Project.load(pid).outputs_dir() / job_id
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "GUNW_product.h5").write_text("fake")
        (out_dir / "wrapped_phase.tif").write_text("fake")
        (out_dir / "browse.png").write_text("fake")

        result = insar_list_outputs(job_id, pid)
        paths_by_type = {a["artifact_type"]: a["path"] for a in result["outputs"]}
        assert "hdf5" in paths_by_type
        assert "geotiff" in paths_by_type
        assert "preview" in paths_by_type

    def test_job_not_done_returns_error(self, insar_project):
        pid = insar_project["project_id"]
        from unittest.mock import patch, MagicMock
        for key, val in [
            ("runconfig.groups.input_file_group.reference_rslc_file", "/data/ref.h5"),
            ("runconfig.groups.input_file_group.secondary_rslc_file", "/data/sec.h5"),
            ("runconfig.groups.dynamic_ancillary_file_group.dem_file", "/data/dem.tif"),
            ("runconfig.groups.product_path_group.product_path", "/out"),
            ("runconfig.groups.product_path_group.scratch_path", "/scratch"),
            ("runconfig.groups.product_path_group.sas_output_file", "GUNW.h5"),
        ]:
            insar_set_runconfig_value(pid, key, val)
        insar_export_runconfig(pid)
        mock_proc = MagicMock()
        mock_proc.pid = 11111
        with patch("insar_agent.mcp.server.subprocess.Popen", return_value=mock_proc):
            result = insar_run_workflow(pid, dry_run=False)
        # Job is still "running" — list_outputs should reject it
        status_result = insar_list_outputs(result["job_id"], pid)
        assert status_result.get("error") == "job_not_done"

    def test_project_not_found(self):
        result = insar_list_outputs("fake-job-id", "nonexistent-project")
        assert result.get("error") == "project_not_found"

    def test_job_not_found(self, insar_project):
        pid = insar_project["project_id"]
        result = insar_list_outputs("nonexistent-job-id", pid)
        assert result.get("error") == "job_not_found"
