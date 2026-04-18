# MCP Responsibilities vs. Other Layers: Detailed Analysis

## Executive Summary

`insar-agent` is **MCP-first** by design, with explicit separation between:
1. **MCP server** (protocol/wiring layer) — thin orchestration, delegates all domain logic
2. **Core modules** (protocol-agnostic domain) — persistence, job models, config mutations
3. **Engine modules** (engine-specific behavior) — workflow-specific logic
4. **Skills** (client-side guidance) — narrative, routing, parameter advisory

This report identifies **why MCP exists** instead of just skills, with concrete evidence from file paths, module responsibilities, and execution patterns.

---

## MCP Layer Responsibilities

### File: `/home/august/insar-agent/src/insar_agent/mcp/server.py` (2,956 lines)

**Single Responsibility**: FastMCP stdio server — registers tools, resources, prompts. Orchestrates domain logic but owns no business logic.

#### 1. **Protocol & Marshaling** (lines 59–126)
- FastMCP server initialization (`mcp = FastMCP(...)`)
- MCP resource handlers (`@mcp.resource`)
  - `insar://workflow-guide` → returns agent constraints from `docs/agent-guide.md`
  - `insar://allowed-fields/{workflow}` → lists settable fields per workflow
- MCP prompts (`@mcp.prompt`)
  - `process_insar_pair` — guided single-pair workflow template
  - `process_insar_batch` — guided batch workflow template

**Why MCP, not skills?**
- Resources and prompts are **protocol-level contracts** served by the MCP server. Skills cannot serve MCP resources.
- Agent clients (Claude Code, Codex, OpenCode) require a running MCP server to read `insar://workflow-guide` before making decisions.

#### 2. **Tool Registration & Delegation** (24 tools, lines 500–2956)
Each tool follows the pattern:
```python
@mcp.tool()
def insar_<operation>(...) -> dict:
    """Doc string."""
    # Validate inputs
    # Load state from core (Project, Job)
    # Delegate to engine module
    # Return result
```

**Evidence:**
- Group 1: Discovery (`insar_discover`, `insar_check_env`) — delegate to adapters
- Group 2: Project (`insar_create_project`, `insar_get_project`) — delegate to `core.Project`
- Group 3: Config (`insar_set_runconfig_value`, `insar_export_runconfig`) — delegate to `core.config` helpers
- Group 4: Execution (`insar_run_workflow`, `insar_get_job`) — subprocess + `core.Job` persistence
- Group 5: Stack/Batch (`insar_prepare_stack`, `insar_run_batch`) — delegate to `engines.isce3.stack/network`
- Group 6: Data (`insar_download_rslc`, `insar_describe_rslc`) — delegate to `engines.isce3.download`
- Group 7: MintPy (`insar_run_mintpy`) — delegate to `engines.isce3.mintpy`
- Group 8: Sentinel (`insar_prepare_sentinel_data`) — delegate to `engines.isce2.sentinel_prep`

**Why MCP, not skills?**
- MCP tools are **callable by AI agents via protocol**. Skills are static Markdown documents.
- Tools **persist state** (Job records, Project configs) in structured JSON. Skills have no state persistence layer.
- Tools **execute long-running processes** (conda, ISCE3 workflows) with async job tracking. Skills cannot directly manage external process lifecycle.

---

## Core Layer: Persistence & Data Models

### File: `/home/august/insar-agent/src/insar_agent/core/project.py` (152 lines)
### File: `/home/august/insar-agent/src/insar_agent/core/jobs.py` (86 lines)

**Single Responsibility**: Protocol-agnostic persistence for projects and jobs.

#### Key Data Models:

```python
@dataclass(slots=True)
class Project:
    project_id: str          # UUID
    engine: str              # "isce3" | "isce2"
    workflow: str            # "insar" | ...
    runconfig: dict          # Mutable ISCE3/ISCE2 config
    workspace_root: str      # File system root
    
    def save(self) -> None:
        # Persists to {workspace_root}/.insar_agent/project.json
        # Registers in ~/.local/share/insar_agent/registry.json
        
    @classmethod
    def load(cls, project_id: str) -> "Project":
        # Looks up project_id in registry, loads from disk
```

```python
@dataclass(slots=True)
class Job:
    project_id: str
    job_id: str              # UUID
    status: str              # "pending" | "running" | "done" | "failed"
    pid: int | None          # Process ID of spawned subprocess
    exit_code: int | None    # Workflow exit code
    log_path: str            # Persistent log file
    exit_code_path: str      # Sidecar exit code file
    
    def save(self, jobs_dir: Path) -> None:
        # Persists to {workspace_root}/.insar_agent/jobs/{job_id}.json
        
    @classmethod
    def load(cls, job_id: str, jobs_dir: Path) -> "Job":
        # Loads from disk
```

**Why this is core, not MCP:**
- These models define the **runtime contract** between CLI and MCP entry points.
- Persistence is **storage-layer logic**, not protocol-layer logic.
- MCP tools import and use these models; they don't define them.

#### Workspace Layout (enforced by core):
```
workspace_root/
  .insar_agent/
    project.json              ← Project persistence
    jobs/{job_id}.json        ← Job persistence
  configs/
    runconfig.yaml            ← Exported ISCE3 config
  logs/
    {job_id}.log              ← Live workflow output
    {job_id}.exitcode         ← Exit code sidecar
  outputs/
    {job_id}/                 ← Products (GUNW .h5, etc.)
```

**Why MCP doesn't own workspace layout:**
- Layout is shared by CLI, MCP, and future entry points.
- Layout defines where tools look for and write state.

---

## Engine Layer: Workflow-Specific Logic

### Files: `/home/august/insar-agent/src/insar_agent/engines/{isce3,isce2}/*.py` (30+ modules)

**Single Responsibility**: Engine-specific workflow behavior, validators, runners, data handling.

#### ISCE3 Modules:
- `runner.py` — builds `conda run python -m nisar.workflows.insar ...` commands
- `validator.py` — validates ISCE3 runconfig against required fields
- `defaults.py` — loads default ISCE3 runconfig template, defines whitelisted parameter keys
- `stack.py` / `network.py` — generates batch runconfigs, pair lists, runner scripts
- `rslc_metadata.py` — reads HDF5 NISAR RSLC metadata for parameter advisory
- `mintpy.py` — launches MintPy time-series workflows
- `geotiff.py` — exports GUNW HDF5 products to GeoTIFF + PNGs

#### ISCE2 Modules:
- Similar structure for Sentinel-1/topsStack workflows
- `sentinel_prep.py` — prepares grouped SAFE directories
- `param_advisor.py` — metadata-first evidence for ISCE2 parameter advice

**Why this is separate from MCP:**
- Engine modules are **reusable** across CLI, MCP, future REST API, etc.
- Engine modules **own domain validation** (e.g., `validate_runconfig` rejects invalid keys).
- MCP tools import engine modules; they don't duplicate the logic.

**Example: MCP delegates to engine:**
```python
# MCP tool (server.py line 1212)
@mcp.tool()
def insar_run_workflow(project_id: str) -> dict:
    # Validates using engine validator
    errors = validate_runconfig(project.runconfig, project.workflow)
    
    # Builds command using engine runner
    command = build_workflow_command(
        workflow=project.workflow,
        runconfig_path=runconfig_path,
        conda_env=project.conda_env,
    )
    
    # Spawns subprocess and tracks Job
    subprocess.Popen([...], stdout=log_file)
```

---

## Config Mutation: MCP vs. Skills vs. Core

### The Parameter Advisory Boundary

This is the **clearest evidence for why MCP exists**.

#### MCP Layer: Strict Enforcement
- `insar_set_runconfig_value(project_id, key, value)` — sets **path fields only** (whitelist)
  - Allowed keys: `runconfig.groups.input_file_group.reference_rslc_file`, etc.
  - Rejected keys: core processing parameters like `multilook_factor`
  - Error: `key_not_allowed`

- `insar_set_processing_param(project_id, key, value, justification)` — sets **processing parameters only** (whitelist)
  - Validates against processing parameter registry (`assets/processing_params_insar.yaml`)
  - Rejects vague justifications ("optimize", "improve quality")
  - Persists `project.updated_at`

#### Skills Layer: Narrative & Advisory
- `skills/param-advisor/SKILL.md` — guides user through evidence-gathering
  - Calls `insar_describe_rslc(...)` to summarize metadata
  - Recommends delegation to project-level subagent
  - Shows user the recommendation package before calling MCP tool

- `.claude/agents/param-advisor.md` — autonomous advisor (optional for non-skill clients)
  - Reads metadata from `insar_describe_rslc`
  - References `docs/archive/knowledge-base/` assets
  - Produces recommendation with justification

#### Core Layer: Config Helpers
- `core.config.set_path(data, dotted_path, value)` — generic dict mutation
- `core.config.get_path(data, dotted_path)` — generic dict lookup
- No validation — that's engine responsibility

**Why this split exists:**
1. **MCP owns validation** because it's the **runtime gatekeeper** — every mutation must be whitelist-controlled.
2. **Skills own reasoning** because they're **narrative-driven** — they explain the "why" and gather evidence.
3. **Core owns the generic helpers** because they're **protocol-agnostic**.

---

## Job Lifecycle: Why MCP Tracks It

### File: `/home/august/insar-agent/src/insar_agent/mcp/server.py` lines 1212–1330 (insar_run_workflow)

```python
def insar_run_workflow(project_id: str) -> dict:
    # Step 1: Load project from core
    project = Project.load(project_id)
    
    # Step 2: Validate runconfig (engine logic)
    errors = validate_runconfig(project.runconfig, project.workflow)
    
    # Step 3: Export config to YAML (MCP orchestration)
    yaml_path.write_text(yaml.dump(project.runconfig, ...))
    
    # Step 4: Build command (engine logic)
    command = build_workflow_command(...)
    
    # Step 5: Create Job record (core persistence)
    job = Job(project_id=project_id, ...)
    job.save(project.jobs_dir())
    
    # Step 6: Spawn subprocess (MCP responsibility)
    proc = subprocess.Popen([...], stdout=log_file)
    job.pid = proc.pid
    job.save(project.jobs_dir())  # Persist PID
    
    # Step 7: Return tool result
    return {
        "job_id": job.job_id,
        "status": "running",
        "pid": proc.pid,
        "poll": f"insar_get_job(job_id='{job.job_id}', project_id='{project_id}')"
    }
```

**Why MCP must track jobs:**
- **Subprocess spawning is MCP responsibility** — only the server can call `subprocess.Popen`.
- **Job polling requires structured state** — `insar_get_job` reads from `{jobs_dir}/{job_id}.json`.
- **Skills cannot track subprocess PID** — they're static documents without runtime state.
- **Exit-code recovery is MCP responsibility** — the server sets up exit-code sidecars (`{job_id}.exitcode`).

### Job Polling Pattern:
```python
@mcp.tool()
def insar_get_job(job_id: str, project_id: str, include_logs: bool = False) -> dict:
    # Load job from disk
    job = Job.load(job_id, project.jobs_dir())
    
    # If still running, return current status
    if job.status == "running":
        return {"job_id": job_id, "status": "running", "pid": job.pid}
    
    # If done, read exit code sidecar
    exit_code = _read_exit_code(job.exit_code_path)
    job.status = "done" if exit_code == 0 else "failed"
    
    # Return final status
    return {"job_id": job_id, "status": job.status, "exit_code": exit_code}
```

**Why this requires MCP:**
- Job state lives in **persistent files**, not in agent memory.
- Multiple agent clients can poll the same job.
- MCP provides a **protocol-agnostic interface** for any client to query job status.

---

## Batch Execution: Stack/Network Generation

### File: `/home/august/insar-agent/src/insar_agent/mcp/server.py` lines 1645–1782

**Stack generation (single-reference baseline):**
```python
@mcp.tool()
def insar_prepare_stack(data_dir, dem, output_dir, reference="auto") -> dict:
    # Delegate to engine
    result = prepare_stack(
        data_dir=data_dir,
        dem=dem,
        output_dir=output_dir,
        reference=reference,
    )
    # MCP adds handoff logic for interactive workflows
    result.update(_prepare_handoff(
        interaction_mode="interactive",
        review_artifacts=[manifest_csv, run_parallel_sh, reference_date_txt],
        next_recommended_action="insar_run_batch(...)"
    ))
    return result
```

**Why this is MCP:**
- `prepare_stack` returns file paths; MCP wraps them with **handoff metadata** for interactive workflows.
- Handoff state (`handoff_required=True`, `review_artifacts`) guides the agent through checkpoint-driven execution.
- Skills cannot manage this state; they're read-only documents.

---

## Constraints & Validation: MCP as the Gatekeeper

### Hard Constraints Enforced by MCP

From `docs/agent-guide.md` (served as `insar://workflow-guide`):

1. **Workflow whitelist** — only official ISCE3 NISAR workflows
   - Enforced by `insar_create_project` accepting only known workflows from adapter

2. **Path field whitelist** — only specified fields settable via `insar_set_runconfig_value`
   - Enforced by checking against `REQUIRED_PATH_FIELDS` and `ALLOWED_SET_FIELDS`
   - Resource `insar://allowed-fields/{workflow}` publishes the whitelist

3. **Processing parameter whitelist** — only specified params settable via `insar_set_processing_param`
   - Enforced by loading `load_processing_params(workflow)` registry
   - Validates type, range, and structure before persisting

4. **Justification validation** — vague justifications rejected
   - Processing params require a `justification` string
   - Rejects words like "optimize", "improve quality", "test"

5. **Execution command contract** — always `conda run python -m nisar.workflows...`
   - Enforced by `build_workflow_command` in engine layer
   - MCP just calls it; engine owns the contract

**Why MCP must enforce these:**
- **Protocol boundary**: Constraints are communicated as **resources** to agent clients.
- **Runtime enforcement**: The MCP server is the **only place** that can reject mutations at call time.
- **Auditability**: Rejected mutations are logged by the MCP server, traceable by the agent.

---

## Skills Layer: Narrative & Workflow Routing

### Files: `skills/insar-agent/SKILL.md` and subskilsl

Skills are **read-only guidance documents** that:
1. Explain workflow steps (entry point, data prep, parameter advisory, execution, results)
2. Route the agent to the correct MCP tool at each step
3. Call `insar_describe_rslc` (data-gathering tool) before entering parameter advisory
4. Delegate recommendation generation to `.claude/agents/param-advisor.md` (subagent)
5. Wait for user confirmation before calling `insar_set_processing_param` (MCP tool)

**Why skills exist alongside MCP:**
- **Narrative flow**: Skills tell the user "here's how to process NISAR data"; MCP tools execute the steps.
- **Reasoning separation**: Skills explain reasoning; MCP tools enforce constraints.
- **Reusability**: Same skills work with Claude Code, Codex, OpenCode; same MCP tools work with any agent client.

---

## Summary: Why MCP Exists

| Concern | Why MCP, Not Just Skills | Evidence |
|---------|-------------------------|----------|
| **Persistence** | Skills have no state. MCP creates/updates Project/Job JSON files. | `core/project.py`, `core/jobs.py` — dataclasses with `save()`/`load()` |
| **Subprocess Lifecycle** | Skills can't spawn processes. MCP calls `subprocess.Popen` and tracks PID. | `server.py:1303–1310` — Popen call, `job.pid` persistence |
| **Constraint Enforcement** | Skills are narrative; MCP is the runtime gatekeeper. | `server.py:950–1000` — whitelist validation in `insar_set_runconfig_value` |
| **Protocol Multiplexing** | Skills are Claude Code specific. MCP works with any agent client. | `docs/architecture.md` § System Layers — MCP is below skills |
| **Handoff State** | Skills guide workflow; MCP returns `handoff_required=True` for interactive checkpoints. | `server.py:370–383` — `_prepare_handoff(...)` |
| **Job Polling** | Skills can't poll long-running processes. MCP provides `insar_get_job(...)` polling interface. | `server.py:1334–1400` — reads exit-code sidecar, updates job.status |
| **Workspace Layout** | Skills can't enforce directory structure. MCP validates and creates `.insar_agent/` layout. | `core/project.py:95–108` — directory accessors ensure consistency |
| **Batch Execution** | Skills can't track multiple parallel jobs. MCP delegates to `BatchJob` model and `run_parallel.sh` orchestration. | `server.py:1785–1860` — `insar_run_batch` launches batch, tracks job |

---

## Files & Lines of Code

| Module | File | LOC | Responsibility |
|--------|------|-----|-----------------|
| **MCP** | `src/insar_agent/mcp/server.py` | 2,956 | Tool registration, orchestration, subprocess management |
| **Core** | `src/insar_agent/core/project.py` | 152 | Project persistence model |
| **Core** | `src/insar_agent/core/jobs.py` | 86 | Job persistence model |
| **Core** | `src/insar_agent/core/config.py` | 37 | Config manipulation helpers (generic) |
| **Engine (ISCE3)** | `src/insar_agent/engines/isce3/runner.py` | ~20 | Build ISCE3 workflow command |
| **Engine (ISCE3)** | `src/insar_agent/engines/isce3/validator.py` | ~80 | Validate ISCE3 runconfig |
| **Engine (ISCE3)** | `src/insar_agent/engines/isce3/stack.py` | ~200+ | Generate stack runconfigs & scripts |
| **Engine (ISCE3)** | `src/insar_agent/engines/isce3/defaults.py` | ~150+ | Load templates, whitelist definitions |

---

## Conclusion

`insar-agent` is **MCP-first** because:

1. **State persistence requires protocol infrastructure** — JSON files, registry lookups, workspace layout enforcement. Skills cannot own these.

2. **Process lifecycle management requires a runtime server** — subprocess spawning, PID tracking, exit-code polling. Only MCP can do this.

3. **Constraint enforcement requires a gatekeeper at tool invocation time** — whitelist validation, type checking, justification validation. Skills are read-only; MCP is a runtime enforcer.

4. **Multi-client support requires protocol abstraction** — same tools work with Claude Code, Codex, OpenCode, REST clients. Skills are client-specific guidance layers on top.

5. **Workflow checkpoints require structured state** — `handoff_required=True`, `review_artifacts=[]`, `next_recommended_action=...`. These must be returned by tools, not embedded in static Markdown.

The three-layer architecture is:
- **MCP** (protocol, orchestration, subprocess, persistence)
- **Skills** (narrative, routing, parameter advisory delegation)
- **Core + Engines** (domain logic, validators, runners)

Each layer is **reusable, testable, and replaceable** precisely because responsibilities are clear.
