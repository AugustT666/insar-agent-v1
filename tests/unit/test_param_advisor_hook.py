"""Enforcement hook: the param-advisor subagent must be consulted before any
irreversible execution step (insar_run_workflow / insar_prepare_stack /
insar_prepare_network).

The gate enforces *process*, not parameter *values*: it never locks a value, it
only requires that the param-advisor subagent ran this session (a PostToolUse
``Task`` hook writes a session marker) — or that a recommendation was already
recorded for the run. After consulting, accepting defaults is allowed.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from insar_agent.hooks import param_advisor_gate as gate

REPO = Path(__file__).resolve().parents[2]
HOOKS_JSON = REPO / "hooks" / "hooks.json"

EXEC_TOOLS = ["insar_run_workflow", "insar_prepare_stack", "insar_prepare_network"]
NAMESPACES = ["mcp__insar-agent__", "mcp__plugin_insar-agent-plugin_insar-mcp-server__"]


def _hooks() -> dict:
    return json.loads(HOOKS_JSON.read_text())["hooks"]


# ── hooks.json contract ───────────────────────────────────────────────────────

def test_pretooluse_matchers_cover_both_tool_namespaces():
    pre = _hooks()["PreToolUse"]
    for tool in EXEC_TOOLS:
        names = [ns + tool for ns in NAMESPACES]
        assert any(
            all(re.search(h["matcher"], n) for n in names) for h in pre
        ), f"no PreToolUse matcher covers both namespaces for {tool}"


def test_pretooluse_gate_blocks_instead_of_echo():
    pre = _hooks()["PreToolUse"]
    cmds = [hk.get("command", "") for entry in pre for hk in entry["hooks"] if hk.get("type") == "command"]
    assert any("param_advisor_gate" in c for c in cmds), f"gate script not wired: {cmds}"
    assert not any(c.strip().startswith("echo") for c in cmds), "execution gate must block, not echo"


def test_posttooluse_marks_param_advisor_subagent():
    post = _hooks().get("PostToolUse", [])
    task_entries = [e for e in post if re.search(e.get("matcher", ""), "Task")]
    assert task_entries, "no PostToolUse hook on the Task tool to record advisor consultation"
    cmds = [hk.get("command", "") for e in task_entries for hk in e["hooks"]]
    assert any("param_advisor_gate" in c or "advisor_marker" in c for c in cmds), cmds


# ── gate logic ────────────────────────────────────────────────────────────────

def _exec_payload(session_id="s-test", dry_run=False, project_id="missing-project"):
    return {
        "session_id": session_id,
        "tool_name": "mcp__plugin_insar-agent-plugin_insar-mcp-server__insar_run_workflow",
        "tool_input": {"project_id": project_id, "dry_run": dry_run},
    }


def test_gate_denies_when_advisor_not_consulted(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    out = gate.decide_execution_gate(_exec_payload(session_id="s-deny"))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "param-advisor" in out["hookSpecificOutput"]["permissionDecisionReason"].lower()


def test_gate_allows_after_advisor_subagent_ran(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    wrote = gate.record_advisor_marker(
        {"session_id": "s-ok", "tool_input": {"subagent_type": "insar-agent-plugin:param-advisor"}}
    )
    assert wrote is True
    out = gate.decide_execution_gate(_exec_payload(session_id="s-ok"))
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_gate_allows_dry_run_without_consultation(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    out = gate.decide_execution_gate(_exec_payload(session_id="s-dry", dry_run=True))
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_marker_not_written_for_other_subagents(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    wrote = gate.record_advisor_marker(
        {"session_id": "s-other", "tool_input": {"subagent_type": "code-reviewer"}}
    )
    assert wrote is False
    out = gate.decide_execution_gate(_exec_payload(session_id="s-other"))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
