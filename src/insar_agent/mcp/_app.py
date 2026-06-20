"""Shared MCP foundation: imports, module constants, and the FastMCP instance.

Every tool/resource/prompt/helper module imports the shared ``mcp`` instance
(and the module-level constants) from here so all decorators register on the
same FastMCP object. This module is deliberately free of tool/helper bodies.

``__all__`` lists every binding (including the underscore-prefixed constants) so
that ``from insar_agent.mcp._app import *`` pulls in the full foundation.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from datetime import datetime, UTC
from pathlib import Path
from typing import TypeGuard

import yaml
from mcp.server.fastmcp import FastMCP

from insar_agent.core.config import get_path, set_path, unset_path
from insar_agent.core.jobs import BatchJob, DownloadJob, Job
from insar_agent.core.layout import RunLayout, find_run_root, infer_run_root
from insar_agent.core.output_resolver import prepare_input_dir, resolve_output
from insar_agent.core.project import Project, new_project
from insar_agent.mcp.layout_helpers import (
    apply_run_layout_to_runconfig as _apply_run_layout_to_runconfig,
    check_output_dir_depth as _check_output_dir_depth,
    param_advice_output_dir as _param_advice_output_dir,
    render_param_advice_markdown as _render_param_advice_markdown,
    resolve_run_layout as _resolve_run_layout,
    validate_param_advice_format_version,
)
from insar_agent.engines.isce3.adapter import ISCE3Adapter
from insar_agent.engines.isce3.defaults import (
    ALLOWED_SET_FIELDS as ISCE3_ALLOWED_SET_FIELDS,
    REQUIRED_PATH_FIELDS,
    get_default_runconfig_template_path,
    get_processing_param_keys,
    load_default_runconfig,
    load_processing_params,
)
from insar_agent.engines.isce2.defaults import (
    ALLOWED_SET_FIELDS as ISCE2_ALLOWED_SET_FIELDS,
)

from insar_agent.engines.isce3.baseline import plot_baseline_network
from insar_agent.engines.isce3.bbox import union_bbox
from insar_agent.engines.isce3.aoi import resolve_aoi_bbox
from insar_agent.engines.isce3.dem import download_dem
from insar_agent.engines.isce3.geotiff import export_geotiff, geocode_runw_to_geotiff
from insar_agent.engines.isce3.mintpy import get_mintpy_status, run_mintpy
from insar_agent.engines.isce3.network import prepare_network
from insar_agent.engines.isce3.rslc_metadata import describe_rslc_pair
from insar_agent.engines.isce3.runner import build_workflow_command
from insar_agent.engines.isce3.stack import prepare_stack
from insar_agent.engines.isce3.validator import validate_runconfig
from insar_agent.engines.isce2.adapter import ISCE2Adapter
from insar_agent.engines.isce2.defaults import (
    REQUIRED_PARAM_FIELDS as ISCE2_REQUIRED_PARAM_FIELDS,
    get_processing_param_keys as isce2_get_processing_param_keys,
    load_default_params as isce2_load_default_params,
    load_processing_params as isce2_load_processing_params,
)
from insar_agent.engines.isce2.runner import (
    build_topsapp_xml,
    build_workflow_command as isce2_build_workflow_command,
    materialize_dem_for_tops,
)
from insar_agent.engines.isce2.mintpy import run_mintpy_isce2_stack
from insar_agent.engines.isce2.sentinel_prep import (
    _read_safe_metadata,
    check_annotation_geolocation_grid,
    prepare_sentinel_data,
)
from insar_agent.engines.isce2.stack import build_stack_command as isce2_build_stack_command
from insar_agent.engines.isce2.validator import validate_params as isce2_validate_params

ENGINE_ALLOWED_FIELDS: dict[str, dict[str, list[str]]] = {
    "isce3": ISCE3_ALLOWED_SET_FIELDS,
    "isce2": ISCE2_ALLOWED_SET_FIELDS,
}

# Canonical task_id derived from engine+workflow.  Maps directly to the
# top-level workspace directory for that workflow type.
_WORKFLOW_TO_TASK_ID: dict[tuple[str, str], str] = {
    ("isce2", "tops"): "d-insar-isce2",
    ("isce3", "insar"): "d-insar-isce3",
    ("isce2", "stack"): "stack-insar-isce2",
    ("isce3", "stack"): "stack-insar-isce3",
}

_ADAPTER = ISCE3Adapter()
_ISCE2_ADAPTER = ISCE2Adapter()
_ENGINES = {_ADAPTER.name: _ADAPTER, _ISCE2_ADAPTER.name: _ISCE2_ADAPTER}

mcp = FastMCP("insar-mcp-server")

_CONDA_SAFE_DEFAULTS = {
    "_CONDA_SET_GEOTIFF_CSV": "",
    "PYTHONWARNINGS": "ignore::FutureWarning",
}

# Entry point for AI clients that reach the MCP server directly.
# Keep workflow guidance single-sourced in the packaged main router skill.
# ``__file__`` is .../src/insar_agent/mcp/_app.py — parents[3] is the repo root,
# matching the original server.py depth (.../src/insar_agent/mcp/server.py).
_WORKFLOW_GUIDE_SKILL_PATH = Path(__file__).resolve().parents[3] / "skills" / "insar-agent" / "SKILL.md"

_SENSITIVE_PARAM_KEYS = {"orbit_password", "password", "token", "access_token", "refresh_token", "proxy"}

_TASK_ROOT_MANAGEMENT_DIRS = {".insar_agent", "insar_product"}

WORKFLOW_LOG_TAIL_LINES = 80

WORKFLOW_LOG_FAILURE_PATTERNS = (
    re.compile(r"^\s*(?:\w+error|error):\s*(?!0\b)", re.IGNORECASE),
    re.compile(r"^\s*traceback\b", re.IGNORECASE),
    re.compile(r"^\s*exception:\s*", re.IGNORECASE),
    re.compile(r"^\s*critical:\s*", re.IGNORECASE),
    re.compile(r"\d+\s+Killed\s"),
)

WORKFLOW_LOG_FAILURE_SUBSTRINGS = (
    "environmentlocationnotfound",
    "not a conda environment",
    "condaerror",
    "已杀死",
)

WORKFLOW_LOG_SUCCESS_MARKERS = (
    "[insar-agent] all stack steps completed.",
    "workflow finished successfully",
)

_VAGUE_JUSTIFICATIONS = {
    "better performance",
    "optimize",
    "optimization",
    "improve quality",
    "test",
}

__all__ = [
    # stdlib / third-party
    "argparse", "json", "math", "os", "re", "shlex", "shutil", "subprocess",
    "sys", "tempfile", "time", "uuid", "zipfile", "datetime", "UTC", "Path",
    "TypeGuard", "yaml", "FastMCP",
    # core
    "get_path", "set_path", "unset_path",
    "BatchJob", "DownloadJob", "Job",
    "RunLayout", "find_run_root", "infer_run_root",
    "prepare_input_dir", "resolve_output",
    "Project", "new_project",
    # layout helpers
    "_apply_run_layout_to_runconfig", "_check_output_dir_depth",
    "_param_advice_output_dir", "_render_param_advice_markdown",
    "_resolve_run_layout", "validate_param_advice_format_version",
    # isce3
    "ISCE3Adapter", "ISCE3_ALLOWED_SET_FIELDS", "REQUIRED_PATH_FIELDS",
    "get_default_runconfig_template_path", "get_processing_param_keys",
    "load_default_runconfig", "load_processing_params",
    "plot_baseline_network", "union_bbox", "resolve_aoi_bbox", "download_dem",
    "export_geotiff", "geocode_runw_to_geotiff", "get_mintpy_status", "run_mintpy",
    "prepare_network", "describe_rslc_pair", "build_workflow_command",
    "prepare_stack", "validate_runconfig",
    # isce2
    "ISCE2_ALLOWED_SET_FIELDS", "ISCE2Adapter", "ISCE2_REQUIRED_PARAM_FIELDS",
    "isce2_get_processing_param_keys", "isce2_load_default_params",
    "isce2_load_processing_params", "build_topsapp_xml",
    "isce2_build_workflow_command", "materialize_dem_for_tops",
    "run_mintpy_isce2_stack", "_read_safe_metadata",
    "check_annotation_geolocation_grid", "prepare_sentinel_data",
    "isce2_build_stack_command", "isce2_validate_params",
    # constants + instance
    "ENGINE_ALLOWED_FIELDS", "_WORKFLOW_TO_TASK_ID", "_ADAPTER", "_ISCE2_ADAPTER",
    "_ENGINES", "mcp", "_CONDA_SAFE_DEFAULTS", "_WORKFLOW_GUIDE_SKILL_PATH",
    "_SENSITIVE_PARAM_KEYS", "_TASK_ROOT_MANAGEMENT_DIRS", "WORKFLOW_LOG_TAIL_LINES",
    "WORKFLOW_LOG_FAILURE_PATTERNS", "WORKFLOW_LOG_FAILURE_SUBSTRINGS",
    "WORKFLOW_LOG_SUCCESS_MARKERS", "_VAGUE_JUSTIFICATIONS",
]
