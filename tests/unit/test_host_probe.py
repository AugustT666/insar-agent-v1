"""Host hardware probe — gives the param-advisor subagent a deterministic,
structured read of local CPU / memory / GPU so its compute-efficiency advice
(num_proc, parallelism) is grounded in the actual machine.
"""
from __future__ import annotations

import insar_agent.core.host_probe as host_probe
from insar_agent.core.host_probe import (
    _detect_unwrap_methods,
    _recommend_unwrap_method,
    probe_host,
)
from insar_agent.mcp.server import insar_probe_host


def test_probe_host_reports_cpu_memory_and_parallelism():
    r = probe_host()
    assert isinstance(r["logical_cpu_count"], int) and r["logical_cpu_count"] >= 1
    assert isinstance(r["usable_cpu_count"], int) and r["usable_cpu_count"] >= 1
    assert "total_memory_gb" in r
    assert "available_memory_gb" in r
    assert "gpus" in r and isinstance(r["gpus"], list)
    assert isinstance(r["suggested_num_proc_upper_bound"], int) and r["suggested_num_proc_upper_bound"] >= 1


def test_insar_probe_host_mcp_tool_returns_hardware():
    r = insar_probe_host()
    assert r.get("error") is None, r
    assert "logical_cpu_count" in r
    assert "suggested_num_proc_upper_bound" in r
    assert "gpus" in r


# ---------------------------------------------------------------------------
# Issue 003 — unwrap method dynamic discovery (RED → GREEN)
# ---------------------------------------------------------------------------

def test_probe_host_includes_unwrap_methods_and_recommendation():
    r = probe_host()
    assert "unwrap_methods" in r and isinstance(r["unwrap_methods"], dict)
    # ISCE2-builtin candidates are always listed (their real availability is tied
    # to ISCE2 being in the run env, which insar_check_env reports).
    for name in ("snaphu", "snaphu2stage", "icu"):
        assert name in r["unwrap_methods"], name
        assert r["unwrap_methods"][name]["source"] == "isce2-builtin"
    assert r["unwrap_recommended"] in r["unwrap_methods"]


def test_recommend_unwrap_method_prefers_snaphu_without_gpu():
    methods = {
        "snaphu": {"available": True, "gpu": False},
        "phunwrap": {"available": False, "gpu": True},
    }
    assert _recommend_unwrap_method(methods, has_gpu=False) == "snaphu"


def test_recommend_unwrap_method_prefers_gpu_unwrapper_when_present_and_available():
    methods = {
        "snaphu": {"available": True, "gpu": False},
        "phunwrap": {"available": True, "gpu": True},
    }
    assert _recommend_unwrap_method(methods, has_gpu=True) == "phunwrap"


def test_recommend_unwrap_method_falls_back_to_snaphu_when_gpu_unwrapper_absent():
    # GPU present, but the GPU-capable unwrapper is not installed → stay on snaphu.
    methods = {
        "snaphu": {"available": True, "gpu": False},
        "phunwrap": {"available": False, "gpu": True},
    }
    assert _recommend_unwrap_method(methods, has_gpu=True) == "snaphu"


def test_detect_unwrap_methods_marks_phunwrap_available_when_on_path(monkeypatch):
    monkeypatch.setattr(
        host_probe.shutil, "which",
        lambda name: "/usr/bin/phunwrap" if name == "phunwrap" else None,
    )
    methods = _detect_unwrap_methods()
    assert methods["phunwrap"]["available"] is True
    assert methods["phunwrap"]["path"] == "/usr/bin/phunwrap"
    assert methods["phunwrap"]["gpu"] is True
    # builtin candidates remain present regardless of PATH
    assert methods["snaphu"]["available"] is True
    assert methods["snaphu"]["source"] == "isce2-builtin"


def test_detect_unwrap_methods_phunwrap_absent(monkeypatch):
    monkeypatch.setattr(host_probe.shutil, "which", lambda name: None)
    methods = _detect_unwrap_methods()
    assert methods["phunwrap"]["available"] is False


def test_insar_probe_host_exposes_unwrap_methods():
    r = insar_probe_host()
    assert r.get("error") is None, r
    assert "unwrap_methods" in r
    assert "unwrap_recommended" in r
