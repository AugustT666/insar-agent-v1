---
description: Start an insar-agent workflow session
allowed-tools: mcp__insar-agent__*
---

Start an insar-agent workflow session.

First call `insar_check_env` and report only missing environment, MCP, or plugin-skill items that block the requested workflow. Then read `insar://workflow-guide` before using any execution tool. Use `skills/insar-agent/SKILL.md` as the routing source of truth, and route the user's request to the appropriate engine-specific skill and `insar_*` MCP tools.

Do not run ISCE2, ISCE3, MintPy, conda processing commands, or ad hoc workflow scripts directly from shell. Use the MCP tools for workflow actions, preserve log paths from tool results, and pause at skill-defined handoff points.
