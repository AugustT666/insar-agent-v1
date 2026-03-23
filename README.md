# insar-agent

`insar-agent` is an independent project for exposing InSAR processing capabilities to agent clients through a shared core, an MCP-facing interface, and engine-specific adapters.

## Current Scope

- Project status: scaffold
- First engine target: `ISCE3`
- First protocol target: local `MCP` server over `stdio`
- Current goal: establish package boundaries and a clean repository layout before implementing real workflow execution

## Working Model

The implementation model for this project is:

1. You provide real `ISCE3` operating guidance, scripts, runconfigs, and workflow notes.
2. Those references are distilled into reusable engine adapters, validation rules, prompts, and host-specific skills.
3. The project exposes that behavior through a stable MCP tool layer instead of depending on one agent client's private plugin model.

## Repository Layout

```text
insar-agent/
  docs/
  examples/
  skills/
  src/insar_agent/
  tests/
```

Key Python packages:

- `insar_agent.core`: project/session/config/job primitives
- `insar_agent.mcp`: MCP-facing entrypoint and server description
- `insar_agent.engines.isce3`: first engine adapter boundary
- `insar_agent.runtime`: environment, workspace, and logging helpers

## Quick Start

```bash
cd /home/august/insar-agent
PYTHONPATH=src python -m insar_agent describe
PYTHONPATH=src python -m insar_agent.mcp.server --describe
```

The current MCP entrypoint is intentionally a protocol-oriented placeholder. It describes planned tools and boundaries, but it does not yet start a real SDK-backed MCP transport.

## Primary Docs

- Architecture: `docs/architecture.md`
- Initial scope decision: `docs/decisions/0001-project-scope.md`
- Current technical plan: `docs/plans/2026-03-23-insar-agent-tech-spec-v0.1.md`

## Near-Term Roadmap

- Replace the placeholder MCP entrypoint with an SDK-backed server
- Port the shared project/config/job model from the current scaffold into real tool handlers
- Add the first `ISCE3` adapter behaviors based on your supplied operating materials
- Introduce skill artifacts that teach host agents how to use the exposed tools safely
