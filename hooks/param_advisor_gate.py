#!/usr/bin/env python3
"""PreToolUse wrapper: deny irreversible InSAR execution until the param-advisor
subagent has been consulted. Self-locates the package so it works in inline
plugin mode without relying on PYTHONPATH.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from insar_agent.hooks.param_advisor_gate import main_gate  # noqa: E402

main_gate()
