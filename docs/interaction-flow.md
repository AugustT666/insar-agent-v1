# Interaction Flow: User × AI × MCP

This document is the primary reference for how the three actors in `insar-agent` interact. Use it as the starting point for discussing changes to the workflow, onboarding design, or tool behavior.

---

## Roles

| Actor | Who | Responsibility |
|-------|-----|---------------|
| **User** | Human, InSAR domain expert | Provides data paths and natural-language instructions |
| **AI Agent** | Claude / Codex / OpenCode etc. | Interprets intent, calls MCP tools, makes sequencing decisions |
| **MCP Server** | `insar-agent` process | Executes operations, enforces safety rules, returns structured results |

---

## Phase 1: AI Connects to MCP (automatic)

When an AI agent connects, the MCP handshake delivers:

- All tool names, parameter schemas, and docstrings
- The list of available Resources and Prompts

The AI should then immediately read the workflow guide resource:

```
AI reads: insar://workflow-guide
  → Hard constraints (which fields are LOCKED)
  → Path A step order (single pair)
  → Path B step order (batch)
  → Error codes and their meaning
  → Allowed vs. forbidden field categories
```

This resource is the authoritative constraint document. The AI holds it in context for the entire session.

---

## Phase 2: User Speaks (natural language)

The user gives an instruction in plain language. The AI identifies which processing path applies and proceeds accordingly.

---

### Path A — Single Pair Processing

**User says:** "Help me process ref.h5 and sec.h5 with DEM at /data/dem.tif, output to /work/insar, conda env is isce3"

**AI:**
1. Identifies Path A (single pair → GUNW)
2. Optionally invokes prompt `process_insar_pair(ref, sec, dem, output_dir, conda_env)` to get a pre-filled step template
3. Executes the following tool sequence:

```
Step 1: insar_create_project(engine="isce3", workflow="insar", workspace_root="/work/insar")
  ← { project_id: "abc123",
       next_step: "Call insar_set_runconfig_value for: reference_rslc_file, secondary_rslc_file, ..." }

Steps 2–7: insar_set_runconfig_value(pid, key, value)  [one call per required field]
  - runconfig.groups.input_file_group.reference_rslc_file        → "/data/ref.h5"
  - runconfig.groups.input_file_group.secondary_rslc_file        → "/data/sec.h5"
  - runconfig.groups.dynamic_ancillary_file_group.dem_file       → "/data/dem.tif"
  - runconfig.groups.product_path_group.product_path             → "/work/insar/products"
  - runconfig.groups.product_path_group.scratch_path             → "/work/insar/scratch"
  - runconfig.groups.product_path_group.sas_output_file          → "GUNW.h5"

Step 8: insar_validate_runconfig(pid)
  ← { valid: true, next_step: "Call insar_export_runconfig" }

Step 9: insar_export_runconfig(pid)
  ← { yaml_path: "/work/insar/runs/run_001/runconfig.yaml",
       next_step: "Call insar_run_workflow" }

Step 10: insar_run_workflow(pid)
  ← { job_id: "job_xyz", next_step: "Poll with insar_get_job_status" }

Step 11: insar_get_job_status(job_id)   [repeat until status = done or failed]

Step 12: insar_get_job_logs(job_id)     [only if failed]

Step 13: insar_list_outputs(pid)
  ← { outputs: [...], next_step: "Inspect products with recommended viewers" }
```

---

### Path B — Batch Processing (stack + network)

**User says:** "I have RSLC files in /data/rslc, DEM at /data/dem.wgs84, prepare batch processing with conn mode, 3 neighbors"

**AI:**
1. Identifies Path B (multi-scene batch → stack → network → GUNW)
2. Optionally invokes prompt `process_insar_batch(data_dir, dem, output_dir, network_mode, ...)`
3. Executes:

```
Step 1: insar_prepare_stack(data_dir="/data/rslc", base_runconfig=..., dem=..., output_dir="/out/stack")
  ← { num_pairs: 15,
       run_parallel_sh: "/out/stack/run_parallel.sh",
       next_step: "Run: bash run_parallel.sh /out/stack 4  Then call insar_prepare_network" }

  → AI tells user: "Please run: bash run_parallel.sh /out/stack 4"

User: "Done."

Step 2: insar_prepare_network(data_dir=..., base_runconfig=..., dem=...,
                               output_dir="/out/network", network_mode="conn", max_conn=3)
  ← { num_pairs: 42,
       network_description: "conn3",
       run_parallel_sh: "/out/network/run_parallel.sh",
       next_step: "Run: bash run_parallel.sh /out/network 4  GUNW products in runs/*/products/*.h5" }

  → AI tells user: "Please run: bash run_parallel.sh /out/network 4"
```

---

## Safety Boundary: What MCP Refuses

If the AI attempts to modify a core processing parameter:

```
AI calls: insar_set_runconfig_value(pid,
            "runconfig.groups.processing.interferogram.filter.filter_strength", 0.8)

MCP returns: {
  "error": "key_not_allowed: runconfig.groups.processing.interferogram.filter.filter_strength
            is a core processing parameter and cannot be modified via MCP"
}
```

The AI must not retry. It should tell the user the field is protected.

**Protected categories (LOCKED — never settable via MCP):**
- `processing.*` — multilook factors, filtering, unwrapping parameters
- `processing.crossmul.*` — cross-multiplication settings
- `processing.interferogram.*` — interferogram formation
- Any field not in `ALLOWED_SET_FIELDS` in `engines/isce3/defaults.py`

**Settable categories (ALLOWED):**
- `input_file_group.*` — RSLC input paths
- `dynamic_ancillary_file_group.*` — DEM and orbit paths
- `product_path_group.*` — output/scratch paths, product filename
- `worker.gpu_enabled` — GPU flag
- `worker.num_process_frames` — parallelism

---

## Constraint Propagation Chain

How domain knowledge flows from expert to enforcement:

```
SKILL.md  (tianxiaolong — domain expert writes constraints)
  ↓
engines/isce3/defaults.py  (ALLOWED_SET_FIELDS, REQUIRED_PATH_FIELDS — compiled into code)
  ↓
mcp/server.py  _WORKFLOW_GUIDE constant  (encoded as readable text)
  ↓
insar://workflow-guide  (MCP Resource — delivered to AI at session start)
  ↓
AI context  (AI learns rules before any tool call)
  ↓
next_step fields  (inline guidance at each tool return)
  ↓
MCP tool enforcement  (key_not_allowed error — last line of defense)
```

Three layers: AI **learns** constraints (Resource) → **follows** guidance (next_step) → **blocked** if wrong (error).

---

## Tool Returns with next_step

These tools always include a `next_step` string in their return value:

| Tool | next_step content |
|------|-------------------|
| `insar_create_project` | Which fields to set with `insar_set_runconfig_value` |
| `insar_validate_runconfig` (invalid) | Which missing fields to set, then re-validate |
| `insar_validate_runconfig` (valid) | Call `insar_export_runconfig` |
| `insar_export_runconfig` | Call `insar_run_workflow` |
| `insar_run_workflow` | Poll with `insar_get_job_status` |
| `insar_list_outputs` | Recommended viewer per output type |
| `insar_prepare_stack` | Run `run_parallel.sh`, then call `insar_prepare_network` |
| `insar_prepare_network` | Run `run_parallel.sh`, find GUNW products in `runs/*/products/*.h5` |

---

## MCP Onboarding Mechanisms Summary

| Mechanism | Type | When active | Purpose |
|-----------|------|-------------|---------|
| `insar://workflow-guide` | Resource | Session start | Full constraint spec and step order |
| `insar://allowed-fields/{workflow}` | Resource | On demand | Settable fields per workflow |
| `process_insar_pair(...)` | Prompt | On demand | Pre-filled single-pair step template |
| `process_insar_batch(...)` | Prompt | On demand | Pre-filled batch step template |
| `next_step` field | Tool return | Every relevant tool call | Inline "what to do next" |
| `key_not_allowed` error | Tool return | On forbidden field | Hard enforcement |
