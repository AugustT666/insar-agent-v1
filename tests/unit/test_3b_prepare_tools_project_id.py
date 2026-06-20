"""Part B TDD tests: prepare_tools project_id migration.

Tests cover the new insar_prepare_stack / insar_prepare_network behaviour after
the project_id caller-migration (task 3.2 Part B):

1. insar_prepare_stack with project_id returns stack_dir == run_root/insar_product/stack.
2. insar_prepare_network with project_id returns network_dir == run_root/insar_product/network.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from insar_agent.mcp.tools.prepare_tools import insar_prepare_stack, insar_prepare_network


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, engine="isce3", workflow="insar"):
    """Create a project, returning project_id and output_root."""
    from insar_agent.mcp.server import insar_create_project

    registry_dir = tmp_path / ".registry"
    registry_dir.mkdir()
    monkeypatch.setenv("XDG_DATA_HOME", str(registry_dir))

    output_root = tmp_path / "output"
    result = insar_create_project(
        engine=engine,
        workflow=workflow,
        workspace_root=str(output_root),
    )
    assert "error" not in result, result
    return result["project_id"], output_root


def make_rslc(data_dir: Path, date: str) -> Path:
    name = (
        f"NISAR_L1_PR_RSLC_005_172_A_008_2005_DHDH_A_{date}T024618_{date}T024652"
        "_X05007_N_F_J_001_cropped.h5"
    )
    p = data_dir / name
    p.write_bytes(b"")
    return p


def make_dem(tmp_path: Path) -> Path:
    dem = tmp_path / "dem.tif"
    dem.write_bytes(b"")
    return dem


def make_fixture_runconfig(tmp_path: Path) -> Path:
    fixture = Path("tests/fixtures/insar_nisar.yaml")
    if not fixture.exists():
        pytest.skip("Fixture tests/fixtures/insar_nisar.yaml not found")
    dest = tmp_path / "insar_nisar.yaml"
    dest.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")
    return dest


# ---------------------------------------------------------------------------
# insar_prepare_stack: project_id → stack_dir == run_root/insar_product/stack
# ---------------------------------------------------------------------------

def test_prepare_stack_with_project_id_returns_insar_product_stack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """insar_prepare_stack(project_id=...) must return stack_dir under run_root/insar_product/stack."""
    project_id, output_root = _make_project(tmp_path, monkeypatch)

    data_dir = tmp_path / "rslc"
    data_dir.mkdir()
    make_rslc(data_dir, "20251122")
    make_rslc(data_dir, "20251204")
    runconfig = make_fixture_runconfig(tmp_path)
    dem = make_dem(tmp_path)

    result = insar_prepare_stack(
        data_dir=str(data_dir),
        base_runconfig=str(runconfig),
        dem=str(dem),
        project_id=project_id,
        interaction_mode="auto",
    )

    assert "error" not in result, result
    run_root = Path(result["run_root"])
    stack_dir = Path(result["stack_dir"])
    assert stack_dir == run_root / "insar_product" / "stack", (
        f"Expected run_root/insar_product/stack, got {stack_dir}"
    )


# ---------------------------------------------------------------------------
# insar_prepare_network: project_id → network_dir == run_root/insar_product/network
# ---------------------------------------------------------------------------

def test_prepare_network_with_project_id_returns_insar_product_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """insar_prepare_network(project_id=...) must return network_dir under run_root/insar_product/network."""
    project_id, output_root = _make_project(tmp_path, monkeypatch)

    data_dir = tmp_path / "rslc"
    data_dir.mkdir()
    make_rslc(data_dir, "20251122")
    make_rslc(data_dir, "20251204")
    runconfig = make_fixture_runconfig(tmp_path)
    dem = make_dem(tmp_path)

    result = insar_prepare_network(
        data_dir=str(data_dir),
        base_runconfig=str(runconfig),
        dem=str(dem),
        project_id=project_id,
        interaction_mode="auto",
    )

    assert "error" not in result, result
    run_root = Path(result["run_root"])
    network_dir = Path(result["network_dir"])
    assert network_dir == run_root / "insar_product" / "network", (
        f"Expected run_root/insar_product/network, got {network_dir}"
    )
