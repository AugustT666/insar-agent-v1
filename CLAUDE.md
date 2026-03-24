# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run all tests
pytest

# Run a single test file
pytest tests/unit/test_smoke.py

# Run a single test by name
pytest tests/unit/test_smoke.py::test_server_description_mentions_isce3

# Run the CLI
PYTHONPATH=src python -m insar_agent describe

# Run the MCP server (describe mode only — stdio not yet implemented)
PYTHONPATH=src python -m insar_agent.mcp.server --describe
# or after installing: insar-mcp-server --describe

# Install in editable mode with dev deps
pip install -e ".[dev]"
```

`pytest` resolves `src/` automatically via `pythonpath = ["src"]` in `pyproject.toml`. The `PYTHONPATH=src` prefix is only needed when running modules directly.

## Architecture

The project separates three layers:

```
Agent Client (Codex / Claude Code / etc.)
  -> insar_agent.mcp        # MCP protocol wiring, tool/resource/prompt definitions
  -> insar_agent.core       # Protocol-agnostic domain logic (Project, Job, config)
  -> insar_agent.engines.isce3  # ISCE3-specific adapter, validators, runner
  -> runtime + local conda env
```

**`insar_agent.core`** — owns the domain model. `Project` (persisted as JSON) holds `engine`, `workflow`, `runconfig` (dict), and `workspace_root`. `config.py` provides `get_path`/`set_path` for dotted-key access into runconfig dicts. `jobs.py` will own the `Job` state machine.

**`insar_agent.mcp`** — owns MCP server wiring. Currently a scaffold (`server.py` prints planned metadata). Will be replaced with an SDK-backed stdio transport. MCP tools must delegate all domain logic to `core` and `engines`; no business logic belongs here.

**`insar_agent.engines`** — owns software-specific behavior. `base.py` defines `EngineAdapter` (Protocol) and `WorkflowInfo`. `isce3/` is the first adapter: `adapter.py` implements `ISCE3Adapter`, `defaults.py` declares supported workflows (`gslc`, `insar`), `validator.py` and `runner.py` are stubs for runconfig validation and `nisar.workflows` execution.

**`insar_agent.runtime`** — workspace layout, conda env detection, structured logging helpers.

**`skills/`** — host-specific teaching material for agent clients. Not the source of truth for execution logic.

## Key Rules from AGENTS.md

- Domain knowledge (ISCE3 runconfigs, scripts, workflow notes) arrives as reference input and must be normalized into code/prompts/validations. Do not invent workflow parameters when source material is incomplete.
- Protocol-agnostic logic belongs in `core`. MCP wiring belongs in `mcp`. Engine behavior belongs in `engines/<engine>`.
- No runtime dependency on `cli-anything` or its package layout.
- When a dependency (e.g. MCP SDK) is not yet installed, preserve a clean scaffold and document the missing dep — do not guess around it.

## Current Status

M0 is complete. M1 (config management) is in progress. Before making non-trivial changes, read:

1. `docs/architecture.md` — system overview, layer boundaries, milestone status
2. `docs/mcp-tools.md` — full input/output spec for every MCP tool
3. `docs/domain-model.md` — Project, Job, WorkflowTemplate, Artifact field definitions
4. `docs/decisions/0001-project-scope.md` — why this is an independent repo
5. `docs/plans/2026-03-23-insar-agent-tech-spec-v0.1.md` — original Chinese draft (historical reference)

## Collaboration Workflow

The domain expert (user) provides ISCE3 processing scripts, runconfig templates, and workflow documentation. Claude Code implements the corresponding MCP tools and engine adapter code.

**Typical flow for each new capability:**
1. User provides ISCE3 script or runconfig template
2. Claude normalizes it into `engines/isce3/` (validator, runner, defaults)
3. Claude wires it as an MCP tool in `mcp/server.py` via the `core` layer
4. Tests are added in `tests/unit/` or `tests/integration/`

**Milestone targets:**
- M0: scaffold ✓ (package layout, scaffold server, smoke tests)
- M1: runconfig management — `insar_create_project`, `get/set/unset/validate/export runconfig`
- M2: job execution — `insar_run_workflow`, `insar_get_job_status`, `insar_get_job_logs`
- M3: output handling — `insar_list_outputs`, `insar_generate_preview`

Full tool specs are in `docs/mcp-tools.md`. Domain object fields are in `docs/domain-model.md`.
