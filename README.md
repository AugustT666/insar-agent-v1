# insar-agent

`insar-agent` is an independent project for exposing InSAR processing capabilities to agent clients through a shared core, an MCP-facing interface, and engine-specific adapters.

## Current Status (2026-03-28)

- **Project completion**: M0–M5 complete; M5b (agent behavior test) verified ✓
- **Test suite**: 155 tests passing (144 unit + 11 integration)
- **Engine**: ISCE3 fully functional with real NISAR RSLC data
- **MCP server**: FastMCP-based, ready for external AI clients
- **Agent integration**: Verified with opencode + gpt-5.3-codex; 9/9 checklist items passed
- **Real output**: 22MB GUNW product generated successfully from NAS data

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

## Next Steps

**M6: MintPy Integration** (planned)
- Implement `insar_run_mintpy` and `insar_plot_baseline` tools
- Reference implementation: `knowledge-base/wangshuai/Scripts/run_mintpy_nisar_stack.sh`
- Skills: `mintpy-isce3/SKILL.md` (time-series analysis workflow)

**M7: Future Enhancements** (discussion phase)
- ASF data download automation
- Multi-engine support (ISCE2, HyP3 adapters)
- Optional: Web UI / task queue
