---
name: insar-agent
description: >
  Entry point for all insar-agent tasks. Invoke this skill at the start of any
  InSAR processing session, when the user mentions NISAR, ISCE3, RSLC, GUNW,
  interferogram, coherence, unwrapped phase, InSAR, DEM preparation, time-series
  analysis, MintPy, smallbaselineApp, displacement, baseline plot, or temporal
  coherence. Also invoke when the user asks "how do I start", environment setup is
  needed, or it is unclear which specific workflow applies. Always invoke this skill
  before any other insar-agent skill.
---

# insar-agent — Session Router

## Core principles

- Use `insar_*` MCP tools for all ISCE3 operations. Do not run ISCE3 shell commands directly.
- Skills define what to do and in what order. MCP tools execute the actions and return factual results.
- Path-type fields are set via `insar_set_runconfig_value`. Core processing parameters are set via `insar_set_processing_param`. Both tools enforce allowlists server-side.
- When the user requests parameter tuning or provides scene/data characteristics that affect multilook, filtering, unwrapping, or atmospheric corrections, route into `param-advisor-isce3`.
- `param-advisor-isce3` is the unified parameter-advisory skill. It owns `insar_describe_rslc`, project-level subagent delegation, diff presentation, and user confirmation.
- The metadata-first entry point for parameter advice remains `insar_describe_rslc`; automatic external search is allowed only when local evidence is insufficient.
- Do not invent workflow parameters when reference material is incomplete. Ask the user.

## Skill routing

Select the skill that matches the user's task and invoke it:

| Task | Skill |
|------|-------|
| First-time setup, ISCE3 or MCP not installed | `env-setup-nisar` |
| Download NISAR RSLC data or prepare/download DEM | `data-prep-nisar` |
| Single RSLC pair → GUNW interferogram product | `d-insar-isce3` |
| Multiple RSLC scenes → interferogram network (batch) | `stack-insar-isce3` |
| MintPy time-series, displacement, baseline plot | `mintpy-isce3` |
| Any parameter tuning / advisory request | `param-advisor-isce3` |

If the task spans multiple rows (e.g., data is missing AND a single pair needs processing),
invoke `data-prep-nisar` first, then `D-InSAR-isce3`.

## Constraint hierarchy

```
skills (guidance)  →  server-side ALLOWED_SET_FIELDS (hard block on core params)
```

Skills are the single source of truth for workflow steps and ordering.
The MCP server is the final enforcement layer — `key_not_allowed` cannot be bypassed.
