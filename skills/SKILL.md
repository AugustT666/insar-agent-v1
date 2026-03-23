# insar-agent

Use this skill when an agent needs to operate `insar-agent` safely.

## Current Guidance

- prefer MCP tools over ad hoc shell commands once the MCP server is implemented
- treat engine adapters as the source of executable behavior
- treat user-provided `ISCE3` scripts and docs as reference material that must be normalized before automation
- do not invent workflow parameters when the reference material is incomplete

## Planned Expansion

This skill will later include:

- `ISCE3` workflow selection guidance
- runconfig authoring patterns
- failure triage heuristics
- output interpretation guidance
