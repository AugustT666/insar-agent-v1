"""Unit tests for the param-write gate + insar_arm_param_write arming tool.

The PreToolUse param-write gate DENIES insar_set_processing_param until the skill
arms the run via insar_arm_param_write. Markers key on project_id (an MCP tool
cannot see the harness session_id). A single arm authorizes all writes this run.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from insar_agent.hooks import param_advisor_gate as gate
from insar_agent.mcp.server import insar_arm_param_write, insar_create_project

REPO = Path(__file__).resolve().parents[2]
HOOKS_JSON = REPO / "hooks" / "hooks.json"
SKILL_DIR = REPO / "skills"
NAMESPACES = ["mcp__insar-agent__", "mcp__plugin_insar-agent-plugin_insar-mcp-server__"]


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "registry"))
    (tmp_path / "registry").mkdir()


def _write_payload(project_id: str) -> dict:
    return {
        "tool_name": "mcp__plugin_insar-agent-plugin_insar-mcp-server__insar_set_processing_param",
        "tool_input": {"project_id": project_id, "key": "x", "value": 1, "justification": "y"},
    }


# ── hooks.json contract (matcher ships together) ─────────────────────────────

def test_hooks_json_gates_set_processing_param_both_namespaces():
    pre = json.loads(HOOKS_JSON.read_text())["hooks"]["PreToolUse"]
    names = [ns + "insar_set_processing_param" for ns in NAMESPACES]
    assert any(
        all(re.search(h["matcher"], n) for n in names)
        and any("param_write_gate" in hk.get("command", "") for hk in h["hooks"])
        for h in pre
    ), "no PreToolUse matcher wires param_write_gate for insar_set_processing_param across both namespaces"


def test_hooks_json_does_not_regress_exec_gate():
    pre = json.loads(HOOKS_JSON.read_text())["hooks"]["PreToolUse"]
    names = [ns + "insar_run_workflow" for ns in NAMESPACES]
    assert any(all(re.search(h["matcher"], n) for n in names) for h in pre), "execution gate matcher was dropped"


# ── gate logic keyed by project_id ───────────────────────────────────────────

def test_gate_denies_when_not_armed(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    out = gate.decide_param_write_gate(_write_payload("proj-deny"))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "insar_arm_param_write" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_gate_allows_after_confirm_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    assert gate.record_param_confirm_marker("proj-confirm") is True
    out = gate.decide_param_write_gate(_write_payload("proj-confirm"))
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_gate_allows_after_auto_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    assert gate.record_auto_marker("proj-auto") is True
    out = gate.decide_param_write_gate(_write_payload("proj-auto"))
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_single_arm_authorizes_multiple_writes(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    gate.record_param_confirm_marker("proj-multi")
    for _ in range(3):
        out = gate.decide_param_write_gate(_write_payload("proj-multi"))
        assert out["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_marker_keyed_by_project_not_shared(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    gate.record_param_confirm_marker("proj-A")
    out = gate.decide_param_write_gate(_write_payload("proj-B"))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_gate_ignores_non_param_write_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    payload = {"tool_name": "mcp__x__insar_set_runconfig_value", "tool_input": {"project_id": "p"}}
    out = gate.decide_param_write_gate(payload)
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"


# ── arming tool writes the marker; gate then allows ──────────────────────────

def _new_project(tmp_path, name):
    return insar_create_project(
        engine="isce3", workflow="insar", workspace_root=str(tmp_path / name)
    )["project_id"]


def test_arm_confirm_writes_marker_and_gate_allows(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    pid = _new_project(tmp_path, "ws-confirm")
    res = insar_arm_param_write(project_id=pid, mode="confirm")
    assert res.get("error") is None, res
    assert res["mode"] == "confirm" and res["armed"] is True
    assert gate.confirm_marker_path(pid).exists()
    out = gate.decide_param_write_gate(_write_payload(pid))
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_arm_auto_writes_marker_and_gate_allows(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    pid = _new_project(tmp_path, "ws-auto")
    res = insar_arm_param_write(project_id=pid, mode="auto")
    assert res.get("error") is None, res
    assert res["mode"] == "auto"
    assert gate.auto_marker_path(pid).exists()
    out = gate.decide_param_write_gate(_write_payload(pid))
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_arm_invalid_mode_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    pid = _new_project(tmp_path, "ws-bad")
    assert insar_arm_param_write(project_id=pid, mode="bogus")["error"] == "invalid_mode"


def test_arm_unknown_project_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    res = insar_arm_param_write(project_id="00000000-0000-0000-0000-000000000000", mode="confirm")
    assert res.get("error") is not None


# ── doc guard: every skill that CALLS set_processing_param must arm ───────────

def test_skills_that_call_set_param_also_arm():
    offenders = []
    for skill in sorted(SKILL_DIR.glob("*/SKILL.md")):
        text = skill.read_text(encoding="utf-8")
        if "insar_set_processing_param(" in text and "insar_arm_param_write(" not in text:
            offenders.append(skill.name)
    assert not offenders, f"skills call insar_set_processing_param(...) without an insar_arm_param_write(...) arm: {offenders}"
