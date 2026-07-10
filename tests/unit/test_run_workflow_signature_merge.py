"""Gap-fix regression: insar_run_workflow must keep BOTH generate_only (C2) and
from_step/to_step (C4), and forward all four extras to _run_workflow_isce2.

Guards against C4 Task 2 rewriting the signature and dropping C2's generate_only
(which would TypeError any C2 caller passing generate_only=...).
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
    for name in ("resume_from_run", "generate_only", "from_step", "to_step"):
        assert name in params, f"insar_run_workflow dropped {name!r}"
    assert params["generate_only"].default is False
    assert params["from_step"].default == ""
    assert params["to_step"].default == ""


def test_internal_signature_keeps_generate_only_and_step_range():
    params = inspect.signature(_run_workflow_isce2).parameters
    for name in ("resume_from_run", "generate_only", "from_step", "to_step"):
        assert name in params, f"_run_workflow_isce2 dropped {name!r}"
    assert params["generate_only"].default is False
    assert params["from_step"].default == ""
    assert params["to_step"].default == ""


def test_dispatch_forwards_all_four_extras_to_isce2(tmp_path):
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
