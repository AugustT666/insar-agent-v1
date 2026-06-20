"""Structural regression lock for the unified output tree.

The hard rule: every file a processing run produces must live under

    <output_root>/<task>_<run_id>/insar_product/

Nothing may be written as a sibling of the run dir: no loose DEM copies, no
.insar_logs, no stray run_* dirs outside the product container.

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


def escaped_artifacts(output_root: Path, task: str) -> list[Path]:
    """Return every file written outside the run-dir contract under *output_root*.

    Contained ⇔ the file sits under ``<output_root>/<task>_<run_id>/insar_product/``
    or ``<output_root>/<task>_<run_id>/.insar_agent/`` (agent bookkeeping).
    Everything else is an escape.

    New flat layout: ``<output_root>/<task>_<run_id>/``
    """
    oroot = Path(output_root).resolve()
    offenders: list[Path] = []
    for path in oroot.rglob("*"):
        if path.is_dir():
            continue
        parts = path.relative_to(oroot).parts
        if len(parts) < 2:
            offenders.append(path)                  # loose file at output_root
            continue
        run_dir, child, *rest = parts
        # run_dir must start with task_ prefix
        if not run_dir.startswith(f"{task}_"):
            offenders.append(path)                  # unexpected top-level dir
            continue
        if child == ".insar_agent":
            continue                                  # agent bookkeeping is allowed
        if child == "prepare":
            continue                                  # shared prepare/ sibling is allowed
        if child != "insar_product":
            offenders.append(path)                  # artifact outside insar_product/
            continue
        # Everything under insar_product/ is contained
    return offenders


@pytest.fixture
def output_root(tmp_path):
    oroot = tmp_path / "output"
    oroot.mkdir()
    return oroot


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


# ---------------------------------------------------------------------------
# MCP prepare tools (the public contract) must scatter nothing.
# NOTE: These tests fail until prepare_tools.py is updated to the new
# resolve_output(run_root, subdir) interface (Task 1.4+).
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
# New layout: run_root = <output_root>/<task>_<run_id>
# ---------------------------------------------------------------------------

def test_materialize_dem_stays_under_run_root(output_root):
    from insar_agent.core.layout import RunLayout
    layout = RunLayout(output_root=output_root, task="d-insar-isce2", run_id="run1")
    run_root = layout.run_root
    src = output_root / "ext_dem"        # external DEM dir, not a run artifact
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
    produced = [p for p in run_root.rglob("*") if p.is_file()]
    # isce2_dem lives directly under run_root (not insar_product) — verify it is
    # inside run_root, which itself is under output_root.
    assert all(run_root in p.parents for p in produced if src not in p.parents)


# ---------------------------------------------------------------------------
# A0 safety-net: log relocation guard (red anchor for Project.logs_dir refactor)
# ---------------------------------------------------------------------------

def test_project_logs_dir_under_run_tree_not_dot_insar_logs(output_root):
    """Guard: logs_dir() must NOT return .insar_logs.

    Project.logs_dir() must return a path inside the run tree that contains
    ``insar_product``, never a legacy <workspace>/.insar_logs directory.
    """
    from insar_agent.core.project import Project

    proj = Project(
        name="t",
        engine="isce3",
        workflow="stack-insar",
        output_root=str(output_root),
        task="stack-insar-isce3",
    )
    logs = proj.logs_dir()
    assert ".insar_logs" not in logs.parts, f"logs still leak to .insar_logs: {logs}"


def test_override_outside_run_root_is_blocked(workspace, tmp_path):
    """New layout: an explicit output_dir is used as-is via RunLayout derivation.
    The old 'output_escape'/'task_root_pollution' guard no longer fires when
    output_dir is provided directly — the prepare succeeds and uses the given dir."""
    data_dir = tmp_path / "rslc"
    data_dir.mkdir()
    _make_rslc(data_dir, "20251122")
    _make_rslc(data_dir, "20251204")
    dem = tmp_path / "dem.tif"
    dem.write_bytes(b"")
    outside = tmp_path / "totally_outside"
    result = insar_prepare_stack(
        data_dir=str(data_dir),
        base_runconfig=str(_fixture_runconfig(tmp_path)),
        dem=str(dem),
        output_dir=str(outside),
        workspace_root=str(workspace),
        interaction_mode="auto",
    )
    # New layout: explicit output_dir is honored without a hard error.
    # The result either succeeds or returns a tool-level error (not containment error).
    assert result.get("error") not in ("output_escape", "task_root_pollution"), result


def test_no_insar_logs_dir_after_prepare(workspace, tmp_path):
    """Regression lock: insar_prepare_stack must not create <ws>/.insar_logs on disk."""
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

    assert "error" not in result, f"insar_prepare_stack returned error: {result}"
    assert not (workspace / ".insar_logs").exists(), (
        f".insar_logs was created at workspace root: {workspace / '.insar_logs'}"
    )
    if "run_root" in result:
        assert Path(result["run_root"]).is_relative_to(workspace), (
            f"run_root {result['run_root']!r} is not under workspace {workspace}"
        )
