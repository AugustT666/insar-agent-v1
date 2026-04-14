---
name: insar-agent
description: >
  Entry point for all insar-agent tasks. Invoke this skill at the start of any
  InSAR processing session, when the user mentions NISAR, Sentinel-1, ISCE3, ISCE2,
  RSLC, SAFE, GUNW, interferogram, coherence, unwrapped phase, InSAR, DEM
  preparation, time-series analysis, MintPy, smallbaselineApp, displacement,
  baseline plot, or temporal coherence. Also invoke when the user asks "how do I
  start", environment setup is needed, or it is unclear which specific workflow
  applies. Always invoke this skill before any other insar-agent skill.
---

# insar-agent — Session Router

## Core principles

- Use `insar_*` MCP tools for all ISCE3 operations. Do not run ISCE3 shell commands directly.
- Skills define what to do and in what order. MCP tools execute the actions and return factual results.
- Path-type fields are set via `insar_set_runconfig_value`. Core processing parameters are set via `insar_set_processing_param`. Both tools enforce allowlists server-side.
- For long-running processing jobs, prefer background execution with an explicit log path and status-polling plan. Show the user the log path before or immediately after launch so they can inspect progress independently.
- When the user requests parameter tuning or provides scene/data characteristics that affect multilook, filtering, unwrapping, or atmospheric corrections, route into the engine-appropriate advisor skill.
- NISAR / ISCE3 uses `param-advisor` with `insar_describe_rslc`.
- Sentinel / ISCE2 uses `param-advisor` with `insar_describe_s1` and workflow-specific templates (`tops`, `stack`).
- The metadata-first entry point for parameter advice remains `insar_describe_rslc`; automatic external search is allowed only when local evidence is insufficient.
- Do not invent workflow parameters when reference material is incomplete. Ask the user.

## Session bootstrap

Before routing into any execution skill, confirm the cross-cutting runtime facts once per session:

- Which conda env should be used for ISCE3 execution (`isce3` / `isce3gpu` / project-specific name)
- Whether the chosen ISCE3 env can actually run `nisar.workflows.insar`
- Which conda env should be used for MintPy — **this must be a separate env from ISCE3**
  (MintPy 1.6.x requires `numpy<2`; ISCE3 typically installs numpy 2.x)
  Standard MintPy env: `conda create -n mintpy -c conda-forge python=3.11 mintpy "numpy<2"`
- Whether the user already has an approved base runconfig template path for this session

If the user only wants documentation or workflow review, you can defer these questions.
If the user wants to actually process data, ask them here before routing into `d-insar-isce3`,
`stack-insar-isce3`, or `mintpy`.

## Skill routing

Select the skill that matches the user's task and invoke it:

| Task | Skill |
|------|-------|
| First-time setup, ISCE3 / ISCE2 / MCP not installed | `env-setup` |
| Data preparation (NISAR RSLC, Sentinel SAFE, DEM, orbits) | `data-prep` |
| Single RSLC pair → GUNW interferogram product | `d-insar-isce3` |
| Multiple RSLC scenes → stack and/or network batch (independent, run either or both) | `stack-insar-isce3` |
| Sentinel-1 single pair with ISCE2 | `d-insar-isce2` |
| Sentinel-1 time-series stack with ISCE2 | `stack-insar-isce2` |
| MintPy time-series, displacement, baseline plot | `mintpy` (with engine parameter) |
| ISCE3 parameter tuning | `param-advisor` (with engine=isce3) |
| ISCE2 parameter tuning | `param-advisor` (with engine=isce2) |

If the task spans multiple rows (e.g., data is missing AND a single pair needs processing),
invoke `data-prep` first to choose engine and prepare inputs, then proceed to the engine-specific workflow skill.

Routing rule for runtime context:

- `insar-agent` owns session-level execution context such as conda env choice
- Workflow skills own workflow-local inputs such as DEM path, output dir, pair strategy, and MintPy config

## Constraint hierarchy

```
skills (guidance)  →  server-side ALLOWED_SET_FIELDS (hard block on core params)
```

Skills are the single source of truth for workflow steps and ordering.
The MCP server is the final enforcement layer — `key_not_allowed` cannot be bypassed.
