"""MCP resources for insar-agent (registered on the shared FastMCP)."""

from __future__ import annotations

from insar_agent.mcp._app import *  # noqa: F403  (foundation: imports + constants + mcp)
from insar_agent.mcp._helpers import *  # noqa: F403  (shared helpers)


@mcp.resource("insar://workflow-guide")
def get_workflow_guide() -> str:
    """Return the main workflow router skill used by skill-aware clients."""
    return _WORKFLOW_GUIDE_SKILL_PATH.read_text(encoding="utf-8")


@mcp.resource("insar://allowed-fields/{workflow}")
def get_allowed_fields(workflow: str) -> str:
    """List the fields that may be set via insar_set_runconfig_value for a workflow."""
    from insar_agent.engines.isce3.defaults import ALLOWED_SET_FIELDS, REQUIRED_PATH_FIELDS
    allowed = ALLOWED_SET_FIELDS.get(workflow)
    if allowed is None:
        return f"Unknown workflow: {workflow!r}. Available: {list(ALLOWED_SET_FIELDS)}"
    required = REQUIRED_PATH_FIELDS.get(workflow, [])
    lines = [f"# Settable fields for workflow '{workflow}'", "",
             "## Required (must be set before insar_run_workflow can launch successfully)"]
    lines += [f"  {f}" for f in required]
    optional = [f for f in allowed if f not in required]
    if optional:
        lines += ["", "## Optional"]
        lines += [f"  {f}" for f in optional]
    lines += ["", "All other fields are core processing parameters and cannot be changed via MCP."]
    return "\n".join(lines)
