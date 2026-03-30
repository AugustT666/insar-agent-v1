# Architecture

## Intent

`insar-agent` separates three concerns:

- shared domain logic for projects, configs, and jobs
- MCP-facing tool exposure for agent clients
- engine-specific behavior for `ISCE3` and future engines

The long-term asset is not any client-specific wrapper. It is the accumulated operational knowledge for running InSAR software safely and repeatably.

---

## System Layers

```text
┌─────────────────────────────────────────┐
│  Agent Client                           │
│  Codex / Claude Code / OpenCode / etc.  │
└──────────────────┬──────────────────────┘
                   │  MCP tools / resources / prompts
                   ▼
┌─────────────────────────────────────────┐
│  insar_agent.mcp                        │
│  - MCP server (stdio transport)         │
│  - tool handler routing                 │
│  - prompt and resource registry         │
└──────────────────┬──────────────────────┘
                   │  domain calls
                   ▼
┌─────────────────────────────────────────┐
│  insar_agent.core                       │
│  - Project (persistence, runconfig)     │
│  - Job (state machine, lifecycle)       │
│  - config (dotted-key read/write)       │
│  - session (undo/redo history)          │
└──────────────────┬──────────────────────┘
                   │  engine-specific calls
                   ▼
┌─────────────────────────────────────────┐
│  insar_agent.engines.isce3              │
│  - ISCE3Adapter (list_workflows)        │
│  - runner (build_workflow_command)      │
│  - validator (runconfig schema checks)  │
│  - defaults (SUPPORTED_WORKFLOWS)       │
└──────────────────┬──────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────┐
│  insar_agent.runtime + local env        │
│  - workspace layout                     │
│  - conda env detection                  │
│  - structured logging                   │
│  - rendered YAML / HDF5 outputs         │
└─────────────────────────────────────────┘
```

---

## Layer Responsibilities

### `insar_agent.mcp`

- Owns the MCP server entry point (`insar-mcp-server`)
- Registers tools, resources, and prompts via FastMCP decorators
- Delegates **all** domain logic to `core` and `engines` — no business logic here
- No direct subprocess calls or file I/O
- Key files: `src/insar_agent/mcp/server.py`

**Registered resources (AI onboarding):**
- `insar://workflow-guide` — full constraint spec and step-by-step guide for both processing paths
- `insar://allowed-fields/{workflow}` — dynamic list of settable fields per workflow

**Registered prompts (task templates):**
- `process_insar_pair` — guided single-pair workflow with path interpolation
- `process_insar_batch` — guided batch stack + network workflow

**`poll` guidance:** `insar_run_workflow` and `insar_run_mintpy` return a `poll` field containing the exact `insar_get_job(...)` call needed for status polling.

**Plugin contract vs MCP contract:** For skill-aware clients, parameter advice is a plugin contract and must be delegated to a dedicated subagent. MCP tools do not and cannot verify whether a subagent was actually used; the MCP contract is limited to allowlists, validation, and factual execution.

### `insar_agent.core`

- Protocol-agnostic domain logic; usable from both CLI and MCP
- `project.py` — `Project` dataclass, JSON persistence, runconfig dict storage
- `config.py` — `get_path` / `set_path` / `unset_path` for dotted-key access
- `jobs.py` — `Job` state machine (`pending → running → done/failed`)
- `session.py` — undo/redo history for runconfig edits
- Key files: `src/insar_agent/core/`

### `insar_agent.engines`

- All software-specific behavior lives here
- `base.py` defines `EngineAdapter` (Protocol) and `WorkflowInfo`
- `isce3/adapter.py` — `ISCE3Adapter` implementing the Protocol
- `isce3/runner.py` — builds the `python -m nisar.workflows.<workflow>` command
- `isce3/validator.py` — runconfig schema and required-field checks
- `isce3/defaults.py` — supported workflows (`gslc`, `insar`) and their metadata
- `isce3/stack.py` — `prepare_stack()`: single-reference stack batch generation (from wangshuai)
- `isce3/network.py` — `prepare_network()`: interferogram network tbase/conn (from wangshuai)
- `isce3/bbox.py` — `union_bbox()`: extract union bounding box from RSLC HDF5 files
- `isce3/geotiff.py` — `export_geotiff()`: convert GUNW HDF5 to GeoTIFF + PNG browse images
- `isce3/mintpy.py` — `run_mintpy()` + `get_mintpy_status()`: async MintPy launcher with PID-based polling
- `isce3/baseline.py` — `plot_baseline_network()`: spatiotemporal baseline plot + CSV
- Key files: `src/insar_agent/engines/`

### `insar_agent.runtime`

- `env.py` — conda environment detection and Python interpreter selection
- `workspace.py` — project workspace layout (`runs/`, `logs/`, `outputs/`)
- `logging.py` — structured log helpers
- Key files: `src/insar_agent/runtime/`

### `skills/`

- Host-specific teaching material for agent clients
- Not the source of truth for execution logic
- Optional; core functionality works without it

---

## Domain Model

See [domain-model.md](domain-model.md) for full field definitions. Summary:

| Object | Purpose | Persisted as |
|---|---|---|
| `Project` | One processing project with a runconfig | JSON file in workspace |
| `Job` | One workflow execution run | JSON file in project dir |
| `WorkflowTemplate` | Default config and metadata for a workflow | In-memory (from `defaults.py`) |
| `Artifact` | Output file produced by a job | File path recorded in Job |

---

## MCP Surface

See [mcp-tools.md](mcp-tools.md) for full input/output specs.

### Resources

| URI | Description |
|-----|-------------|
| `insar://workflow-guide` | Hard constraints and step-by-step guide for both processing paths |
| `insar://allowed-fields/{workflow}` | Required and optional settable fields for a given workflow |

### Prompts

| Name | Parameters | Description |
|------|-----------|-------------|
| `process_insar_pair` | ref, sec, dem, output_dir, conda_env | Guided single-pair RSLC → GUNW workflow |
| `process_insar_batch` | data_dir, dem, output_dir, network_mode, ... | Guided batch stack + interferogram network |

### Tools (15 total)

**Discovery**
- `insar_discover` — list engines (no args) or workflows for a given engine
- `insar_get_project` — project metadata and latest job status

**Config management** (M1)
- `insar_create_project` — create project, bind engine/workflow/workspace, and return one-time tuning guidance
- `insar_get_runconfig` — read current runconfig (JSON or YAML view)
- `insar_set_runconfig_value` — set or remove dotted-key path (value=None removes)
- `insar_set_processing_param` — set whitelist-controlled algorithm parameter with justification

**Execution** (M2)
- `insar_run_workflow` — validate + export + launch (all-in-one); supports `dry_run`
- `insar_get_job` — job state ± logs for ISCE3 and MintPy jobs (unified)
- `insar_list_outputs` — output files with type and recommended viewer

**Stack / Network** (M4)
- `insar_prepare_stack` — batch single-reference runconfig generation
- `insar_prepare_network` — batch interferogram network runconfig generation

**MintPy** (M6)
- `insar_run_mintpy` — async MintPy time-series processing
- `insar_plot_baseline` — baseline network plot + CSV

**Utilities** (M5)
- `insar_extract_bbox` — extract union bounding box from RSLC files (for DEM download)
- `insar_export_geotiff` — convert GUNW HDF5 to GeoTIFF + PNG browse images

---

## Typical Agent Interaction Flow

### Path A — Single pair

```
0.  Read resource insar://workflow-guide           (onboarding — learn constraints first)
    OR invoke prompt process_insar_pair(...)       (get pre-filled step-by-step instructions)
1.  insar_create_project(...)                      → project_id
2.  insar_set_runconfig_value(...)  ×6             (only allowed path fields; value=None to remove)
2.5 param-advisor-isce3 (optional)                 → main agent builds evidence profile, subagent returns parameter advice, then adjust whitelist-controlled processing params
3.  insar_run_workflow(...)                        → job_id + poll hint (auto validates + exports)
4.  insar_get_job(job_id, project_id)  [poll]      (include_logs=True if failed)
5.  insar_list_outputs(job_id)                     → artifact list
```

### Path B — Batch stack / network

```
0.  Read resource insar://workflow-guide
    OR invoke prompt process_insar_batch(...)
0.5 param-advisor-isce3 (optional)                 → tune temporary insar project via subagent-generated advice, export base runconfig
1.  insar_prepare_stack(data_dir, runconfig, dem, output_dir)
    → USER runs: bash run_parallel.sh <output_dir> <N>
2.  insar_prepare_network(data_dir, runconfig, dem, output_dir, network_mode)
    → USER runs: bash run_parallel.sh <output_dir> <N>
    → GUNW products in runs/*/products/*.h5
```

---

## MCP Layer and Script Interaction

### Overview

The MCP layer and processing scripts are connected through three interaction modes. The MCP server itself never calls scripts directly — it delegates to `engines/isce3/` which builds commands or generates scripts.

```
AI Client
  │  MCP tool call (JSON args over stdio)
  ▼
mcp/server.py          — routes call, no business logic
  │  Python function calls
  ▼
core/ + engines/isce3/ — builds commands, validates, manages state
  │  subprocess or script generation
  ▼
ISCE3 / MintPy / GDAL  — actual InSAR computation
```

### Mode A — Direct Subprocess (Path A, single pair)

Used by `insar_run_workflow`. The engine layer constructs a command and `server.py` launches it directly via `subprocess.Popen`.

**Call chain:**
```
insar_run_workflow(project_id)
  → load Project from registry
  → runner.build_workflow_command(workflow, runconfig_path, conda_env)
      → ["conda", "run", "-n", <env>, "--no-capture-output",
         "python", "-m", "nisar.workflows.insar", "/path/to/runconfig.yaml"]
  → subprocess.Popen(command, stdout=log_file, cwd=workspace_root)
  → Job saved (job_id, pid, log_path, status=running)
  → returns job_id for polling
```

**Status polling:**
```
insar_get_job(job_id, project_id)
  → load Job from jobs/<job_id>.json
  → os.kill(pid, 0)         — check if process alive
  → /proc/<pid>/status      — detect zombie
  → on exit: read log tail, scan for "error:"/"traceback" → done or failed
  → update job.json
```

**Parameter flow (complete Path A sequence):**
```
1. insar_create_project(engine, workflow, workspace_root, conda_env)
      → load default runconfig YAML from assets/insar.yaml
      → Project saved: project.runconfig = dict (in memory + JSON)

2. insar_set_runconfig_value(project_id, key, value)   × 6
      → ALLOWED_SET_FIELDS check (path fields + worker flags only)
      → config.set_path(project.runconfig, "runconfig.groups.input_file_group.reference_rslc_file", value)
      → project.json updated
      (value=None → unset_path, restore to template default)

3. insar_run_workflow(project_id)
      [internal] validator.validate_runconfig() → errors returned if invalid
      [internal] yaml.dump(project.runconfig) → <workspace>/configs/runconfig.yaml
      [internal] subprocess.Popen(command, stdout=log_file, cwd=workspace_root)
      → Job saved (job_id, pid, log_path, status=running)
      → returns {job_id, poll: "insar_get_job(job_id='...', project_id='...')"}

4. insar_get_job(job_id, project_id)   [poll until done/failed]
   insar_get_job(job_id, project_id, include_logs=True)   [if failed — get log inline]

5. insar_list_outputs(job_id)
      → scan <workspace>/outputs/<job_id>/
      → map extensions (.h5, .tif, .png) to artifact types
```

### Mode B — Script Generation (Path B, batch processing)

Used by `insar_prepare_stack` and `insar_prepare_network`. The engine layer generates runconfig YAMLs and shell scripts on disk; the user runs them manually. No subprocess is launched by MCP.

**Call chain (stack):**
```
insar_prepare_stack(data_dir, base_runconfig, dem, output_dir, reference='auto')
  → stack.discover_scenes(data_dir)
      → scan for RSLC .h5 files, extract dates from _YYYYMMDDTHHMMSS_ in filename
  → select reference (earliest if reference='auto')
  → for each secondary scene:
      → read base_runconfig YAML
      → set reference_rslc_file, secondary_rslc_file, dem_file, product_path
      → write <output_dir>/runconfigs/<date>.yaml
  → write <output_dir>/run_all.sh         (sequential)
  → write <output_dir>/run_parallel.sh    (GNU parallel)
  → write <output_dir>/stack_manifest.csv
  → return: {run_command, runconfig_dir, manifest_path, n_pairs}
```

**User executes (outside MCP):**
```bash
bash run_parallel.sh <output_dir> <N_jobs>
# → N parallel: conda run -n isce3 python -m nisar.workflows.insar <date>.yaml
# → GUNW products: <output_dir>/runs/<date1>_<date2>/products/*.h5
```

**Network mode** (`insar_prepare_network`) follows the same pattern but applies tbase or conn pairing logic before generating runconfigs.

### Mode C — Async Shell Script (MintPy)

Used by `insar_run_mintpy`. The engine launches a shell wrapper script that orchestrates multiple Python tools in sequence.

**Call chain:**
```
insar_run_mintpy(mintpy_work_dir, gunw_glob, mintpy_config, dem_path, conda_env)
  → mintpy.run_mintpy(...)
      → validate paths
      → command = ["conda", "run", "-n", <env>, "bash",
                   "engines/isce3/assets/run_mintpy_nisar_stack.sh",
                   mintpy_work_dir, gunw_glob, mintpy_config, dem_path]
      → subprocess.Popen(command, stdout=log_file)   [async, returns immediately]
      → save job JSON to <mintpy_work_dir>/.jobs/<job_id>.json
  → return job_id
```

**Shell script sequence (`run_mintpy_nisar_stack.sh`):**
```
1. prep_nisar_current_gunw.py          → prepare GUNW stack as MintPy input
2. apply_common_ifgram_mask.py         → mask low-coherence pixels
3. smallbaselineApp.py --start modify_network --end reference_point
4. apply_common_ifgram_mask.py         → re-apply mask
5. smallbaselineApp.py --start correct_unwrap_error
```

**Status polling (Mode C):**
```
insar_get_job(job_id, work_dir=mintpy_work_dir)
  → load job from <mintpy_work_dir>/.jobs/<job_id>.json
  → os.kill(pid, 0)           — liveness check
  → on exit: inspect log tail for completion markers
```

### Script Whitelist and Safety

Scripts that can be executed are constrained at multiple points:

| Constraint | Where enforced |
|------------|---------------|
| Only `nisar.workflows.*` modules allowed | `runner.py` — command builder |
| Only whitelisted runconfig keys settable | `defaults.py` — `ALLOWED_SET_FIELDS` |
| Output paths must be inside workspace_root | validated before export |
| No shell string interpolation | all commands built as `list[str]` |
| `dry_run=True` available | prints command without executing |

---

## Safety Policy

- MCP tools may only invoke whitelisted workflow modules (declared in `defaults.py`)
- All output paths must be within the project's `workspace_root`
- Arbitrary shell execution is not permitted — commands are constructed by `runner.py` only
- Read-only tools (`list_*`, `get_*`) vs. state-mutating tools (`create_*`, `set_*`, `run_*`) are clearly separated in the tool registry
- `insar_run_workflow` supports a `dry_run` mode that validates and prints the command without executing

---

## Knowledge Ingestion Model

Domain knowledge (ISCE3 runconfigs, scripts, workflow notes) enters the project like this:

```
User provides ISCE3 operating material
  → stored as reference in docs/workflows/
  → normalized into engines/isce3/ (defaults, validator, runner)
  → wired as MCP tools in mcp/server.py via the core layer
  → tested in tests/unit/ and tests/integration/
```

Never invent workflow parameters or undocumented operational steps when source material is incomplete.

---

## Milestone Status

| Milestone | Status | Scope |
|---|---|---|
| M0: Server skeleton | **Done** | Package layout, scaffold server, smoke tests |
| M1: Config management | **Done** | FastMCP server, `create_project`, `get/set runconfig`, project registry, conda env support |
| M2: Job execution | **Done** | `run_workflow` (async Popen), `get_job` (status + logs) |
| M3: Output handling | **Done** | `list_outputs` with artifact type inference |
| M4: Stack / network | **Done** | `prepare_stack`, `prepare_network` (wangshuai two-layer architecture) |
| M4b: Agent onboarding | **Done** | Resources, Prompts, skill-first architecture |
| M5: Utilities | **Done** | `insar_extract_bbox`, `insar_export_geotiff`, `insar_set_processing_param` |
| M5b: Agent behavior test | **Done** | opencode + gpt-5.3-codex MCP client: 9/9 checklist items passed; 22MB GUNW product generated |
| M6: MintPy integration | **Done** | `insar_run_mintpy`, `insar_plot_baseline`; `mintpy-isce3` skill |
| Refinement | **Done** | MCP API consolidated 21→15 tools; `insar_discover`, `insar_get_job` (unified), auto validate+export in `run_workflow`; 160 unit tests |
| M7 | **Planned** | Remote / automation (TBD) |

### Implementation notes (2026-03-29)

- **MCP SDK**: `mcp>=1.0` (FastMCP) installed; Resources and Prompts use `@mcp.resource` / `@mcp.prompt` decorators
- **Runconfig templates**: copied from `/home/august/isce3/share/nisar/defaults/` into `engines/isce3/assets/`
- **Project registry**: `~/.local/share/insar_agent/registry.json` maps `project_id → workspace_root`; overridable via `$XDG_DATA_HOME`
- **Safety**: `ALLOWED_SET_FIELDS` in `defaults.py` blocks core processing parameters; only path fields and worker flags are settable via MCP
- **Conda env**: stored per-project, injected into `build_workflow_command()` as `conda run -n <env>`
- **Test data**: NISAR RSLC files on NAS at `/home/august/NAS/NISAR_wangshuai_data/`; integration tests reference directly; `insar_nisar.yaml` fixture in `tests/fixtures/`
- **Knowledge bases**: `knowledge-base/tianxiaolong/` — primary (SKILL.md constraints, runconfig template); `knowledge-base/wangshuai/` — supplementary (stack/network scripts, MintPy integration)
- **Developer documents**: `docs/developer-documents/` — project management docs (dev-plan, workflow showcase); not referenced by CLAUDE.md
- **Agent behavior test (M5b)**: Full end-to-end test via opencode MCP client; verified tool call sequences, GPU flag override, GUNW output validation

---

## Non-Goals (V1)

- No GUI, map viewer, or interactive parameter forms
- No remote cluster scheduling (Kubernetes, Slurm)
- No multi-engine support in V1 (ISCE3 only)
- No `cli-anything` runtime dependency
- No coverage of all NISAR workflows in V1 (start with `gslc` and `insar`)
