"""Generic InSAR product quality metrics.

This module provides reusable product statistics that can be used from skills,
MCP tools, command-line scripts, and the integration-test harness.
It does NOT contain experiment-specific fields (E1–E4 tables, interventions,
tmux transcripts) — those belong in the test harness.
"""
from insar_agent.metrics.product import collect_product_metrics, write_product_metrics

__all__ = ["collect_product_metrics", "write_product_metrics"]
