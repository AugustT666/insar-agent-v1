---
name: insar-agent
description: >
  This skill should be used when the user asks about NISAR, Sentinel-1,
  ISCE3, ISCE2, RSLC, SAFE, GUNW, interferograms, coherence, unwrapped phase,
  DEM preparation, MintPy, baseline plots, time-series analysis, environment
  setup, parameter tuning, or unclear InSAR workflow requests. It is the main
  InSAR workflow entry point for the insar-agent plugin and routes users to the
  correct workflow skill and insar_* MCP tools.
version: 0.1.0
---

# insar-agent — Main InSAR Workflow Entry Skill

Use this skill as the top-level router for the insar-agent plugin. Route each
request to the appropriate workflow skill, preserve session-level context, and
use `insar_*` MCP tools for execution.

## Core Principles

- Use `insar_*` MCP tools for all ISCE3/ISCE2 operations. Never run ISCE3,
  ISCE2, MintPy, or conda processing commands directly via shell.
- Treat skills as the workflow source of truth. MCP tools execute actions and
  return factual results.
- Set path-type runconfig fields through `insar_set_runconfig_value`. Set core
  processing parameters through the `param-advisor` flow and
  `insar_set_processing_param`.
- For long-running jobs, prefer background execution with an explicit log path
  and status-polling plan. Show the log path before or immediately after launch.
- Do not invent workflow parameters when reference material is incomplete. Ask
  the user or collect metadata through `insar_describe_rslc` /
  `insar_describe_s1`.

## Session Bootstrap

Before routing into an execution workflow, collect the cross-cutting session
facts once:

1. Read the MCP resource `insar://workflow-guide` to load hard workflow
   constraints.
2. Ask which conda environment to use for ISCE3 execution (`isce3`, `isce3gpu`,
   or a project-specific name).
3. Confirm whether the selected ISCE3 environment can run
   `nisar.workflows.insar`.
4. Ask which conda environment to use for MintPy. Keep this separate from the
   ISCE3 environment because MintPy 1.6.x requires `numpy<2` while ISCE3 often
   installs NumPy 2.x.
5. Ask whether the user has an approved base runconfig template path for this
   session.

Defer items 2-5 when the user only wants documentation, architecture review, or
workflow consultation. Collect them before any real data-processing workflow.

## Workflow Routing

Invoke the matching same-plugin skill via the Skill tool. In Claude Code plugin
usage, users may also invoke the namespaced form such as
`/insar-agent-plugin:insar-agent`.

| Task | Skill name | Inline fallback |
|------|------------|-----------------|
| First-time setup, ISCE3 / ISCE2 / MCP not installed | `env-setup` | Call `insar_check_env`, then guide installation |
| Data preparation: NISAR RSLC, Sentinel SAFE/ZIP, DEM, orbits | `data-prep` | Ask engine type, then route inline |
| Single NISAR RSLC pair to GUNW interferogram | `d-insar-isce3` | Path A: create project, set paths, tune params, run, poll |
| Multiple NISAR RSLC scenes to stack/network batch | `stack-insar-isce3` | Path B: prepare stack/network, run batch, poll |
| Sentinel-1 single pair with ISCE2 | `d-insar-isce2` | ISCE2 Path A inline |
| Sentinel-1 time-series stack with ISCE2 | `stack-insar-isce2` | ISCE2 Path B inline |
| MintPy time-series, displacement, baseline plot | `mintpy` | Plot baseline when relevant, run MintPy, poll |
| ISCE3 parameter tuning | `param-advisor` with `engine=isce3` | Collect metadata, then delegate to param-advisor subagent through the skill |
| ISCE2 parameter tuning | `param-advisor` with `engine=isce2` | Collect Sentinel metadata, then delegate to param-advisor subagent through the skill |

If a request spans multiple rows, route in dependency order. For example, run
`data-prep` before an engine-specific processing workflow when data is missing.

## Session Context Ownership

Keep these responsibilities separated:

- `insar-agent` skill: session bootstrap, engine choice, high-level routing,
  MCP server status awareness.
- Workflow skills: DEM paths, output directories, pair strategy, MintPy config,
  interaction mode, step ordering.
- `param-advisor` skill: evidence collection, expert subagent delegation, diff
  presentation, user confirmation, parameter application, and full YAML echo.
- MCP server: final allowlist enforcement and factual execution.

## Parameter Advisory Delegation

When parameter tuning is needed, invoke the `param-advisor` skill with the
appropriate engine and workflow context:

- NISAR / ISCE3: use `param-advisor` with `engine=isce3`; metadata comes from
  `insar_describe_rslc`.
- Sentinel-1 / ISCE2: use `param-advisor` with `engine=isce2`; metadata comes
  from `insar_describe_s1` and workflow-specific templates (`tops`, `stack`).

Do not present the parameter diff, collect the three-way confirmation, or call
`insar_set_processing_param` from this entry skill. Those actions belong to the
`param-advisor` skill. After `param-advisor` completes, resume the original
workflow skill.

## Constraint Hierarchy

```text
insar-agent skill (session bootstrap + routing)
  → workflow skills (step sequencing + interaction gates)
    → param-advisor skill (parameter advice orchestration when needed)
      → param-advisor subagent (advisory-only recommendation package)
        → MCP server allowlists and validators (hard enforcement)
```

`key_not_allowed` and validation errors from the MCP server are hard blocks and
must not be bypassed by client-side instructions.

## Hard Constraints

- Do not run ISCE3, ISCE2, MintPy, conda, or processing shell commands directly;
  use `insar_*` MCP tools.
- Do not set core processing parameters via `insar_set_runconfig_value`.
- Do not skip session bootstrap when the user intends to process data.
- Do not invent workflow parameters when source material is incomplete.
- Do not directly generate parameter recommendations when the
  `param-advisor` skill/subagent flow applies.


---

## 任务小结（Task Debrief — 强制执行）

任务最后一步，无论成功或失败，必须输出以下结构化小结，不得跳过。

```
【任务小结】
实验 ID / run_id：<task_id 或 N/A>_<run_id 或 N/A>

工作流合规性
  Skill 流程：<完全遵循 | 部分偏离 | 严重偏离>
  MCP 工具：<全程使用 mcp__insar-agent__* 接口 | 部分绕过 | 未使用>

偏离记录（如无填"无"）
  1. <偏离点：说明发生了什么，与 skill 规定步骤的差异>

根因分类（有偏离时勾选，可多选）
  □ Skill 指引不完备（步骤缺失 / 说明不清 / 边界条件未覆盖）
  □ MCP 工具问题（参数不直观 / 返回值格式异常 / 工具功能缺失）
  □ 环境 / 数据问题（conda env / 文件路径 / 权限 — 非插件问题）
  □ 其他：___

开发 agent 介入建议
  需要介入：<是 | 否>
  建议：<具体改进点，说明异常在哪、应如何修复 | "无">

最终结果：<成功 | 失败>
摘要：<一句话：处理了什么数据，产生了什么产品>
```
