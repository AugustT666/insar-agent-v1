---
name: env-setup-nisar
description: >
  Use when the user needs to set up the insar-agent environment from scratch, when
  ISCE3 or the MCP server is not yet installed, or when environment checks fail.
  Invoke when the user says "first time setup", "install isce3", "MCP not found",
  "how do I install", "set up the environment", or asks how to get started with
  insar-agent for the first time.
---

# Environment Setup: ISCE3 + insar-agent MCP

> **Status: placeholder — detailed steps to be completed in a future milestone.**

## What this skill will do (planned)

1. Check whether the ISCE3 conda environment exists locally (`conda env list`)
2. Check whether the insar-agent MCP server is installed and registered in Claude Code
3. If either is missing: ask the user whether to proceed with guided installation
4. Walk through ISCE3 environment creation from the standard conda template
5. Install insar-agent in editable mode (`pip install -e ".[dev]"`)
6. Register insar-agent as an MCP server in Claude Code settings
7. Run a smoke test to confirm the MCP server responds correctly

## For now

If you reach this skill and setup is needed, ask the user to follow the manual steps:

1. Install ISCE3 following the official NISAR documentation.
2. Install insar-agent:
   ```bash
   cd /path/to/insar-agent
   pip install -e ".[dev]"
   ```
3. Register the MCP server and install skills in Claude Code:
   ```bash
   claude plugin marketplace add /path/to/insar-agent --scope project
   claude plugin install insar-agent-skills@insar-agent
   ```
4. Verify: `pytest` should pass all unit tests.
