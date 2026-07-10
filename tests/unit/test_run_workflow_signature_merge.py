"""Gap-fix regression: insar_run_workflow must keep generate_only (C2),
from_step/to_step (C4), and start_step/end_step (PSF-final), and forward all
six extras to _run_workflow_isce2.

Guards against a future signature rewrite dropping any earlier extra (which
would TypeError any caller still passing it).
"""
from __future__ import annotations

import inspect
from unittest.mock import patch

from insar_agent.mcp.server import (
    _run_workflow_isce2,
    insar_create_project,
    insar_run_workflow,
)


def test_public_signature_keeps_generate_only_and_step_range():
    params = inspect.signature(insar_run_workflow).parameters
    for name in ("resume_from_run", "generate_only", "from_step", "to_step", "start_step", "end_step"):
        assert name in params, f"insar_run_workflow dropped {name!r}"
    assert params["generate_only"].default is False
    assert params["from_step"].default == ""
    assert params["to_step"].default == ""
    assert params["start_step"].default == 0
    assert params["end_step"].default == 0


def test_internal_signature_keeps_generate_only_and_step_range():
    params = inspect.signature(_run_workflow_isce2).parameters
    for name in ("resume_from_run", "generate_only", "from_step", "to_step", "start_step", "end_step"):
        assert name in params, f"_run_workflow_isce2 dropped {name!r}"
    assert params["generate_only"].default is False
    assert params["from_step"].default == ""
    assert params["to_step"].default == ""
    assert params["start_step"].default == 0
    assert params["end_step"].default == 0


def test_dispatch_forwards_all_six_extras_to_isce2(tmp_path):
    proj = insar_create_project(
        engine="isce2",
        workflow="stack",
        workspace_root=str(tmp_path / "ws"),
        conda_env="isce2",
    )
    pid = proj["project_id"]
    with patch(
        "insar_agent.mcp.server._run_workflow_isce2", return_value={"ok": True}
    ) as m:
        insar_run_workflow(
            pid,
            dry_run=True,
            resume_from_run=0,
            generate_only=True,
            from_step="step_a",
            to_step="step_b",
        )
    assert m.called
    _, kwargs = m.call_args
    assert kwargs["resume_from_run"] == 0
    assert kwargs["generate_only"] is True
    assert kwargs["from_step"] == "step_a"
    assert kwargs["to_step"] == "step_b"
    assert kwargs["start_step"] == 0
    assert kwargs["end_step"] == 0


def test_dispatch_forwards_start_end_step_to_isce2(tmp_path):
    proj = insar_create_project(
        engine="isce2",
        workflow="stack",
        workspace_root=str(tmp_path / "ws"),
        conda_env="isce2",
    )
    pid = proj["project_id"]
    with patch(
        "insar_agent.mcp.server._run_workflow_isce2", return_value={"ok": True}
    ) as m:
        insar_run_workflow(
            pid,
            dry_run=True,
            start_step=5,
            end_step=8,
        )
    assert m.called
    _, kwargs = m.call_args
    assert kwargs["start_step"] == 5
    assert kwargs["end_step"] == 8
    assert kwargs["resume_from_run"] == 0
    assert kwargs["generate_only"] is False
