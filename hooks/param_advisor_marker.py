#!/usr/bin/env python3
"""PostToolUse wrapper: record that the param-advisor subagent was consulted this
session (matches the Task tool; only marks when subagent_type is the
param-advisor). Self-locates the package so it works in inline plugin mode.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from insar_agent.hooks.param_advisor_gate import main_marker  # noqa: E402

main_marker()
