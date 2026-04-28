# InSAR-Agent: Skills vs. MCP Boundary Analysis

## Executive Summary

The insar-agent repository implements a **clear delegation boundary** between Claude Code **Plugin Skills** (workflow guidance, decision routing, constraint enforcement) and **MCP Tools** (deterministic execution, data validation, subprocess management).

- **Skills own**: Workflow narrative, tool sequencing, parameter advisory logic, client-aware branching, user confirmation loops
- **MCP owns**: ISCE3/ISCE2 command construction, conda execution, project persistence, allowlist enforcement, error handling
- **Plugin Contract**: Parameter advisory logic explicitly delegates to `.claude/agents/param-advisor.md` subagent to prevent context pollution

This design answers the question: **Why not only use skills?** Because skills cannot enforce server-side validation, handle background processes, or provide reproducible tool contracts independent of the client model or personality.

---

## I. Skills Directory: 11 Skill Files

### Location
`/home/august/insar-agent/skills/`

### Responsibility Map

| Skill | File Path | Primary Responsibility | Key Constraints |
|-------|-----------|------------------------|-----------------|
| **insar-agent** | `insar-agent/SKILL.md` | Session entry point, runtime context bootstrap, skill routing | Must confirm conda env, MCP server status; owns execution context (env choice) across session |
| **env-setup** | `env-setup/SKILL.md` | First-time environment checks, installation guidance | Checks `insar_check_env()` status; delegates to conda commands; no state persistence |
| **data-prep** | `data-prep/SKILL.md` | Data preparation strategy router | Routes to `data-prep-nisar` or `data-prep-sentinel` based on input type |
| **data-prep-nisar** | `data-prep-nisar/SKILL.md` | NISAR RSLC + DEM download, AOI crop guidance | Uses `insar_download_rslc`, `insar_download_dem`, `insar_download_scene` MCP tools |
| **data-prep-sentinel** | `data-prep-sentinel/SKILL.md` | Sentinel-1 SAFE download + Sentinel data prep workflow | Routes to `insar_prepare_sentinel_data` MCP tool |
| **d-insar-isce3** | `d-insar-isce3/SKILL.md` | Single RSLC pair → GUNW workflow (Path A, NISAR) | Hard-codes workflow step order; gates param-advisor at Step 2.5; owns `interaction_mode` logic |
| **d-insar-isce2** | `d-insar-isce2/SKILL.md` | Single Sentinel-1 pair → ISCE2 workflow (Path A, Sentinel) | Enforces TOPS workflow; manages parameter confirmation gates |
| **stack-insar-isce3** | `stack-insar-isce3/SKILL.md` | Multi-scene RSLC → stack/network batch (Path B, NISAR) | Coordinates `insar_prepare_stack` + `insar_prepare_network` sequencing; gates param-advisor |
| **stack-insar-isce2** | `stack-insar-isce2/SKILL.md` | Multi-scene Sentinel-1 → ISCE2 batch stack | Manages parallel batch execution through MCP |
| **mintpy** | `mintpy/SKILL.md` | Time-series analysis (baseline plot, displacement) | Enforces ISCE3/ISCE2 env separation (numpy<2); owns baseline review pause point |
| **param-advisor** | `param-advisor/SKILL.md` | Unified parameter tuning orchestrator | **Plugin contract**: must call engine-specific `describe_*` tool, then delegate to `.claude/agents/param-advisor.md` subagent; cannot directly invoke `insar_set_processing_param` |

---

## II. MCP Tool Surface: 24 Registered Tools + 2 Resources + 2 Prompts

The source of truth for this count is the `@mcp.tool()` registration surface in
`src/insar_agent/mcp/server.py`. The current `--describe` summary lists 22 tools
because `build_server_description()` is missing `insar_export_runconfig` and
`insar_run_mintpy_isce2`; fixing that summary is a documentation/runtime
consistency task, not a change to the actual FastMCP registration surface.

### Location
`/home/august/insar-agent/src/insar_agent/mcp/server.py` (2,956 lines)

### Responsibility Map

| Category | Tools | Ownership |
|----------|-------|-----------|
| **Discovery & Env** | `insar_discover`, `insar_check_env` | Runtime status; no side effects |
| **Project Lifecycle** | `insar_create_project`, `insar_get_project` | Project registry (`{workspace}/.insar_agent/project.json`) |
| **Config Management** | `insar_get_runconfig`, `insar_set_runconfig_value`, `insar_set_processing_param`, `insar_export_runconfig` | Allowlist enforcement (`ALLOWED_SET_FIELDS` in `defaults.py`); YAML persistence |
| **Execution** | `insar_run_workflow`, `insar_get_job`, `insar_list_outputs` | Job lifecycle, conda execution, log capture |
| **Batch Processing** | `insar_prepare_stack`, `insar_prepare_network`, `insar_run_batch` | Runconfig generation, parallel batch runner scripts |
| **Time-Series** | `insar_run_mintpy`, `insar_run_mintpy_isce2`, `insar_plot_baseline` | MintPy config management, baseline visualization |
| **Data (NISAR)** | `insar_describe_rslc`, `insar_download_rslc`, `insar_download_dem`, `insar_export_geotiff` | Metadata extraction, remote HDF5 cropping, GeoTIFF conversion |
| **Data (Sentinel)** | `insar_describe_s1`, `insar_download_scene`, `insar_prepare_sentinel_data` | Sentinel metadata parsing, SAFE archive handling |

### Resources (Served as `insar://` URIs)
```
insar://workflow-guide              → /home/august/insar-agent/docs/agent-guide.md
insar://allowed-fields/{workflow}   → Dynamically generated field allowlists per engine/workflow
```

### Prompts
```
process_insar_pair(reference_rslc, secondary_rslc, dem, output_dir, conda_env)
process_insar_batch(rslc_dir, dem, output_dir, network_mode, conda_env)
```

---

## III. Plugin Contract: The Parameter Advisory Pattern

### Why Parameter Advisory Is NOT Just an MCP Tool

**The Problem:**
Parameter recommendations for InSAR processing require:
1. **Local metadata inspection** (sensor, baseline, coherence patterns)
2. **Evidence-based reasoning** (why change the default? what risk?)
3. **User acceptance loop** (show diff → user confirms → apply)

If this were purely MCP, every request would require:
- An `insar_get_runconfig()` call to fetch full YAML
- A question to the LLM to generate advice
- User confirmation in the same turn

This creates context pollution and makes the advice entangled with client model personality.

### The Solution: Skill + Subagent Delegation

**Main skill** (`skills/param-advisor/SKILL.md`):
- Collects minimal evidence (engine, project context, scene metadata via `insar_describe_rslc` / `insar_describe_s1`)
- Builds compressed evidence profile
- **Delegates to project-level subagent** (`.claude/agents/param-advisor.md`)
- Shows user a diff preview
- Applies accepted changes via `insar_set_processing_param`

**Subagent** (`.claude/agents/param-advisor.md`):
- Advisory-only; does not call MCP tools
- Reads compressed evidence + reference asset (`.claude/agents/references/param-advisor-isce{engine}.md`)
- Outputs structured recommendation package with:
  - `advisory_only: true`
  - `user_responsibility_notice`
  - `provenance` for each parameter change
  - `changes`, `sources`, `yaml_diff_preview`
- **Does not talk to end user**
- Performs web search to supplement local evidence

**Hard Constraints** (from `docs/agent-guide.md` line 16-21):
```
For skill-aware clients, parameter advice is a plugin contract: the main agent
must route into the unified advisor skill and that skill must
delegate advice generation to its project-level subagent.
  - NISAR / ISCE3: skills/param-advisor/SKILL.md + engine=isce3 → .claude/agents/param-advisor.md → insar_describe_rslc
  - Sentinel / ISCE2: skills/param-advisor/SKILL.md + engine=isce2 → .claude/agents/param-advisor.md → insar_describe_s1
MCP cannot verify this at protocol level; it only enforces the MCP contract (allowlists + validation).
```

---

## IV. Hard Constraints: Where Skills and MCP Enforce Boundaries

### Skills Enforce (Soft, Client-Aware)

1. **Workflow sequencing** (d-insar-isce3 skill lines 45–135)
   - Step 1: Create project
   - Step 2: Set path fields
   - **Step 2.5 (GATE)**: Ask about param tuning (interactive) or auto-enter param-advisor (auto mode)
   - Step 3: Run workflow

2. **Interaction mode branching** (e.g., d-insar-isce3 line 24–30)
   - `interactive` (default): pause at gates, ask user
   - `auto`: skip gates, auto-apply recommendations

3. **Session bootstrap** (insar-agent skill lines 27–40)
   - Must confirm conda env names upfront
   - Must verify ISCE3 env can run `nisar.workflows.insar`
   - Must confirm separate MintPy env (numpy<2 requirement)

4. **Constraint hierarchy** (insar-agent skill lines 66–72)
   ```
   skills (guidance) → server-side ALLOWED_SET_FIELDS (hard block)
   ```

### MCP Enforces (Hard, Server-Side)

1. **Allowlist enforcement** (`src/insar_agent/engines/isce3/defaults.py`)
   ```python
   ALLOWED_SET_FIELDS = {
       "insar": [
           "runconfig.groups.input_file_group.reference_rslc_file",
           "runconfig.groups.input_file_group.secondary_rslc_file",
           "runconfig.groups.input_file_group.dem_file",
           # ... path fields only
       ]
   }
   ```
   - `insar_set_runconfig_value()` rejects non-whitelisted keys with `key_not_allowed`
   - `insar_set_processing_param()` only accepts whitelist-controlled param keys
   - **This is server-side truth** — cannot be bypassed by any client

2. **Validation & conda execution** (`insar_run_workflow`)
   - Validates runconfig before launch
   - Exports YAML to disk
   - Runs `conda run -n <env> python -m nisar.workflows.<workflow> /path/to/runconfig.yaml`
   - Captures exit code + logs
   - Returns `job_id` for polling

3. **Job persistence** (`src/insar_agent/core/job.py`)
   - All jobs (single-pair, batch, MintPy) stored in `.insar_agent/jobs/{job_id}.json`
   - Independent of client model or personality
   - Queryable via `insar_get_job(job_id)`

4. **Error codes** (docs/agent-guide.md lines 32–42)
   - `key_not_allowed`: Guardrail to prevent skill from setting non-whitelisted fields
   - `runconfig_invalid`: Missing required path fields
   - `path_not_found`: Filesystem validation
   - `invalid_input`: Parameter range validation

---

## V. Why Not Only Skills? Three Structural Reasons

### 1. **Server-Side Allowlist Enforcement**

Skills are **client-side guidance**; they can be rationalized or ignored. An allowlist in the MCP server is **protocol-level truth**:

```python
# MCP server (src/insar_agent/mcp/server.py)
@mcp.tool()
def insar_set_runconfig_value(project_id, key, value):
    # If key not in ALLOWED_SET_FIELDS[workflow]:
    #   return error("key_not_allowed")
```

A skill cannot enforce this. If the client model decides to invent a parameter key, only the MCP server can reject it with certainty.

### 2. **Background Process Management**

Skills cannot:
- Launch conda subprocesses (`conda run`)
- Capture stderr/stdout across sessions
- Poll job status asynchronously
- Persist job state independently of the LLM conversation

MCP tools handle this:
```python
@mcp.tool()
def insar_run_workflow(project_id, dry_run=False):
    # Returns {job_id, log_path, pid, status}
    # User can tail -f log_path independently
    # Later: insar_get_job(job_id) queries status without re-running
```

### 3. **Protocol-Agnostic Execution**

The same Python library (`insar_agent.core`, `insar_agent.engines`) must work across:
- Claude Code with skills
- Codex or other OpenCode clients with MCP-only (no skills)
- CLI tools (`insar-agent describe`)
- Headless workflows

Skills are **Claude Code specific**. MCP is **protocol-agnostic**.

---

## VI. Documentation of the Contract

### CLAUDE.md (Lines 57–63): The Core Contract

```
For skill-aware clients, parameter advisory follows a plugin contract rather
than an MCP contract. The `param-advisor` skill must call the engine-appropriate
describe tool, then delegate recommendation generation to the project subagent
defined in `.claude/agents/param-advisor.md`. That subagent is
advisory-only, cites evidence, and may use models such as `gpt-5.3-codex`
depending on the host client. MCP tools do not enforce whether the subagent was
spawned; they only validate and apply the requested changes.
```

### docs/agent-guide.md (Lines 3–24): Hard Constraints

```
For skill-aware clients, parameter advice is a plugin contract: the main agent
must route into the unified advisor skill and that skill must
delegate advice generation to its project-level subagent.
...
MCP cannot verify this at protocol level; it only enforces the MCP contract (allowlists + validation).
```

### .claude/agents/param-advisor.md (Lines 26–44): Subagent Contract

```
Hard Constraints:
- Do not talk to the end user directly.
- Do not directly call `insar_set_processing_param`.
- The recommendation package must include `advisory_only: true`.
- The recommendation package must include `user_responsibility_notice`.
- Every parameter change must include `provenance`.
```

### docs/mcp-knowledge-base-mapping.md: Tool-to-Script Provenance

Each MCP tool is traced to its source:
- `insar_download_rslc` → wangshuai's `nisar-test-download_v2.py`
- `insar_prepare_stack` → wangshuai's `prepare_isce3_stack.py`
- `insar_export_geotiff` → tianxiaolong's `save_geotiff_nisar.py`

This ensures domain knowledge is **normalized into code**, not buried in prompts.

---

## VII. Skill Limits vs. MCP Guarantees

### What Skills CANNOT Do

| Constraint | Implication |
|-----------|-------------|
| No filesystem persistence | Cannot store job IDs across sessions |
| No subprocess control | Cannot launch background conda tasks |
| No protocol independence | Cannot serve non-Claude clients |
| No allowlist enforcement | Cannot guarantee parameter safety |
| No asynchronous polling | Cannot track long-running jobs independently |

### What MCP CANNOT Do

| Constraint | Implication |
|-----------|-------------|
| No workflow guidance | Tool order is up to client |
| No user interaction loops | Cannot pause for confirmation |
| No client branching | Same response for all clients (no `interaction_mode`) |
| No reasoning traces | Cannot show "why this parameter?" |
| No subagent delegation | Cannot spawn specialized advisory agents |

### The Division

```
Skills        → Workflow narrative, decision routing, confirmation loops, reasoning
MCP Tools     → Execution, validation, persistence, process management, protocol safety
Together      → Complete, reproducible, client-aware InSAR processing system
```

### Completed Evolution: Router Skill as a Real Agent (2026-04-27)

The `skills/insar-agent/SKILL.md` Markdown router has been upgraded to a
project-level agent defined at `.claude/agents/insar-agent.md`.

The agent owns session-level context (conda env choice, engine selection) and
routes to workflow skills via the Skill tool, with inline fallback steps when
the Skill tool is unavailable. It can be invoked directly via the Agent tool
without manual skill loading.

The parameter-advisor split is preserved: the router agent routes and bootstraps;
the dedicated `.claude/agents/param-advisor.md` subagent continues to own
advisory package generation and does not communicate with the user directly.

The skill file (`skills/insar-agent/SKILL.md`) is retained as a compatibility
and documentation layer for skill-aware clients that load it explicitly. It is
no longer the authoritative definition.

---

## VIII. File Paths: Evidence Checklist

### Skill Guidance Files
```
/home/august/insar-agent/skills/insar-agent/SKILL.md                    (73 lines) — Session entry point
/home/august/insar-agent/skills/param-advisor/SKILL.md                  (189 lines) — Parameter advisory orchestration
/home/august/insar-agent/skills/d-insar-isce3/SKILL.md                  (135 lines) — Path A workflow (NISAR)
/home/august/insar-agent/skills/d-insar-isce2/SKILL.md                  (~140 lines) — Path A workflow (Sentinel)
/home/august/insar-agent/skills/stack-insar-isce3/SKILL.md              (~150 lines) — Path B workflow (NISAR)
/home/august/insar-agent/skills/stack-insar-isce2/SKILL.md              (~150 lines) — Path B workflow (Sentinel)
/home/august/insar-agent/skills/data-prep/SKILL.md                      (~100 lines) — Data prep router
/home/august/insar-agent/skills/data-prep-nisar/SKILL.md                (~100 lines) — NISAR data download
/home/august/insar-agent/skills/data-prep-sentinel/SKILL.md             (~100 lines) — Sentinel data prep
/home/august/insar-agent/skills/env-setup/SKILL.md                      (152 lines) — Environment checks
/home/august/insar-agent/skills/mintpy/SKILL.md                         (164 lines) — Time-series analysis
```

### Contract Documentation Files
```
/home/august/insar-agent/CLAUDE.md                                       (80 lines) — Developer guidance; lines 57–63 define param-advisor contract
/home/august/insar-agent/docs/agent-guide.md                            (51 lines) — Hard constraints; lines 16–21 define skill/subagent contract
/home/august/insar-agent/.claude/agents/param-advisor.md                (129 lines) — Subagent contract; lines 26–44 hard constraints
/home/august/insar-agent/.claude/agents/references/param-advisor-isce3.md    (evidence patterns, heuristics)
/home/august/insar-agent/.claude/agents/references/param-advisor-isce2.md    (workflow-specific templates)
/home/august/insar-agent/docs/developer-documents/mcp-knowledge-base-mapping.md — Tool provenance
/home/august/insar-agent/docs/architecture.md                           (147 lines) — Layer boundaries; lines 43–45 define skill layer
```

### MCP Server Implementation
```
/home/august/insar-agent/src/insar_agent/mcp/server.py                 (2,956 lines) — FastMCP wiring; allowlist enforcement
/home/august/insar-agent/src/insar_agent/engines/isce3/defaults.py      (100 lines) — ALLOWED_SET_FIELDS registry
/home/august/insar-agent/src/insar_agent/engines/isce3/param_advisor.py (347 lines) — Engine-specific parameter heuristics
/home/august/insar-agent/src/insar_agent/core/project.py                (persistence & project lifecycle)
/home/august/insar-agent/src/insar_agent/core/job.py                    (job state model)
```

---

## IX. Summary: The Rationale

**Question:** Why not use only skills to save workflow scripts/constraints?

**Answer:** Because:

1. **Safety requires server-side enforcement.** Skills are client-side guidance; only MCP allowlists prevent malformed parameter changes.

2. **Asynchronous execution requires state persistence.** Background conda jobs must be tracked independently; skills cannot poll across sessions.

3. **Protocol independence requires abstraction.** The same library must serve Claude Code (skills+MCP), other clients (MCP-only), and headless workflows (CLI). Skills are Claude-only.

4. **Parameter advice requires reasoning separation.** To avoid context pollution, the main agent routes into a skill, which then spawns a dedicated subagent. The subagent's reasoning is ephemeral; only the parameter diff is committed.

5. **Domain knowledge normalization requires code.** Workflow scripts, allowlists, and heuristics live in Python modules, not skill prompts. This makes them testable, version-controllable, and reusable.

**The result:** A system where
- **Skills guide**, **MCP executes**
- **Main agent routes**, **subagent advises**
- **Clients enjoy workflow guidance**, **servers guarantee safety**

This design is documented in CLAUDE.md, agent-guide.md, and the param-advisor contract files.
