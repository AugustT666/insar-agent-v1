# MCP Tools Reference

This document is the primary implementation reference for all MCP tools, resources, and prompts exposed by `insar-mcp-server`.

For system context see [architecture.md](architecture.md). For data object definitions see [domain-model.md](domain-model.md).

---

## Resources

Resources are read-only documents the AI client fetches to understand constraints and workflow before calling any tool.

---

### `insar://workflow-guide`

Complete workflow guide — hard constraints, step-by-step instructions for both processing paths, allowed/forbidden field rules, and error reference.

**Returns:** Plain text. Contains:
- Hard constraints (no core parameter modification, official workflows only)
- Path A: mandatory step order for single-pair RSLC → GUNW processing
- Path B: batch stack + interferogram network preparation
- Required and optional settable fields for each workflow
- Error code reference

**Implementation:** `mcp/server.py::get_workflow_guide`

---

### `insar://allowed-fields/{workflow}`

Dynamic list of fields that may be set via `insar_set_runconfig_value` for the given workflow.

**URI parameter:** `workflow` — e.g. `insar`, `gslc`

**Returns:** Plain text with Required and Optional sections. Error message for unknown workflows.

**Implementation:** `mcp/server.py::get_allowed_fields`

---

## Prompts

Prompts are task templates. Invoke to get pre-filled step-by-step instructions.

---

### `process_insar_pair`

Guided template for processing a single RSLC pair (Path A workflow).

**Parameters:** `reference_rslc`, `secondary_rslc`, `dem`, `output_dir`, `conda_env`

**Returns:** 8-step instructions pre-filled with provided paths + constraint reminders.

---

### `process_insar_batch`

Guided template for batch stack + interferogram network preparation (Path B workflow).

**Parameters:** `data_dir`, `base_runconfig`, `dem`, `output_dir`, `network_mode`, `max_temporal_baseline_days`

**Returns:** 2-step instructions with terminal commands and output structure.

---

## next_step guidance

These tools include a `next_step` field in their return value:

| Tool | `next_step` content |
|------|---------------------|
| `insar_create_project` | Lists required fields + call `insar_set_runconfig_value` |
| `insar_validate_runconfig` (invalid) | Fix errors and validate again |
| `insar_validate_runconfig` (valid) | Call `insar_export_runconfig` |
| `insar_export_runconfig` | Call `insar_run_workflow` |
| `insar_run_workflow` | Poll `insar_get_job_status` with returned job_id |
| `insar_list_outputs` | Product format + batch path suggestion |
| `insar_prepare_stack` | Exact `bash run_parallel.sh` command + call `insar_prepare_network` |
| `insar_prepare_network` | Exact `bash run_parallel.sh` command + GUNW output path pattern |

---

## Group 1: Discovery

These tools are read-only and require no project context.

---

### `insar_list_engines`

Returns the InSAR engines available on this server.

**Parameters:** none

**Returns:**
```json
{
  "engines": [
    {
      "name": "isce3",
      "available": true,
      "description": "ISCE3 / NISAR science processor"
    }
  ]
}
```

**Errors:** none expected

**Implementation:** `engines/isce3/adapter.py` — `ISCE3Adapter.name`

---

### `insar_list_workflows`

Returns supported workflows for a given engine.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `engine` | string | yes | Engine name, e.g. `"isce3"` |

**Returns:**
```json
{
  "engine": "isce3",
  "workflows": [
    {
      "workflow": "insar",
      "supports_gpu": true,
      "description": "Generate interferometric products from reference/secondary RSLC inputs."
    },
    {
      "workflow": "gslc",
      "supports_gpu": true,
      "description": "Geocode SLC products from RSLC inputs."
    }
  ]
}
```

**Errors:**
- `engine_not_found` — engine name not recognized

**Implementation:** `engines/isce3/adapter.py` — `ISCE3Adapter.list_workflows()`

---

### `insar_get_project`

Returns project metadata, current runconfig summary, and latest job status.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | yes | UUID of the project |

**Returns:**
```json
{
  "project_id": "...",
  "name": "my-insar-run",
  "engine": "isce3",
  "workflow": "insar",
  "workspace_root": "/data/projects/my-insar-run",
  "created_at": "2026-03-24T10:00:00Z",
  "updated_at": "2026-03-24T10:05:00Z",
  "runconfig_keys": ["runconfig.groups.input_file_group.reference_rslc_file", "..."],
  "latest_job": null
}
```

**Errors:**
- `project_not_found`

**Implementation:** `core/project.py`

---

## Group 2: Config Management (M1)

These tools create and manage projects and their runconfigs.

---

### `insar_create_project`

Creates a new project, initializes the workspace, and loads the default runconfig template for the chosen workflow.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `engine` | string | yes | Engine name, e.g. `"isce3"` |
| `workflow` | string | yes | Workflow name, e.g. `"insar"` |
| `workspace_root` | string | yes | Absolute path where project files will be written |
| `name` | string | no | Human-readable project name (default: auto-generated) |

**Returns:**
```json
{
  "project_id": "a1b2c3d4-...",
  "name": "my-insar-run",
  "engine": "isce3",
  "workflow": "insar",
  "workspace_root": "/data/projects/my-insar-run",
  "created_at": "2026-03-24T10:00:00Z"
}
```

**Errors:**
- `engine_not_found`
- `workflow_not_found`
- `workspace_not_writable` — path does not exist or is not writable

**Implementation:** `core/project.py`, `engines/isce3/defaults.py`

---

### `insar_get_runconfig`

Returns the current runconfig for a project.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | yes | Project UUID |
| `format` | string | no | `"json"` (default) or `"yaml"` |

**Returns (json):**
```json
{
  "project_id": "...",
  "format": "json",
  "runconfig": {
    "runconfig": {
      "name": "insar",
      "groups": {
        "input_file_group": {
          "reference_rslc_file": null,
          "secondary_rslc_file": null
        },
        "worker": {
          "gpu_enabled": false
        }
      }
    }
  }
}
```

**Returns (yaml):** plain YAML string in `"runconfig_yaml"` field

**Errors:**
- `project_not_found`

**Implementation:** `core/project.py`, `core/config.py`

---

### `insar_set_runconfig_value`

Sets a value at a dotted key path within the runconfig.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | yes | Project UUID |
| `key` | string | yes | Dotted path, e.g. `"runconfig.groups.worker.gpu_enabled"` |
| `value` | any | yes | New value (string, number, boolean, list) |

**Returns:**
```json
{
  "project_id": "...",
  "key": "runconfig.groups.worker.gpu_enabled",
  "value": true,
  "updated_at": "2026-03-24T10:02:00Z"
}
```

**Errors:**
- `project_not_found`
- `key_invalid` — path does not exist in the runconfig schema

**Implementation:** `core/config.py` — `set_path()`

---

### `insar_unset_runconfig_value`

Removes a key from the runconfig, restoring it to the template default or null.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | yes | Project UUID |
| `key` | string | yes | Dotted path to remove |

**Returns:**
```json
{
  "project_id": "...",
  "key": "runconfig.groups.worker.gpu_enabled",
  "unset": true
}
```

**Errors:**
- `project_not_found`
- `key_not_found`

**Implementation:** `core/config.py` — `unset_path()`

---

### `insar_validate_runconfig`

Validates the current runconfig against the workflow schema and required-field rules.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | yes | Project UUID |

**Returns:**
```json
{
  "project_id": "...",
  "valid": false,
  "errors": [
    {
      "key": "runconfig.groups.input_file_group.reference_rslc_file",
      "message": "Required field is null",
      "suggestion": "Set to the absolute path of the reference RSLC HDF5 file"
    }
  ]
}
```

**Errors:**
- `project_not_found`

**Implementation:** `engines/isce3/validator.py`

---

### `insar_export_runconfig`

Renders the current runconfig as a YAML file in the specified output directory.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | yes | Project UUID |
| `output_dir` | string | no | Directory to write YAML into (default: `workspace_root/configs/`) |

**Returns:**
```json
{
  "project_id": "...",
  "yaml_path": "/data/projects/my-insar-run/configs/runconfig.yaml",
  "exported_at": "2026-03-24T10:03:00Z"
}
```

**Errors:**
- `project_not_found`
- `output_dir_not_writable`

**Implementation:** `core/project.py`, `core/config.py`

---

## Group 3: Execution (M2)

These tools launch and monitor workflow jobs.

---

### `insar_run_workflow`

Launches the workflow using the current exported runconfig. Creates a `Job` record.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | yes | Project UUID |
| `dry_run` | boolean | no | If true, print the command without executing (default: false) |

**Returns:**
```json
{
  "job_id": "j-001",
  "project_id": "...",
  "command": ["python", "-m", "nisar.workflows.insar", "/data/.../runconfig.yaml"],
  "status": "running",
  "submitted_at": "2026-03-24T10:10:00Z",
  "dry_run": false
}
```

**Errors:**
- `project_not_found`
- `runconfig_not_exported` — call `insar_export_runconfig` first
- `runconfig_invalid` — validation failed; call `insar_validate_runconfig` to see errors
- `workflow_not_whitelisted` — engine returned a workflow name not in `defaults.py`

**Implementation:** `engines/isce3/runner.py`, `core/jobs.py`

---

### `insar_get_job_status`

Returns the current state of a job.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `job_id` | string | yes | Job UUID |

**Returns:**
```json
{
  "job_id": "j-001",
  "project_id": "...",
  "status": "running",
  "exit_code": null,
  "submitted_at": "2026-03-24T10:10:00Z",
  "started_at": "2026-03-24T10:10:01Z",
  "finished_at": null,
  "log_path": "/data/projects/my-insar-run/logs/j-001.log"
}
```

**Status values:** `pending`, `running`, `done`, `failed`

**Errors:**
- `job_not_found`

**Implementation:** `core/jobs.py`

---

### `insar_get_job_logs`

Returns the job log content.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `job_id` | string | yes | Job UUID |
| `tail` | integer | no | Number of lines from the end (default: full log) |

**Returns:**
```json
{
  "job_id": "j-001",
  "log_path": "/data/.../j-001.log",
  "lines": 342,
  "content": "...[log text]..."
}
```

**Errors:**
- `job_not_found`
- `log_not_available` — job has not started yet

**Implementation:** `core/jobs.py`, `runtime/logging.py`

---

## Group 4: Outputs (M3)

These tools locate and summarize job outputs.

---

### `insar_list_outputs`

Lists output files produced by a completed job.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `job_id` | string | yes | Job UUID |

**Returns:**
```json
{
  "job_id": "j-001",
  "outputs": [
    {
      "path": "/data/.../output/interferogram.h5",
      "artifact_type": "hdf5",
      "description": "Interferogram product",
      "recommended_viewer": "h5py / QGIS"
    },
    {
      "path": "/data/.../output/unwrapped_phase.tif",
      "artifact_type": "geotiff",
      "description": "Unwrapped phase",
      "recommended_viewer": "QGIS / GDAL"
    }
  ]
}
```

**Errors:**
- `job_not_found`
- `job_not_done` — job is still running or failed

**Implementation:** `core/jobs.py`, `runtime/workspace.py`

---

### `insar_generate_preview`

Generates a lightweight preview (PNG thumbnail or statistics summary) from a job output file.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `job_id` | string | yes | Job UUID |
| `artifact_path` | string | no | Specific output file to preview (default: auto-select primary product) |

**Returns:**
```json
{
  "job_id": "j-001",
  "preview_path": "/data/.../output/preview.png",
  "stats": {
    "min": -3.14,
    "max": 3.14,
    "mean": 0.01,
    "nodata_fraction": 0.02
  }
}
```

**Errors:**
- `job_not_found`
- `job_not_done`
- `preview_not_supported` — artifact type does not support preview generation

**Implementation:** `engines/isce3/` (to be added), `runtime/workspace.py`

---

## Group 5: Stack / Network (M4)

These tools implement wangshuai's two-layer ISCE3 batch processing architecture.
They operate independently of the project registry — they take direct filesystem
paths and generate self-contained directory structures with runconfigs and runner scripts.

---

### `insar_prepare_stack`

Generate single-reference ISCE3 runconfigs from a directory of RSLC files (Layer 1).

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `data_dir` | string | yes | Directory containing NISAR RSLC `.h5` files |
| `base_runconfig` | string | yes | Path to template ISCE3 runconfig YAML |
| `dem` | string | yes | Path to the DEM file |
| `output_dir` | string | yes | Directory where runconfigs and scripts are written |
| `reference` | string | no | Reference scene: `'auto'` (earliest date), `YYYYMMDD`, or RSLC path |

**Returns:**
```json
{
  "reference_date": "20251122",
  "num_pairs": 1,
  "output_dir": "/path/to/stack",
  "runconfigs": ["/path/to/stack/runconfigs/20251122_20251204.yaml"],
  "run_all_sh": "/path/to/stack/run_all.sh",
  "run_parallel_sh": "/path/to/stack/run_parallel.sh",
  "manifest_csv": "/path/to/stack/stack_manifest.csv"
}
```

**Output structure:**
```
output_dir/
  runconfigs/          # Per-secondary runconfig YAMLs
  runs/<date1>_<date2>/
    products/          # ISCE3 output destination
    scratch/           # ISCE3 temp dir
    qa/                # QA outputs
    logs/
  run_all.sh           # Sequential runner
  run_parallel.sh      # Parallel runner (MAX_JOBS=8)
  stack_manifest.csv   # reference/secondary/runconfig/run_dir index
  reference_date.txt   # Selected reference date
```

**Errors:**
- `path_not_found` — data_dir, base_runconfig, or dem does not exist
- `invalid_input` — fewer than 2 RSLC files, duplicate dates, or negative baseline from reference selection

**Implementation:** `engines/isce3/stack.py::prepare_stack`

---

### `insar_prepare_network`

Generate ISCE3 runconfigs for an interferogram network from a directory of RSLC files (Layer 2).

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `data_dir` | string | yes | Directory containing NISAR RSLC `.h5` files |
| `base_runconfig` | string | yes | Path to template ISCE3 runconfig YAML |
| `dem` | string | yes | Path to the DEM file |
| `output_dir` | string | yes | Directory where runconfigs and scripts are written |
| `network_mode` | string | no | `'tbase'` (default) or `'conn'` |
| `max_temporal_baseline_days` | int | no | Max days between pair dates in tbase mode (default: 36) |
| `connection_span` | int | no | Forward neighbors per date in conn mode (default: 3) |
| `pair_list` | string | no | Path to file with `YYYYMMDD_YYYYMMDD` pairs, one per line |

**Network modes:**
- `tbase`: connect all pairs whose temporal baseline ≤ `max_temporal_baseline_days`
- `conn`: connect each date to the next `connection_span` dates
- Custom: when `pair_list` is provided, `network_mode` and span/threshold are ignored

**Returns:**
```json
{
  "num_pairs": 3,
  "output_dir": "/path/to/network",
  "runconfigs": ["..."],
  "run_all_sh": "/path/to/network/run_all.sh",
  "run_parallel_sh": "/path/to/network/run_parallel.sh",
  "pairs_selected_txt": "/path/to/network/pair_lists/pairs_selected.txt",
  "manifest_csv": "/path/to/network/stack_manifest.csv",
  "network_label": "pairs_tbase36d",
  "network_description": "Connect acquisitions with temporal baseline <= 36 days"
}
```

**Output structure:**
```
output_dir/
  runconfigs/          # Per-pair runconfig YAMLs
  runs/<date1>_<date2>/
    products/
    scratch/
    qa/
    logs/
  run_all.sh
  run_parallel.sh
  pair_lists/
    pairs_selected.txt       # YYYYMMDD_YYYYMMDD, one per line
    pairs_tbase36d.txt       # (or pairs_conn3.txt depending on mode)
    pairs_selected.csv       # date1/date2/rslc mapping
  stack_manifest.csv
```

**Errors:**
- `path_not_found` — data_dir, base_runconfig, dem, or pair_list does not exist
- `invalid_input` — invalid network_mode, span < 1, threshold < 1, bad pair format, or pair references unknown date

**Implementation:** `engines/isce3/network.py::prepare_network`
