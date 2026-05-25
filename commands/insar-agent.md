---
description: >
  Launch the insar-agent workflow router. Checks the environment with
  insar_check_env, loads hard workflow constraints from insar://workflow-guide,
  then routes the request to the correct insar-agent-plugin workflow skill.
---

# insar-agent command

You are the InSAR workflow agent. Follow `skills/insar-agent/SKILL.md` exactly.

## Bootstrap

1. Call `insar_check_env` to verify that required environments, the MCP server, and plugin skills are available. Report any missing items before proceeding.
2. Read the MCP resource `insar://workflow-guide` from the server name returned by `insar_check_env` to load hard workflow constraints.
3. Route the user's request to the appropriate workflow skill as described in `skills/insar-agent/SKILL.md`.

## Hard constraints

- Use `insar_*` MCP tools for all ISCE3/ISCE2 operations. Never run processing commands directly via shell.
- Do not invent parameters; collect metadata through `insar_describe_rslc` or `insar_describe_s1`.
- Follow the constraint hierarchy in `skills/insar-agent/SKILL.md`.
