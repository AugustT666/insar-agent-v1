# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Read First

**开发（修改代码、新增工具）：**
1. `docs/developer-documents/dev-plan.md` — 当前进度、待办、协作方向
2. `docs/architecture.md` — 层次边界、MCP 设计原则、核心数据模型

**应用（作为 agent 执行 InSAR 处理）：**
1. `docs/agent-guide.md` — 工作流硬约束（同 `insar://workflow-guide`）

## Commands

```bash
pip install -e ".[dev]"                             # install with dev deps
pytest                                              # default suite; excludes real_data marker
pytest -m real_data tests/integration -q            # real-data tests (opt-in)
pytest tests/unit/test_smoke.py::test_name          # single test
pytest --cov=src --cov-report=term-missing          # coverage
ruff check src tests                                # lint (dev dep)
mypy src                                            # type check (dev dep)

insar-agent describe                                # active MCP surface (JSON)
insar-agent doctor                                  # runtime / conda env checks (JSON)
insar-mcp-server --describe                         # inspect MCP tools/resources/prompts
insar-mcp-server --stdio                            # launch stdio server for agent clients
```

Console scripts (`insar-agent`, `insar-mcp-server`) are wired in `pyproject.toml` and available after `pip install -e`. `pytest` resolves `src/` via `pythonpath` config; when running modules without install use `PYTHONPATH=src python -m insar_agent.mcp.server --stdio`.

## Architecture

```
Agent Client (Codex / Claude Code / etc.)
  -> insar_agent.mcp            # FastMCP stdio server; tool/resource/prompt wiring only
  -> insar_agent.core           # Protocol-agnostic: Project, Job, BatchJob, config, session
  -> insar_agent.engines.isce3  # NISAR/ISCE3: adapter, validator, runner, stack, network,
                                #   dem, bbox, geotiff, rslc_metadata, mintpy, param_advisor
  -> insar_agent.engines.isce2  # Sentinel-1/ISCE2: adapter, runner, sentinel_prep,
                                #   stack, mintpy, param_advisor, validator, defaults
  -> insar_agent.runtime        # workspace layout, conda env detection, logging
  -> local conda environment(s) invoked via `conda run`
```

Core persistence lives under `{workspace_root}/.insar_agent/project.json` and `.insar_agent/jobs/{job_id}.json`; batch and MintPy jobs persist beside their own output roots (see `docs/architecture.md` §Workspace Layout).

**`skills/`** — Claude Code skill files, packaged as a local plugin (`insar-agent-skills@insar-agent`). Covers the `insar-agent` entry router, env setup, data prep, Path A/B for each engine, MintPy, and param advisory. Invoke via the Skill tool; definitions live under `skills/<name>/SKILL.md`. Session entry point is `skills/insar-agent/SKILL.md`, a Claude Code plugin skill that routes to workflow skills and MCP tools. Claude Code agents are used as subagents/workers, not primary session takeovers.

Plugin setup (run once, or after `skills/` changes):
```bash
claude plugin marketplace add <insar-agent-repo> --scope project
claude plugin install insar-agent-skills@insar-agent
```

For skill-aware clients, parameter advisory follows a plugin contract rather
than an MCP contract. The `param-advisor` skill must call the engine-appropriate
describe tool, then delegate recommendation generation to the project subagent
defined in `agents/param-advisor.md`. That subagent is
advisory-only, cites evidence, and may use models such as `gpt-5.3-codex`
depending on the host client. MCP tools do not enforce whether the subagent was
spawned; they only validate and apply the requested changes.

## Key Rules

- Domain knowledge (ISCE3 runconfigs, scripts, workflow notes) arrives as reference input and must be normalized into code/prompts/validations. Do not invent workflow parameters when source material is incomplete.
- Protocol-agnostic logic belongs in `core`. MCP wiring belongs in `mcp`. Engine behavior belongs in `engines/<engine>`.
- When a dependency (e.g. MCP SDK) is not yet installed, preserve a clean scaffold and document the missing dep — do not guess around it.
- MCP tool design principles (数量优先, unified Job model, etc.) are in `docs/architecture.md`.

## Collaboration

The domain expert (user) provides ISCE3 processing scripts, runconfig templates, and workflow documentation. Claude Code normalizes them into `engines/isce3/` as library modules (not CLIs), wires MCP tools in `mcp/server.py`, and adds tests in `tests/unit/` or `tests/integration/`. See `docs/developer-documents/dev-plan.md` for milestone history and the canonical typical-flow steps.

Knowledge archive:
- `docs/archive/knowledge-base/tianxiaolong/` — workflow constraints, runconfig templates, DEM/GeoTIFF scripts
- `docs/archive/knowledge-base/wangshuai/` — stack/network prep, MintPy time-series, baseline visualization

**Test data:** Real-data tests are marked `real_data` and are excluded from default `pytest` runs unless explicitly selected.
