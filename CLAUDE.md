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
pytest                                              # run default test suite (excludes real_data)
pytest -m real_data tests/integration -q            # run real-data tests explicitly
pytest tests/unit/test_smoke.py::test_name         # run a single test
pip install -e ".[dev]"                             # install with dev deps
```

`pytest` resolves `src/` automatically. Use `PYTHONPATH=src python -m insar_agent.mcp.server --stdio` to run the MCP server directly.

## Architecture

```
Agent Client (Codex / Claude Code / etc.)
  -> insar_agent.mcp        # MCP protocol wiring, tool/resource/prompt definitions
  -> insar_agent.core       # Protocol-agnostic domain logic (Project, Job, config)
  -> insar_agent.engines.isce3  # ISCE3-specific adapter, validators, runner
  -> insar_agent.engines.isce2  # ISCE2-specific adapter, runner, stack
  -> runtime + local conda env
```

**`skills/`** — Claude Code skill files, packaged as a local plugin (`insar-agent-skills@insar-agent`). Invoke with the Skill tool:
- `insar-agent` — session router / entry point
- `env-setup` — environment check & installation guide (ISCE3/ISCE2/MintPy/MCP)
- `data-prep-nisar` — download NISAR RSLC data (ASF) and DEM (Copernicus 30m)
- `d-insar-isce3` — single RSLC pair → GUNW product (NISAR/ISCE3, Path A)
- `stack-insar-isce3` — multi-scene batch stack + network (NISAR/ISCE3, Path B)
- `param-advisor` — unified parameter-advisory workflow entry point for ISCE3 and ISCE2
- `mintpy` — time-series analysis with MintPy across ISCE3 and ISCE2
- `d-insar-isce2` — single S1 pair → interferogram (Sentinel-1/ISCE2, topsApp)
- `stack-insar-isce2` — S1 time-series stack (Sentinel-1/ISCE2, stackSentinel + MintPy)

Plugin setup (run once, or after `skills/` changes):
```bash
claude plugin marketplace add /home/august/insar-agent --scope project
claude plugin install insar-agent-skills@insar-agent
```

For skill-aware clients, parameter advisory follows a plugin contract rather
than an MCP contract. The `param-advisor` skill must call the engine-appropriate
describe tool, then delegate recommendation generation to the project subagent
defined in `.claude/agents/param-advisor.md`. That subagent is
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

**Test data:** NAS RSLC files at `/home/august/NAS/NISAR_wangshuai_data/`; real-data tests are marked `real_data` and are excluded from default `pytest` runs unless explicitly selected.
