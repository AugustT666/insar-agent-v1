"""Structural regression lock for the unified output tree.

The hard rule (see docs/architecture.md and the integration dev-plan): every file
a processing run produces must live under

    <workspace>/<task_id>/outputs/<run_id>/

Nothing may be written as a sibling of the run dir: no <ws>/isce2_dem, no
<ws>/.insar_logs, no <ws>/<task_id>/outputs/configs, no stray run_* dirs.

This module provides a reusable walker, ``escaped_artifacts``, that every output
producing code path can be driven against. Phase 2 of the refactor wires every
tool/engine through ``core.output_resolver`` and flips the xfail markers below to
hard assertions.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from insar_agent.engines.isce2 import runner as isce2_runner
from insar_agent.engines.isce3 import network as network_mod
from insar_agent.engines.isce3 import stack as stack_mod

# Structural dirs allowed directly under <ws>/<task_id>/ (not processing output).
_ALLOWED_TASK_CHILDREN = {".insar_agent", "outputs", "sessions"}


def escaped_artifacts(workspace_root: Path, task_id: str) -> list[Path]:
    """Return every file written outside the run dir contract.

    A path is *contained* iff it sits under ``<ws>/<task_id>/outputs/<run_id>/``
    (run_id = any single directory level under ``outputs``) or is project/job
    bookkeeping under ``<ws>/<task_id>/.insar_agent/``. Anything else is an escape.
    """
    ws = Path(workspace_root).resolve()
    offenders: list[Path] = []
    for path in ws.rglob("*"):
        if path.is_dir():
            continue
        rel = path.relative_to(ws)
        parts = rel.parts
        # Files directly under the workspace root (e.g. ws/isce2_dem/...) — escape
        # unless they live under a recognised task dir.
        if len(parts) < 2:
            offenders.append(path)
            continue
        task, child, *rest = parts
        if task != task_id:
            # Artifacts under an unexpected top-level dir are escapes too.
            offenders.append(path)
            continue
        if child == ".insar_agent":
            continue  # project.json / jobs bookkeeping is allowed here
        if child == "sessions":
            continue
        if child != "outputs":
            offenders.append(path)  # e.g. ws/<task_id>/isce2_dem/... — escape
            continue
        # Under outputs/: must be outputs/<run_id>/...  (>= one run-id level + file)
        if len(rest) < 2:
            offenders.append(path)  # e.g. outputs/loose_file or outputs/configs
    return offenders


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


def _make_rslc(path: Path, dt: str) -> None:
    path.write_text(f"rslc {dt}")


# ---------------------------------------------------------------------------
# Code paths that already comply (these must stay green through the refactor).
# ---------------------------------------------------------------------------

def test_prepare_stack_keeps_all_artifacts_inside_run_dir(workspace):
    ref = workspace / "ref.h5"
    sec = workspace / "sec.h5"
    _make_rslc(ref, "20230101")
    _make_rslc(sec, "20230113")
    # Inputs created at workspace root for the test are not run artifacts; remove
    # them from consideration by checking only what prepare_stack adds.
    before = {p for p in workspace.rglob("*") if p.is_file()}

    stack_mod.prepare_stack(
        workspace_root=str(workspace),
        reference=str(ref),
        secondaries=[str(sec)],
        dem=None,
        task_id="stack-insar-isce3",
    )

    produced = {p for p in workspace.rglob("*") if p.is_file()} - before
    escapes = [p for p in escaped_artifacts(workspace, "stack-insar-isce3") if p in produced]
    assert escapes == [], f"prepare_stack leaked artifacts: {escapes}"


def test_prepare_network_keeps_all_artifacts_inside_run_dir(workspace):
    rslcs = []
    for dt in ("20230101", "20230113", "20230125"):
        p = workspace / f"{dt}.h5"
        _make_rslc(p, dt)
        rslcs.append(str(p))
    before = {p for p in workspace.rglob("*") if p.is_file()}

    network_mod.prepare_network(
        workspace_root=str(workspace),
        rslcs=rslcs,
        dem=None,
        task_id="stack-insar-isce3",
        max_temporal_baseline=20,
    )

    produced = {p for p in workspace.rglob("*") if p.is_file()} - before
    escapes = [p for p in escaped_artifacts(workspace, "stack-insar-isce3") if p in produced]
    assert escapes == [], f"prepare_network leaked artifacts: {escapes}"


# ---------------------------------------------------------------------------
# Known leaks — documented as expected failures until Phase 2 fixes them.
# Removing the xfail markers is part of Phase 2's success criteria.
# ---------------------------------------------------------------------------

@pytest.mark.xfail(
    reason="leak #1: materialize_dem_for_tops writes <ws>/isce2_dem; fixed in Phase 2",
    strict=True,
)
def test_materialize_dem_does_not_escape_run_dir(workspace):
    dem = workspace / "srtm_dem.tif"
    dem.write_text("fake dem")
    task_id = "d-insar-isce2"

    isce2_runner.materialize_dem_for_tops(
        workspace_root=str(workspace),
        dem_path=str(dem),
    )

    # The input DEM at ws root is not a run artifact; the materialised copy is.
    offenders = [p for p in escaped_artifacts(workspace, task_id) if p.name != "srtm_dem.tif"]
    assert offenders == [], f"materialize_dem_for_tops leaked: {offenders}"
