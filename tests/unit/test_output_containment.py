"""Structural regression lock for the unified output tree.

The hard rule (see docs/architecture.md and the integration dev-plan): every file
a processing run produces must live under

    <workspace>/<task_id>/outputs/<run_id>/

Nothing may be written as a sibling of the run dir: no <ws>/isce2_dem, no
<ws>/.insar_logs, no <ws>/<task_id>/outputs/configs, no stray run_* dirs.

``escaped_artifacts`` is a reusable tree walker that any output-producing path can
be driven against. The tests drive the real MCP prepare tools (the public contract
the plugin must honour) plus the isce2 DEM materialiser, then assert nothing leaks.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from insar_agent.engines.isce2.runner import materialize_dem_for_tops
from insar_agent.mcp.server import insar_prepare_network, insar_prepare_stack

_NISAR_NAME = (
    "NISAR_L1_PR_RSLC_005_172_A_008_2005_DHDH_A_{date}T024618_{date}T024652"
    "_X05007_N_F_J_001_cropped.h5"
)


def _make_rslc(data_dir: Path, date: str) -> Path:
    p = data_dir / _NISAR_NAME.format(date=date)
    p.write_bytes(b"")
    return p


def _fixture_runconfig(tmp_path: Path) -> Path:
    fixture = Path("tests/fixtures/insar_nisar.yaml")
    if not fixture.exists():
        pytest.skip("Fixture tests/fixtures/insar_nisar.yaml not found")
    dest = tmp_path / "insar_nisar.yaml"
    dest.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")
    return dest


def escaped_artifacts(workspace_root: Path, task_id: str) -> list[Path]:
    """Return every file written outside the run-dir contract under *workspace_root*.

    Contained ⇔ the file sits under ``<ws>/<task_id>/outputs/<run_id>/...`` (one
    run-id level beneath ``outputs``) or is project/job bookkeeping under
    ``<ws>/<task_id>/.insar_agent/`` or ``<ws>/<task_id>/sessions/``. Everything
    else is an escape.
    """
    ws = Path(workspace_root).resolve()
    offenders: list[Path] = []
    for path in ws.rglob("*"):
        if path.is_dir():
            continue
        parts = path.relative_to(ws).parts
        if len(parts) < 2:
            offenders.append(path)            # loose file at workspace root
            continue
        task, child, *rest = parts
        if task != task_id:
            offenders.append(path)            # unexpected top-level dir
            continue
        if child in (".insar_agent", "sessions"):
            continue                          # bookkeeping is allowed
        if child != "outputs":
            offenders.append(path)            # e.g. <ws>/<task>/isce2_dem/...
            continue
        if len(rest) < 2:
            offenders.append(path)            # outputs/<loose> or outputs/configs
    return offenders


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


# ---------------------------------------------------------------------------
# MCP prepare tools (the public contract) must scatter nothing.
# ---------------------------------------------------------------------------

def test_prepare_stack_mcp_contains_all_artifacts(workspace, tmp_path):
    data_dir = tmp_path / "rslc"
    data_dir.mkdir()
    _make_rslc(data_dir, "20251122")
    _make_rslc(data_dir, "20251204")
    dem = tmp_path / "dem.tif"
    dem.write_bytes(b"")

    result = insar_prepare_stack(
        data_dir=str(data_dir),
        base_runconfig=str(_fixture_runconfig(tmp_path)),
        dem=str(dem),
        output_dir="",
        workspace_root=str(workspace),
        interaction_mode="auto",
    )

    assert "error" not in result
    escapes = escaped_artifacts(workspace, "stack-insar-isce3")
    assert escapes == [], f"insar_prepare_stack leaked: {escapes}"


def test_prepare_network_mcp_contains_all_artifacts(workspace, tmp_path):
    data_dir = tmp_path / "rslc"
    data_dir.mkdir()
    _make_rslc(data_dir, "20251122")
    _make_rslc(data_dir, "20251204")
    dem = tmp_path / "dem.tif"
    dem.write_bytes(b"")

    result = insar_prepare_network(
        data_dir=str(data_dir),
        base_runconfig=str(_fixture_runconfig(tmp_path)),
        dem=str(dem),
        output_dir="",
        workspace_root=str(workspace),
        interaction_mode="auto",
    )

    assert "error" not in result
    escapes = escaped_artifacts(workspace, "stack-insar-isce3")
    assert escapes == [], f"insar_prepare_network leaked: {escapes}"


# ---------------------------------------------------------------------------
# Leak #1: isce2 DEM materialiser must place the copy under the run dir.
# materialize_dem_for_tops(dem_file, run_root) -> writes <run_root>/isce2_dem/.
# ---------------------------------------------------------------------------

def test_materialize_dem_stays_under_run_root(workspace):
    run_root = workspace / "d-insar-isce2" / "outputs" / "d-insar-isce2_run1"
    src = workspace / "ext_dem"        # external DEM dir, not a run artifact
    src.mkdir()
    dem = src / "dem.tif"
    dem.write_bytes(b"dem")
    (src / "dem.tif.xml").write_text(
        '<image_name><property name="file_name"><value>/stale/dem.tif</value>'
        "</property></image_name>",
        encoding="utf-8",
    )
    (src / "dem.tif.vrt").write_text(
        '<VRTDataset><SourceFilename relativeToVRT="1">dem.tif</SourceFilename>'
        "</VRTDataset>",
        encoding="utf-8",
    )

    out = materialize_dem_for_tops(str(dem), run_root)

    assert Path(out) == run_root / "isce2_dem" / "dem.tif"
    # The materialised copy + sidecars must all be inside the run root.
    produced = [p for p in (workspace / "d-insar-isce2").rglob("*") if p.is_file()]
    escapes = escaped_artifacts(workspace, "d-insar-isce2")
    # The external src/ files are deliberately outside the contract; ignore them.
    escapes = [p for p in escapes if src not in p.parents]
    assert escapes == [], f"materialize_dem_for_tops leaked: {escapes}"
    assert all(run_root in p.parents for p in produced if src not in p.parents)
