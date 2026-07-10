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
