"""Task 3.2c focused tests: param/product/job tools use insar_product/ dirs.

Write these FIRST (TDD). They should FAIL before the implementation and PASS after.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from insar_agent.core.jobs import DownloadJob
from insar_agent.core.project import Project
from insar_agent.mcp.server import (
    insar_create_project,
    insar_export_runconfig,
    insar_get_job,
    insar_record_param_advice,
)


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "registry"))


# ---------------------------------------------------------------------------
# Test 1: param advice lands under insar_product/param_advisor
# ---------------------------------------------------------------------------

def test_param_advice_under_insar_product(tmp_path):
    """insar_record_param_advice output is under <run_root>/insar_product/param_advisor/."""
    result = insar_create_project(
        engine="isce3",
        workflow="insar",
        output_root=str(tmp_path / "out"),
    )
    assert "error" not in result, f"create_project failed: {result}"
    pid = result["project_id"]

    package = {
        "advisory_only": True,
        "summary": "test advice",
        "changes": [],
        "sources": [],
        "external_context": {},
        "yaml_diff_preview": "",
        "user_responsibility_notice": "Advisory only.",
    }
    record = insar_record_param_advice(pid, package)

    assert "error" not in record, f"record_param_advice failed: {record}"
    json_path = Path(record["recommendation_json"])
    assert "insar_product" in json_path.parts, (
        f"expected 'insar_product' in path parts, got: {json_path}"
    )
    assert "param_advisor" in json_path.parts, (
        f"expected 'param_advisor' in path parts, got: {json_path}"
    )


# ---------------------------------------------------------------------------
# Test 2: export_runconfig default dir lands under insar_product/configs
# ---------------------------------------------------------------------------

def test_export_runconfig_default_under_insar_product(tmp_path):
    """insar_export_runconfig default output is under <run_root>/insar_product/configs/."""
    result = insar_create_project(
        engine="isce3",
        workflow="insar",
        output_root=str(tmp_path / "out"),
    )
    assert "error" not in result, f"create_project failed: {result}"
    pid = result["project_id"]

    res = insar_export_runconfig(pid)
    assert "error" not in res, f"export_runconfig failed: {res}"
    yaml_path = Path(res["yaml_path"])
    assert "insar_product" in yaml_path.parts, (
        f"expected 'insar_product' in path parts, got: {yaml_path}"
    )
    assert "configs" in yaml_path.parts, (
        f"expected 'configs' in path parts, got: {yaml_path}"
    )


# ---------------------------------------------------------------------------
# Test 3: DownloadJob round-trips via insar_get_job(project_id, job_id)
# ---------------------------------------------------------------------------

def test_download_job_roundtrip_via_project_id(tmp_path):
    """A DownloadJob written to project.jobs_dir() is findable by project_id."""
    result = insar_create_project(
        engine="isce3",
        workflow="insar",
        output_root=str(tmp_path / "out"),
    )
    assert "error" not in result, f"create_project failed: {result}"
    pid = result["project_id"]

    project = Project.load(pid)
    jobs_dir = project.jobs_dir()
    jobs_dir.mkdir(parents=True, exist_ok=True)

    dl = DownloadJob(
        output_dir=str(tmp_path),
        n_files=1,
        tool_name="insar_download_dem",
        job_type="dem_download",
    )
    dl.save(jobs_dir)

    # Retrieve via insar_get_job with project_id (should find DownloadJob)
    res = insar_get_job(project_id=pid, job_id=dl.job_id)
    assert "error" not in res, f"insar_get_job failed: {res}"
    assert res.get("job_id") == dl.job_id, f"job_id mismatch: {res}"
