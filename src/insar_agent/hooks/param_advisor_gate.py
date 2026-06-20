"""Param-advisor enforcement hook logic.

Two responsibilities, both driven by Claude Code hook payloads on stdin:

* ``decide_execution_gate`` — PreToolUse gate on the irreversible execution tools
  (insar_run_workflow / insar_prepare_stack / insar_prepare_network). It denies
  the call unless the param-advisor subagent has been consulted this session (a
  marker written by ``record_advisor_marker``) or a recommendation has already
  been recorded for the run. dry-run workflow calls are always allowed.

* ``record_advisor_marker`` — PostToolUse hook on the Task tool. When the
  subagent that just ran was the param-advisor, it writes the session marker.

The gate enforces *process* (the advisor must be consulted), never parameter
*values*: after consulting, accepting the default parameters is allowed.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

_ADVISOR_HINT = "param-advisor"
_EXEC_TOOL_SUFFIXES = ("insar_run_workflow", "insar_prepare_stack", "insar_prepare_network")


def marker_dir() -> Path:
    base = os.environ.get("TMPDIR") or "/tmp"
    return Path(base) / "insar_param_advisor_gate"


def marker_path(session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "unknown")
    return marker_dir() / f"{safe}.consulted"


def record_advisor_marker(payload: dict) -> bool:
    """Write the session marker iff the Task subagent was the param-advisor."""
    tool_input = payload.get("tool_input") or {}
    subagent_type = str(tool_input.get("subagent_type") or "")
    if _ADVISOR_HINT not in subagent_type:
        return False
    path = marker_path(str(payload.get("session_id") or ""))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(datetime.now(UTC).isoformat(), encoding="utf-8")
    return True


def _decision(verdict: str, reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": verdict,
            "permissionDecisionReason": reason,
        }
    }


def _is_execution_tool(tool_name: str) -> bool:
    return any(tool_name.endswith(suffix) for suffix in _EXEC_TOOL_SUFFIXES)


def _recommendation_recorded(project_id: str) -> bool:
    if not project_id:
        return False
    try:
        from insar_agent.core.output_resolver import param_advice_output_dir
        from insar_agent.core.project import Project

        project = Project.load(project_id)
        advice_dir = param_advice_output_dir(project, "", "")
        return (advice_dir / "recommendation.json").exists()
    except Exception:
        return False


def decide_execution_gate(payload: dict) -> dict:
    tool_name = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input") or {}

    # A dry-run workflow is non-destructive and is itself part of the advisor flow.
    if tool_name.endswith("insar_run_workflow") and bool(tool_input.get("dry_run")):
        return _decision("allow", "dry_run is non-destructive")

    if not _is_execution_tool(tool_name):
        return _decision("allow", "not an irreversible execution tool")

    session_id = str(payload.get("session_id") or "")
    if marker_path(session_id).exists():
        return _decision("allow", "param-advisor subagent was consulted this session")

    if _recommendation_recorded(str(tool_input.get("project_id") or "")):
        return _decision("allow", "a param-advisor recommendation is already recorded for this run")

    return _decision(
        "deny",
        "Blocked: the param-advisor subagent has not been consulted for this run. "
        "Enter the param-advisor skill and invoke the insar-agent-plugin:param-advisor "
        "subagent first; you may still accept the default parameters afterward, then retry.",
    )


def main_gate() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # never block on malformed hook input
    decision = decide_execution_gate(payload)
    if decision["hookSpecificOutput"]["permissionDecision"] == "deny":
        print(json.dumps(decision))
    sys.exit(0)


def main_marker() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    record_advisor_marker(payload)
    sys.exit(0)
