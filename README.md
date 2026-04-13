# insar-agent

`insar-agent` is an MCP-first InSAR orchestration project. It exposes a stable
tool surface for agent clients and keeps the processing logic in reusable Python
modules instead of client-specific plugins or ad hoc shell workflows.

## What It Does

Current support is centered on `ISCE3` and NISAR RSLC data:

- Path A: single reference/secondary RSLC pair -> `GUNW`
- Path B: multi-scene stack preparation -> interferogram network -> MintPy
- metadata-first parameter optimization via `param-advisor-isce3` (NISAR/ISCE3)
  or `param-advisor-isce2` (Sentinel/ISCE2), each delegating recommendation
  generation to a project-level subagent
- utility workflows such as RSLC bbox extraction and GeoTIFF export

## Who It Is For

- AI-agent clients that need a compact, well-scoped MCP interface
- developers turning real InSAR operating knowledge into reusable tooling
- advanced users who want reproducible ISCE3 workflow orchestration without
  baking logic into a single host application

## Quick Start

```bash
cd /home/august/insar-agent
pip install -e ".[dev]"

PYTHONPATH=src python -m insar_agent describe
PYTHONPATH=src python -m insar_agent doctor
PYTHONPATH=src python -m insar_agent.mcp.server --describe
PYTHONPATH=src python -m insar_agent.mcp.server --stdio
```

`insar-mcp-server` runs over stdio. `--describe` prints the active MCP surface;
`--stdio` starts the server for external clients.

## Tests

```bash
pytest                              # default suite; excludes real_data tests
pytest tests/unit -q                # unit tests only
pytest -m real_data tests/integration -q
```

Real-data tests require the NAS dataset and may launch actual processing workflows, so they are opt-in.

## Typical Workflows

### Single Pair

1. Create a project with `insar_create_project`
2. Fill required path fields with `insar_set_runconfig_value`
3. If parameter tuning is needed, enter the engine-appropriate advisor:
   - `param-advisor-isce3` for NISAR/ISCE3 (`insar_describe_rslc`)
   - `param-advisor-isce2` for Sentinel/ISCE2 (`insar_describe_s1`)
4. Apply approved whitelist-controlled changes through
   `insar_set_processing_param`
5. Launch with `insar_run_workflow`
6. Poll with `insar_get_job`

### Batch Stack / Time Series

1. Generate stack runconfigs with `insar_prepare_stack`
2. Generate network runconfigs with `insar_prepare_network`
3. Launch generated batches manually or through `insar_run_batch`
4. Run MintPy with `insar_run_mintpy` (ISCE3/GUNW) or `insar_run_mintpy_isce2` (Sentinel-1/ISCE2 stack)
5. Poll all long-running work with `insar_get_job`

## Repository Structure

```text
insar-agent/
  docs/                 architecture, API reference, archive, developer notes
  examples/             reserved place for future sanitized example runconfigs
  skills/               workflow guidance for skill-aware hosts
  src/insar_agent/      core models, MCP server, ISCE3 engine code
  tests/                unit and integration coverage
```

Historical source materials that informed the current implementation live under
`docs/archive/knowledge-base/`. They are retained for traceability, not as the
current source of truth.

## Primary Docs

- `docs/architecture.md`: system overview, execution modes, and core data model
- `docs/mcp-tools.md`: tools, resources, prompts, and behavior contracts
- `docs/agent-guide.md`: hard workflow constraints served as
  `insar://workflow-guide`
- `CLAUDE.md`: developer-facing collaboration guide for Claude Code and Codex
- `docs/developer-documents/dev-plan.md`: internal progress and planned work

## Current Status

The current active surface is:

- 17 FastMCP tools
- 2 resources
- 2 prompts
- real-data validation paths for ISCE3 and MintPy-adjacent workflows

For exact tool behavior, treat `docs/mcp-tools.md` and the live `--describe`
output as authoritative.
