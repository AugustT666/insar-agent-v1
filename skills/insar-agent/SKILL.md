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
- For long-running jobs, use the `poll` call returned by the MCP tool, or call
  `insar_get_job` with the returned job id and context. If you need to wait, use
  only a bounded one-shot sleep and then poll the MCP tool again. Do not create
  Bash PID monitors, `kill -0` loops, `tail -f` loops, or other shell status
  checkers; zombie child processes can make PID-based monitors hang after the
  MCP job has actually finished.
- Do not invent workflow parameters when reference material is incomplete. Ask
  the user or collect metadata through `insar_describe_rslc` /
  `insar_describe_s1`.

## Session Bootstrap

Before routing into an execution workflow, collect only the cross-cutting session
facts that are missing for the requested workflow:

1. For ISCE3 execution, use the environment specified by the task/user; if none
   is specified, ask which ISCE3 environment to use (`isce3`, `isce3gpu`, or a
   project-specific name).
2. For MintPy, use workflow-specific defaults when available. In particular,
   ISCE2/topsStack MintPy defaults to `isce2` unless the task/user overrides it;
   ISCE3 MintPy should use a dedicated MintPy environment with `numpy<2`.
3. Ask whether the user has an approved base runconfig template path only for
   workflows that need one and do not already have a default.

Defer these questions when the user only wants documentation, architecture review,
or workflow consultation. Do not force environment prompts that the selected
workflow skill can resolve through a valid default.

## Preconditions Before Any Processing (开工前门检)

Before routing to any processing workflow, confirm two inputs exist; if either is
missing, STOP and ask the user — do not invent paths:

1. **`output_root`** — the single top-level directory passed to `insar_create_project`.
   Shared prepare inputs (DEM, SAFE, orbits, RSLC) land under `<output_root>/prepare/` and are
   **reused across runs** — a present DEM/SAFE is not re-downloaded.
2. **Input data paths** — whatever the user has (RSLC / SAFE / burst / zip / DEM).
   Inputs may be incomplete: if a required input (DEM, precise orbits) is missing,
   auto-complete it by calling the matching tool (e.g. `insar_download_dem`) rather
   than asking the user to fetch it.

Output location is OPTIONAL: if the user gives one, the product tools validate it
stays inside the workspace run root; if not, tools derive the default run directory.
After this gate the user is not asked about paths again. Layout:
- Shared inputs: `<output_root>/prepare/{dem,safe,orbits,rslc}/`
- Per-run products: `<output_root>/<task>_<timestamp>/insar_product/<subdir>/`
- Agent state + Layer-1 progress: `<run_root>/.insar_agent/progress.log`
- Raw engine logs (Layer-2): `<run_root>/insar_product/logs/`

Long tasks (≥2 scenes, DEM/orbit download, stack processing) auto-background:
tool returns `{job_id, status:"running", poll, monitor, log_path}`.
Always relay the `monitor` command to the user so they can watch Layer-1 progress live.
Poll with `insar_get_job` at minute-level intervals — NOT a tight while-true loop.

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
| Post-run review, YODO experience capture, plugin asset planning | `yodo` | Summarize the collaboration, classify the asset opportunity, and recommend development handoff |
| Ad-hoc / partial execution: run one segment, resume a window, rerun a stage, reprocess an intermediate | `freeform` | Use engine-native step granularity via existing gated MCP tools (resume_from_run / from_step-to_step / stage enabled toggles / mintpy start-end); never bash run_files directly |

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
