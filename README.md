# insar-agent

`insar-agent` is an MCP-first InSAR orchestration project. It exposes a stable tool surface for agent clients and keeps the processing logic in reusable Python modules instead of client-specific plugins or ad hoc shell workflows.

It is built as a dual-engine orchestrator, supporting both **NISAR/ISCE3** and **Sentinel-1/ISCE2** data streams.

## Capabilities

The system exposes a rich MCP and plugin surface tailored for automated workflows:

- **28 MCP Tools**: Covering catalog discovery, project management, config tuning, execution, batch processing, data preparation, product export, recovery geocoding, and ISCE2 troposphere correction.
- **1 MCP Resource + 1 Resource Template**: Serving hard workflow constraints (`insar://workflow-guide`) and schema rules (`insar://allowed-fields/{workflow}`).
- **2 MCP Prompts**: Pre-built instructions for single-pair and batch processing.
- **11 Plugin Skills**: Providing the main `insar-agent` entry router plus domain guidance for data preparation, parameter advisory, environment setup, and path execution.
- **Dual-Engine Execution**: Native support for both `isce3` (NISAR) and `isce2` (Sentinel-1) processing graphs.
- **Runtime Support Layer**: Unified output layout (`output_root/<task>_<timestamp>/insar_product/`), two-layer logging (Layer-1 progress + Layer-2 raw engine logs), and Conda environment orchestration.

Note: the source FastMCP registration surface and the `--describe` CLI summary currently report 28 tools.

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

Real-data tests may launch actual processing workflows, so they are opt-in.

## Plugin Entry Point

For Claude Code plugin usage, start InSAR sessions through the packaged command:

```text
/insar-agent
```

The command checks the installed MCP/plugin surface, reads `insar://workflow-guide`,
and routes through the main `insar-agent` skill. The entry skill then routes to the
engine-specific workflow skills and delegates parameter tuning to the `param-advisor`
skill and `agents/param-advisor.md` subagent.

## Output Layout

`insar_create_project(output_root=<path>)` returns a single `project_id`. All subsequent
tools use this handle.

```
<output_root>/
  prepare/{dem,safe,orbits,rslc}/   shared inputs reused across runs
  <task>_<timestamp>/               one directory per run
    .insar_agent/
      project.json
      jobs/
      progress.log                  Layer-1 concise progress (tail -f to monitor)
    insar_product/
      products/ scratch/ configs/
      logs/                         Layer-2 raw engine output
      stack/ network/ mintpy/ exports/ param_advisor/ troposphere/
```

Long-running tasks auto-background. Poll with `insar_get_job(project_id, job_id)`.
Monitor progress: `tail -f <run_root>/.insar_agent/progress.log`.

## Typical Workflows

### D-InSAR (Path A)

1. Create a project with `insar_create_project(output_root=...)` → get `project_id`.
2. Fill required path fields with `insar_set_runconfig_value`.
3. Run `param-advisor` to review metadata (`insar_describe_rslc` or `insar_describe_s1`) — mandatory before execution.
4. Apply approved whitelist-controlled changes through `insar_set_processing_param`.
5. Launch with `insar_run_workflow` — task auto-backgrounds, returns `job_id`.
6. Poll completion with `insar_get_job(project_id, job_id)`.
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
  agents/               Claude Code subagents and agent-local references
  docs/                 Architecture, API reference, archive, developer notes
  examples/             Reserved place for future sanitized example runconfigs
  hooks/                Claude Code plugin hooks for workflow gates
  skills/               Workflow guidance and slash-style skill entry points
  src/insar_agent/      Core models, MCP server, ISCE3 & ISCE2 engine code, runtime logic
  tests/                Unit and integration coverage
```

Historical source materials that informed the current implementation live under `docs/archive/knowledge-base/`. They are retained for traceability, not as the current source of truth.

## Primary Docs

- `docs/architecture.md`: System overview, layer boundaries, and core data model.
- `docs/developer-documents/mcp-tools.md`: Tools, resources, prompts, and behavior contracts.
- `docs/agent-guide.md`: Hard workflow constraints served as `insar://workflow-guide`.
- `CLAUDE.md`: Developer-facing collaboration guide for Claude Code and Codex.
- `docs/developer-documents/dev-plan.md`: Internal progress and planned work.
