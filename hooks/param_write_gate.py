#!/usr/bin/env python3
"""PreToolUse wrapper: deny insar_set_processing_param until the param-advisor /
stack / mintpy skill has armed param writes for the run via insar_arm_param_write.
Self-locates the package so it works in inline plugin mode without PYTHONPATH.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from insar_agent.hooks.param_advisor_gate import main_param_write_gate  # noqa: E402

main_param_write_gate()
