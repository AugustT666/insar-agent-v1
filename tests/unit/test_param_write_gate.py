"""Controlled write policy + mode-aware gate (Component 3 / spec §5).

The parameter-write tool (insar_set_processing_param) is a PreToolUse-gated
science-parameter channel: writes are denied unless a per-run user-confirm
marker OR a per-session auto-mode marker exists. Path fields via
insar_set_runconfig_value are NOT gated.

Markers live under the same marker_dir() as the execution gate.
"""
from __future__ import annotations

from pathlib import Path

from insar_agent.hooks import param_advisor_gate as gate


# ── marker helpers ────────────────────────────────────────────────────────────

def test_confirm_marker_path_shape(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    p = gate.confirm_marker_path("run/abc 1")
    assert p.parent == gate.marker_dir()
    assert p.name == "run_abc_1.paramconfirm"


def test_auto_marker_path_shape(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    p = gate.auto_marker_path("s/ess 9")
    assert p.parent == gate.marker_dir()
    assert p.name == "s_ess_9.autoparam"


def test_confirm_and_auto_markers_do_not_collide(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    assert gate.confirm_marker_path("x") != gate.auto_marker_path("x")


def test_record_param_confirm_marker_creates_file(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    p = gate.record_param_confirm_marker("proj-1")
    assert p == gate.confirm_marker_path("proj-1")
    assert p.exists()


def test_record_auto_marker_creates_file(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    p = gate.record_auto_marker("sess-1")
    assert p == gate.auto_marker_path("sess-1")
    assert p.exists()


# ── gate logic (matrix: interactive/no-marker=deny, confirm=allow, auto=allow) ─

def _write_payload(session_id="s-w", project_id="proj-1"):
    return {
        "session_id": session_id,
        "tool_name": "mcp__plugin_insar-agent-plugin_insar-mcp-server__insar_set_processing_param",
        "tool_input": {
            "project_id": project_id,
            "key": "range_looks",
            "value": 8,
            "justification": "test",
            "scope": "isce2",
        },
    }


def test_gate_denies_interactive_without_any_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    assert gate.decide_param_write_gate(
        _write_payload(session_id="s-deny", project_id="p-deny")
    ) is False


def test_gate_allows_with_run_confirm_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    gate.record_param_confirm_marker("p-ok")
    assert gate.decide_param_write_gate(
        _write_payload(session_id="s-x", project_id="p-ok")
    ) is True


def test_gate_allows_with_session_auto_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    gate.record_auto_marker("s-auto")
    assert gate.decide_param_write_gate(
        _write_payload(session_id="s-auto", project_id="p-any")
    ) is True


def test_confirm_marker_is_scoped_to_its_run(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    gate.record_param_confirm_marker("p-ok")
    # a DIFFERENT run id, no auto marker -> still denied
    assert gate.decide_param_write_gate(
        _write_payload(session_id="s-x", project_id="p-other")
    ) is False


def test_gate_ignores_dry_run_field(tmp_path, monkeypatch):
    # param writes have NO dry-run bypass (unlike the execution gate): a dry_run
    # field must not open a hole. dry-run-equivalent = N/A for this gate.
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    payload = _write_payload(session_id="s-dry", project_id="p-dry")
    payload["tool_input"]["dry_run"] = True
    assert gate.decide_param_write_gate(payload) is False


def test_deny_reason_mentions_confirmation_and_auto():
    reason = gate._PARAM_WRITE_DENY_REASON.lower()
    assert "non-path science parameters require user confirmation" in reason
    assert "auto mode" in reason
