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
- For long-running jobs, prefer one-shot self-paced background monitoring: choose the wait interval from current workflow evidence, call Bash with `run_in_background=true`, and on wake use `insar_get_job` plus the explicit log path to report progress without blocking the session.
- Do not invent workflow parameters when reference material is incomplete. Ask
  the user or collect metadata through `insar_describe_rslc` /
  `insar_describe_s1`.

## Session Bootstrap

Before routing into an execution workflow, collect only the cross-cutting session
facts that are missing for the requested workflow:

1. Read the MCP resource `insar://workflow-guide` to load hard workflow
   constraints. Call `insar_check_env` first to get the correct `mcp.server_name`,
   then pass it to `readMcpResource`. Both `uri` and `server` are required:
   `readMcpResource(uri="insar://workflow-guide", server=<mcp.server_name>)`.
   If `insar_check_env` is unavailable, use `plugin:insar-agent-plugin:insar-mcp-server`
   (colons, not underscores) as the fallback server name.
2. For ISCE3 execution, use the environment specified by the task/user; if none
   is specified, ask which ISCE3 environment to use (`isce3`, `isce3gpu`, or a
   project-specific name).
3. For MintPy, use workflow-specific defaults when available. In particular,
   ISCE2/topsStack MintPy defaults to `isce2` unless the task/user overrides it;
   ISCE3 MintPy should use a dedicated MintPy environment with `numpy<2`.
4. Ask whether the user has an approved base runconfig template path only for
   workflows that need one and do not already have a default.

Defer these questions when the user only wants documentation, architecture review,
or workflow consultation. Do not force environment prompts that the selected
workflow skill can resolve through a valid default.

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
- Do not use the Read tool to read skill files directly. Always invoke skills
  through the Skill tool (`Skill(insar-agent-plugin:<skill-name>)`).
