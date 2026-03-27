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

**`skills/`** — Claude Code skill files, packaged as a local plugin (`insar-agent-skills@insar-agent`) and installed into Claude Code. Invoke with the Skill tool:
- `data-prep-nisar` — download NISAR RSLC data (ASF) and DEM (Copernicus 30m)
- `d-insar-isce3` — single RSLC pair → GUNW product (Path A, M1-M3 tools)
- `stack-insar-isce3` — multi-scene batch stack + network (Path B, M4 tools)
- `env-setup-nisar` — ISCE3 + MCP installation guide (placeholder, M6+)
- `insar-agent` — session router / entry point

Plugin setup (run once, or after skills/ changes):
```bash
claude plugin marketplace add /home/august/insar-agent --scope project
claude plugin install insar-agent-skills@insar-agent
```

## Key Rules from AGENTS.md

- Domain knowledge (ISCE3 runconfigs, scripts, workflow notes) arrives as reference input and must be normalized into code/prompts/validations. Do not invent workflow parameters when source material is incomplete.
- Protocol-agnostic logic belongs in `core`. MCP wiring belongs in `mcp`. Engine behavior belongs in `engines/<engine>`.
- No runtime dependency on `cli-anything` or its package layout.
- When a dependency (e.g. MCP SDK) is not yet installed, preserve a clean scaffold and document the missing dep — do not guess around it.

## Current Status

**M0–M6 + skill-first architecture complete. 144 unit tests + 11 integration tests passing (2026-03-28).**

Before making non-trivial changes, read:

1. `docs/architecture.md` — system overview, layer boundaries, milestone status
2. `docs/mcp-tools.md` — full input/output spec for every MCP tool
3. `docs/domain-model.md` — Project, Job, WorkflowTemplate, Artifact field definitions
4. `docs/agent-guide.md` — AI constraint guide (single source of truth); served as `insar://workflow-guide` MCP resource

## Collaboration Workflow

The domain expert (user) provides ISCE3 processing scripts, runconfig templates, and workflow documentation. Claude Code implements the corresponding MCP tools and engine adapter code.

Knowledge base:
- `knowledge-base/tianxiaolong/` — primary: SKILL.md (workflow constraints), runconfig template, DEM/GeoTIFF scripts
- `knowledge-base/wangshuai/` — supplementary: stack/network preparation, MintPy time-series, baseline visualization

**Typical flow for each new capability:**
1. User provides ISCE3 script or runconfig template (in knowledge-base/)
2. Claude normalizes it into `engines/isce3/` (library module, not CLI)
3. Claude wires it as an MCP tool in `mcp/server.py`
4. Tests are added in `tests/unit/` or `tests/integration/`

**Milestone status:**
- M0: scaffold ✓
- M1: runconfig management ✓ — `insar_create_project`, `get/set/unset/validate/export runconfig`, project registry
- M2: job execution ✓ — `insar_run_workflow`, `insar_get_job_status`, `insar_get_job_logs`
- M3: output handling ✓ — `insar_list_outputs`
- M4: stack/network ✓ — `insar_prepare_stack`, `insar_prepare_network` (wangshuai two-layer architecture)
- M4b: agent onboarding ✓ — MCP Resources, Prompts, `next_step` guidance in tool returns
- M5: utilities ✓ — `insar_extract_bbox`, `insar_export_geotiff`; skill-first architecture (skills = single guidance source, MCP tools = pure execution)
- M5 (next): MintPy integration — `insar_run_mintpy`, `insar_plot_baseline` (run_mintpy_nisar_stack.sh, plot_isce3_baseline_network.py)

**engines/isce3/ modules:**
- `adapter.py` — ISCE3Adapter (list_workflows)
- `defaults.py` — ALLOWED_SET_FIELDS, REQUIRED_PATH_FIELDS, load_default_runconfig
- `validator.py` — validate_runconfig (required path checks)
- `runner.py` — build_workflow_command (conda run wrapper)
- `stack.py` — prepare_stack() (single-reference stack, from wangshuai)
- `network.py` — prepare_network() (interferogram network tbase/conn, from wangshuai)

**Agent onboarding (mcp/server.py):**
- Resource `insar://workflow-guide` — hard constraints + step order for both workflows
- Resource `insar://allowed-fields/{workflow}` — dynamic list of settable fields per workflow
- Prompt `process_insar_pair(ref, sec, dem, output_dir, conda_env)` — single-pair guided template
- Prompt `process_insar_batch(data_dir, dem, output_dir, network_mode, ...)` — batch stack/network template
- `poll` field in `insar_run_workflow` return (contains exact job_id for polling)
- `run_command` + `gunw_pattern` fields in `insar_prepare_stack` / `insar_prepare_network` returns
- All narrative `next_step` fields removed — workflow guidance is owned by skills, not MCP tools

**Test data:**
- NAS RSLC files: `/home/august/NAS/NISAR_wangshuai_data/` (referenced directly by integration tests)
- Fixture runconfig: `tests/fixtures/insar_nisar.yaml`
- Integration tests skip automatically if NAS not mounted

Full tool specs are in `docs/mcp-tools.md`. Domain object fields are in `docs/domain-model.md`.
