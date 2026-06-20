"""Host hardware probe — gives the param-advisor subagent a deterministic,
structured read of local CPU / memory / GPU so its compute-efficiency advice
(num_proc, parallelism) is grounded in the actual machine.
"""
from __future__ import annotations

from insar_agent.core.host_probe import probe_host
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
