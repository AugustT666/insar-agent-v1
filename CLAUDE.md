# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Read First

Before making any non-trivial change, read these in order:

1. `docs/developer-documents/dev-plan.md` — collaboration master document for current progress, pending work, and agreed implementation direction
2. `docs/architecture.md` — system overview, execution modes, core data model, and current boundaries
3. `docs/mcp-tools.md` — full tool, resource, and prompt contract
4. `docs/agent-guide.md` — hard workflow constraints served as `insar://workflow-guide`

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

# Run the MCP server
PYTHONPATH=src python -m insar_agent.mcp.server --describe
PYTHONPATH=src python -m insar_agent.mcp.server --stdio
# or after installing: insar-mcp-server --describe

# Install in editable mode with dev deps
pip install -e ".[dev]"
```

`pytest` resolves `src/` automatically via `pythonpath = ["src"]` in `pyproject.toml`. The `PYTHONPATH=src` prefix is only needed when running modules directly.

## Architecture

`docs/architecture.md` is the canonical system-overview document. Read it for
the authoritative description of layers, execution modes, domain objects, and
the current parameter-advisor split.

Only keep the high-level boundary in mind here:

```
Agent Client (Codex / Claude Code / etc.)
  -> insar_agent.mcp        # MCP protocol wiring, tool/resource/prompt definitions
  -> insar_agent.core       # Protocol-agnostic domain logic (Project, Job, config)
  -> insar_agent.engines.isce3  # ISCE3-specific adapter, validators, runner
  -> runtime + local conda env
```

**`skills/`** — Claude Code skill files, packaged as a local plugin (`insar-agent-skills@insar-agent`) and installed into Claude Code. Invoke with the Skill tool:
- `data-prep-nisar` — download NISAR RSLC data (ASF) and DEM (Copernicus 30m)
- `d-insar-isce3` — single RSLC pair → GUNW product (Path A, M1-M3 tools)
- `stack-insar-isce3` — multi-scene batch stack + network (Path B, M4 tools)
- `param-advisor-isce3` — unified parameter-advisory workflow entry point
- `env-setup-nisar` — ISCE3 + MCP installation guide
- `insar-agent` — session router / entry point

Plugin setup (run once, or after skills/ changes):
```bash
claude plugin marketplace add /home/august/insar-agent --scope project
claude plugin install insar-agent-skills@insar-agent
```

For skill-aware clients, parameter advice uses a three-layer plugin contract. The main session routes into `skills/param-advisor-isce3/SKILL.md`, that skill gathers metadata-first evidence via `insar_describe_rslc`, then delegates recommendation generation to the project-level subagent defined in `.claude/agents/param-advisor-isce3.md`. The subagent may consult `.claude/agents/references/param-advisor-isce3.md` for advisory heuristics while keeping its own file focused on contract and output shape. If local evidence is still insufficient, the advisor may use external search and must return complete provenance so the user can decide what to trust. MCP tools cannot enforce that delegation; they only enforce white-listed parameter updates and validation. Use a frontier-capable model such as `claude-sonnet-4-6` (Claude Sonnet 4.6) or an equivalent model with capability comparable to `gpt-5.3-codex` (GPT-5.3-Codex), not a weak mini-tier model.

## Key Rules

- Domain knowledge (ISCE3 runconfigs, scripts, workflow notes) arrives as reference input and must be normalized into code/prompts/validations. Do not invent workflow parameters when source material is incomplete.
- Protocol-agnostic logic belongs in `core`. MCP wiring belongs in `mcp`. Engine behavior belongs in `engines/<engine>`.
- When a dependency (e.g. MCP SDK) is not yet installed, preserve a clean scaffold and document the missing dep — do not guess around it.

## MCP Tool Design Principles

MCP tool count directly affects AI agent decision depth — fewer, more semantic tools mean faster decisions and shorter task chains.

1. **数量优先**：每个新能力首先问"能否扩展现有工具"，不能才增加新工具。
2. **合并同概念操作**：同一概念的读/写/删不超过 2 个工具，能合并参数就不拆工具。
3. **顺序必然的步骤合并**：如 validate → export → run 必然顺序执行，合并为一个工具，内部串联。
4. **统一 Job 模型**：任何新 workflow 类型必须复用标准 `Job` dataclass 和 `project_id` 索引，禁止创建平行的状态追踪机制。
5. **小而美**：工具语义清晰、职责单一；优先精简，非必要不新增；必要时可新增（有明确职责边界即合理）。

## Current Status

**Current FastMCP surface: 17 active tools. Fresh verification on 2026-03-31: `pytest -q` → 205 passed, 1 warning.**

## Collaboration Workflow

The domain expert (user) provides ISCE3 processing scripts, runconfig templates, and workflow documentation. Claude Code implements the corresponding MCP tools and engine adapter code.

Historical source archive:
- `docs/archive/knowledge-base/tianxiaolong/` — primary archived references: workflow constraints, runconfig templates, DEM/GeoTIFF scripts
- `docs/archive/knowledge-base/wangshuai/` — supplementary archived references: stack/network preparation, MintPy time-series, baseline visualization

**Typical flow for each new capability:**
1. User provides ISCE3 script or runconfig template (archived under `docs/archive/knowledge-base/` when retained)
2. Claude normalizes it into `engines/isce3/` (library module, not CLI)
3. Claude wires it as an MCP tool in `mcp/server.py`
4. Tests are added in `tests/unit/` or `tests/integration/`

**Milestone status:**
- M0: scaffold ✓
- M1: runconfig management ✓ — `insar_create_project`, `insar_get/set_runconfig`, project registry
- M2: job execution ✓ — `insar_run_workflow` (auto validate+export+launch), `insar_get_job`
- M3: output handling ✓ — `insar_list_outputs`
- M4: stack/network ✓ — `insar_prepare_stack`, `insar_prepare_network` (wangshuai two-layer architecture)
- M4b: agent onboarding ✓ — MCP Resources, Prompts, skill-first architecture
- M5: utilities ✓ — `insar_extract_bbox`, `insar_export_geotiff`
- M7 metadata-first advisor update ✓ — `insar_describe_rslc`, metadata-first parameter advisory flow, provenance-aware subagent contract
- M6: MintPy ✓ — `insar_run_mintpy`, `insar_plot_baseline`
- Refinement (2026-03-29 checkpoint): MCP API consolidated 21→15 tools; `insar_discover`, `insar_get_job` (unified ISCE3+MintPy), `insar_set_runconfig_value` (value=None unsets), `insar_run_workflow` absorbs validate+export
- M4c (2026-03-30): added `insar_run_batch`; `insar_get_job` now covers batch jobs via `batch_dir`; 171 unit tests
- Current active MCP surface: 17 tools after the M4c + metadata-advisor additions
- M7 remote / automation follow-ups: TBD

**engines/isce3/ modules:**
- `adapter.py` — ISCE3Adapter (list_workflows)
- `defaults.py` — ALLOWED_SET_FIELDS, REQUIRED_PATH_FIELDS, load_default_runconfig, get_processing_param_keys, load_processing_params
- `validator.py` — validate_runconfig (required path checks)
- `runner.py` — build_workflow_command (conda run wrapper)
- `stack.py` — prepare_stack() (single-reference stack, from wangshuai)
- `network.py` — prepare_network() (interferogram network tbase/conn, from wangshuai)
- `bbox.py` — union_bbox() (RSLC bounding box extraction)
- `geotiff.py` — export_geotiff() (HDF5 → GeoTIFF conversion)
- `rslc_metadata.py` — summarize_rslc(), describe_rslc_pair() (metadata-first RSLC profiling for the advisor)
- `mintpy.py` — run_mintpy(), get_mintpy_status()
- `baseline.py` — plot_baseline_network()
- `assets/processing_params_insar.yaml` — whitelist of tunable processing parameters for `insar_set_processing_param`

**Agent onboarding (mcp/server.py):**
- Resource `insar://workflow-guide` — hard constraints + step order for both workflows
- Resource `insar://allowed-fields/{workflow}` — dynamic list of settable fields per workflow
- Prompt `process_insar_pair(ref, sec, dem, output_dir, conda_env)` — single-pair guided template
- Prompt `process_insar_batch(data_dir, dem, output_dir, network_mode, ...)` — batch stack/network template
- `poll` field in `insar_run_workflow` and `insar_run_mintpy` returns (exact `insar_get_job(...)` call for polling)
- `run_command` + `gunw_pattern` fields in `insar_prepare_stack` / `insar_prepare_network` returns
- All narrative `next_step` fields removed — workflow guidance owned by skills, not MCP tools

**Test data:**
- NAS RSLC files: `/home/august/NAS/NISAR_wangshuai_data/` (referenced directly by integration tests)
- Fixture runconfig: `tests/fixtures/insar_nisar.yaml`
- Integration tests skip automatically if NAS not mounted

Full tool specs and domain-object overview are in `docs/mcp-tools.md` and `docs/architecture.md`.
