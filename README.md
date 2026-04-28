# insar-agent

`insar-agent` is an MCP-first InSAR orchestration project. It exposes a stable tool surface for agent clients and keeps the processing logic in reusable Python modules instead of client-specific plugins or ad hoc shell workflows.

It is built as a dual-engine orchestrator, supporting both **NISAR/ISCE3** and **Sentinel-1/ISCE2** data streams.

## Capabilities

The system exposes a rich MCP and plugin surface tailored for automated workflows:

- **24 MCP Tools**: Covering discovery, project management, config tuning, execution, batch processing, data preparation, and export.
- **2 MCP Resources**: Serving hard workflow constraints (`insar://workflow-guide`) and schema rules (`insar://allowed-fields/{workflow}`).
- **2 MCP Prompts**: Pre-built instructions for single-pair and batch processing.
- **11 Plugin Skills**: Providing domain guidance for data preparation, parameter advisory, environment setup, and path execution.
- **Dual-Engine Execution**: Native support for both `isce3` (NISAR) and `isce2` (Sentinel-1) processing graphs.
- **Runtime Support Layer**: Abstracted workspace layout, logging, and Conda environment orchestration.

Note: the source FastMCP registration surface and the `--describe` CLI summary both currently report 24 tools, including `insar_export_runconfig` and `insar_run_mintpy_isce2`.

## Who It Is For

- AI-agent clients that need a compact, well-scoped MCP interface.
- Developers turning real InSAR operating knowledge into reusable tooling.
- Advanced users who want reproducible ISCE3/ISCE2 workflow orchestration without baking logic into a single host application.

## Quick Start

```bash
pip install -e ".[dev]"

# Inspect the active MCP surface and runtime environment
insar-agent describe          # JSON summary of tools/resources/prompts
insar-agent doctor            # conda env and dependency checks

# Inspect or launch the MCP server
insar-mcp-server --describe   # print tool signatures
insar-mcp-server --stdio      # start stdio server for agent clients
```

## Tests

```bash
pytest                              # default suite; excludes real_data tests
pytest tests/unit -q                # unit tests only
pytest -m real_data tests/integration -q
```

Real-data tests require the NAS dataset and may launch actual processing workflows, so they are opt-in.

## Typical Workflows

### D-InSAR (Path A)

1. Create a project with `insar_create_project`.
2. Fill required path fields with `insar_set_runconfig_value`.
3. If parameter tuning is needed, enter `param-advisor` to review metadata (`insar_describe_rslc` or `insar_describe_s1`).
4. Apply approved whitelist-controlled changes through `insar_set_processing_param`.
5. Launch with `insar_run_workflow`.
6. Poll completion with `insar_get_job`.
7. Verify generated products with `insar_list_outputs`.

### Stack InSAR (Path B)

1. Generate stack runconfigs with `insar_prepare_stack`.
2. Generate network runconfigs with `insar_prepare_network`.
3. Launch generated batches through `insar_run_batch`.
4. Poll batch completion with `insar_get_job`.
5. Run MintPy with `insar_run_mintpy` (ISCE3/GUNW) or `insar_run_mintpy_isce2` (Sentinel-1/ISCE2 stack).
6. Poll all long-running MintPy tasks with `insar_get_job`.

## Repository Structure

```text
insar-agent/
  docs/                 Architecture, API reference, archive, developer notes
  examples/             Reserved place for future sanitized example runconfigs
  skills/               Workflow guidance for skill-aware hosts
  src/insar_agent/      Core models, MCP server, ISCE3 & ISCE2 engine code, runtime logic
  tests/                Unit and integration coverage
```

Historical source materials that informed the current implementation live under `docs/archive/knowledge-base/`. They are retained for traceability, not as the current source of truth.

## Primary Docs

- `docs/architecture.md`: System overview, layer boundaries, and core data model.
- `docs/mcp-tools.md`: Tools, resources, prompts, and behavior contracts.
- `docs/agent-guide.md`: Hard workflow constraints served as `insar://workflow-guide`.
- `CLAUDE.md`: Developer-facing collaboration guide for Claude Code and Codex.
- `docs/developer-documents/dev-plan.md`: Internal progress and planned work.
