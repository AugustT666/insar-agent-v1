from __future__ import annotations

import json
from pathlib import Path

import pytest

from insar_agent.mcp.server import (
    insar_create_project,
    insar_record_param_advice,
    insar_set_runconfig_value,
)


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "registry"))


def test_record_param_advice_writes_json_and_markdown_under_product_path(tmp_path):
    workspace = tmp_path / "workspace"
    result = insar_create_project(engine="isce3", workflow="insar", workspace_root=str(workspace))
    project_id = result["project_id"]
    # New layout: <workspace>/<task_id>/outputs/<run_id>/products
    product_dir = workspace / "d-insar-isce3" / "outputs" / "d-insar-isce3_20260511T001500" / "products"
    insar_set_runconfig_value(
        project_id,
        "runconfig.groups.product_path_group.product_path",
        str(product_dir),
    )

    package = {
        "advisory_only": True,
        "summary": "Use deformation-mode SNAPHU for active rift deformation.",
        "changes": [
            {
                "key": "runconfig.groups.processing.phase_unwrap.snaphu.cost_mode",
                "current_value": "smooth",
                "default_value": "smooth",
                "suggested_value": "defo",
                "risk": "medium",
                "confidence": "medium",
                "justification": "External geology context indicates active rifting.",
                "provenance": {
                    "local_metadata": ["NISAR L-band 12-day baseline"],
                    "external_references": ["USGS regional geology"],
                },
                "sources": [
                    {
                        "title": "USGS regional geology",
                        "url": "https://example.invalid/usgs",
                        "why_it_was_used": "study-area tectonic context",
                        "recommended_authority": "USGS",
                    }
                ],
            }
        ],
        "sources": [],
        "external_context": {
            "study_area_name": "Afar Rift",
            "geology_or_tectonic_setting": "active rift",
            "known_deformation_context": "tectonic and volcanic deformation",
            "land_cover_or_climate_context": "arid",
            "sensor_revisit_cycle": "12 days",
            "sensor_resolution_or_pixel_spacing": "metadata-derived",
            "sensor_wavelength_or_band": "L-band",
            "context_confidence": "medium",
            "sources": [],
        },
        "yaml_diff_preview": "phase_unwrap:\n  snaphu:\n    cost_mode: defo\n",
        "user_responsibility_notice": "Advisory only.",
    }

    record = insar_record_param_advice(project_id, package, task_id="E1_20260511T001500")

    assert "error" not in record
    json_path = Path(record["recommendation_json"])
    markdown_path = Path(record["recommendation_markdown"])
    # New layout: param_advisor goes to workspace/<task_id>/outputs/<run_id>/param_advisor/
    # (or inside the product_dir run-root if product_path already has run_id structure)
    assert json_path.name == "recommendation.json"
    assert markdown_path.name == "recommendation.md"
    assert "param_advisor" in json_path.parts
    # New layout: param_advisor is under workspace/<task_id>/outputs/<run_id>/param_advisor/
    assert json_path.is_relative_to(workspace / "d-insar-isce3" / "outputs")
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["format_version"] == "param-advisor.v1"
    assert data["recommendation_package"]["external_context"]["study_area_name"] == "Afar Rift"
    assert "cost_mode" in markdown_path.read_text(encoding="utf-8")


def test_record_param_advice_rejects_invalid_format_version(tmp_path):
    workspace = tmp_path / "workspace"
    result = insar_create_project(engine="isce3", workflow="insar", workspace_root=str(workspace))

    record = insar_record_param_advice(
        result["project_id"],
        {"summary": "test"},
        format_version="param-advisor.v1`\n# injected",
    )

    assert record["error"] == "invalid_format_version"
    assert not list(workspace.glob("**/recommendation.*"))


def test_record_param_advice_rejects_output_dir_outside_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    result = insar_create_project(engine="isce3", workflow="insar", workspace_root=str(workspace))

    record = insar_record_param_advice(
        result["project_id"],
        {"summary": "test"},
        output_dir=str(outside),
    )

    assert record["error"] == "invalid_output_dir"
    assert not outside.exists()


def test_record_param_advice_sanitizes_task_id_fallback(tmp_path):
    workspace = tmp_path / "workspace"
    result = insar_create_project(engine="isce3", workflow="insar", workspace_root=str(workspace))

    record = insar_record_param_advice(
        result["project_id"],
        {"summary": "test"},
        task_id="../evil task",
    )

    assert "error" not in record
    advice_dir = Path(record["advice_dir"])
    assert advice_dir.resolve().is_relative_to(workspace.resolve())
    assert ".." not in advice_dir.parts
    assert "../evil task" not in str(advice_dir)
