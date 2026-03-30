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

## Tool Summary (16 tools)

| Group | Tool | Purpose |
|---|---|---|
| Discovery | `insar_discover` | List engines or workflows for an engine |
| Discovery | `insar_get_project` | Project metadata + latest job status |
| Config | `insar_create_project` | Create a new project |
| Config | `insar_get_runconfig` | Read current runconfig |
| Config | `insar_set_runconfig_value` | Set or remove a runconfig field (value=None removes) |
| Config | `insar_set_processing_param` | Set whitelist-controlled algorithm parameter |
| Execution | `insar_run_workflow` | Validate + export + launch (all in one) |
| Execution | `insar_get_job` | Job status ± logs (ISCE3, MintPy, and batch) |
| Execution | `insar_list_outputs` | List output files from a completed job |
| Stack/Network | `insar_prepare_stack` | Prepare single-reference RSLC stack |
| Stack/Network | `insar_prepare_network` | Generate interferogram network |
| Stack/Network | `insar_run_batch` | Execute a prepared stack or network batch |
| MintPy | `insar_run_mintpy` | Launch MintPy time-series processing |
| MintPy | `insar_plot_baseline` | Render baseline network plot |
| Utilities | `insar_extract_bbox` | Union bounding box from RSLC list |
| Utilities | `insar_export_geotiff` | HDF5 GUNW → GeoTIFF + PNG |

---

## Group 1: Discovery

These tools are read-only and require no project context.

---

### `insar_discover`

Discover available engines (no args) or workflows for a specific engine.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `engine` | string | no | Leave empty to list engines; provide `"isce3"` etc. to list workflows |

**Returns (engine list, engine=""):**
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

**Returns (workflow list, engine="isce3"):**
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

**Implementation:** `mcp/server.py::insar_discover`

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
  "created_at": "2026-03-24T10:00:00Z",
  "required_fields": [
    "runconfig.groups.input_file_group.reference_rslc_file"
  ],
  "guidance": "Set required path fields with insar_set_runconfig_value. If you need to tune multilook, filtering, unwrapping, or atmospheric corrections, invoke param-advisor-isce3 before validate/export/run and apply changes via insar_set_processing_param."
}
```

For skill-aware clients, this guidance is a plugin contract: parameter advice must be generated by the `param-advisor-isce3` project-level subagent before the main agent applies any whitelist-controlled changes.

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

Sets or removes a value at a dotted key path within the runconfig.
Pass `value=null` to remove the key (restore to template default).

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | yes | Project UUID |
| `key` | string | yes | Dotted path, e.g. `"runconfig.groups.worker.gpu_enabled"` |
| `value` | any\|null | yes | New value (string, number, boolean, list) or null to remove the key |

**Returns (set):**
```json
{
  "project_id": "...",
  "key": "runconfig.groups.worker.gpu_enabled",
  "value": true,
  "updated_at": "2026-03-24T10:02:00Z"
}
```

**Returns (unset, value=null):**
```json
{
  "project_id": "...",
  "key": "runconfig.groups.worker.gpu_enabled",
  "unset": true
}
```

**Errors:**
- `project_not_found`
- `key_not_allowed` — key is not in the allowed set for this workflow
- `key_invalid` — path does not exist in the runconfig schema
- `key_not_found` — key not present when removing

**Implementation:** `core/config.py` — `set_path()` / `unset_path()`

---

### `insar_set_processing_param`

Sets a whitelist-controlled processing parameter. This tool is intended to be called from `param-advisor-isce3`, not as a free-form replacement for direct YAML editing.

For skill-aware clients, `param-advisor-isce3` must obtain the recommendation from the project-level subagent defined in `.claude/agents/param-advisor-isce3.md` before calling this tool. MCP does not verify that delegation; it only validates the parameter update itself.

**Behavior notes:**
- Enforces type validation, range validation, enum validation, and simple structural validation for list-shaped values.
- Rejects empty or vague `justification` strings.
- Returns `validated_against` so the caller can explain which registry entry accepted the change.

**Typical use:**
- `crossmul` multilook factors
- `phase_unwrap` settings
- `filter_interferogram` filter mode and limited boxcar window sizing
- atmospheric correction toggles

**Errors:**
- `project_not_found`
- `key_not_allowed`
- `invalid_type`
- `value_not_allowed`
- `value_out_of_range`
- `invalid_input`
- `justification_required`

---

### _Removed: `insar_validate_runconfig` and `insar_export_runconfig`_

These tools no longer exist as MCP tools. `insar_run_workflow` now automatically validates
and exports the runconfig before launching. If validation fails it returns `runconfig_invalid`
with the full errors list.

---

### _Removed: `insar_unset_runconfig_value`_

Use `insar_set_runconfig_value(project_id, key, value=None)` instead.

---


---

## Group 3: Execution (M2)

These tools launch and monitor workflow jobs.

---

### `insar_run_workflow`

Validates the runconfig, exports it to YAML, and launches the workflow. Creates a `Job` record.
No separate validate or export step is needed.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | yes | Project UUID |
| `dry_run` | boolean | no | If true, validate + export but do not launch (default: false) |

**Returns:**
```json
{
  "job_id": "j-001",
  "project_id": "...",
  "command": ["conda", "run", "-n", "isce3gpu", "python", "-m", "nisar.workflows.insar", "..."],
  "status": "running",
  "pid": 12345,
  "submitted_at": "2026-03-24T10:10:00Z",
  "log_path": "/data/projects/my-insar-run/logs/j-001.log",
  "dry_run": false,
  "poll": "insar_get_job(job_id='j-001', project_id='...')"
}
```

**Errors:**
- `project_not_found`
- `runconfig_invalid` — validation failed; `errors` field contains the list
- `export_failed` — could not write YAML to configs dir
- `launch_failed` — subprocess failed to start

**Implementation:** `engines/isce3/runner.py`, `engines/isce3/validator.py`, `core/jobs.py`

---

### `insar_get_job`

Returns the current state of any job — ISCE3 workflow jobs, MintPy jobs, or batch jobs.
Optionally includes the full log content.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `job_id` | string | yes | Job UUID |
| `project_id` | string | cond. | Project UUID — required for ISCE3 workflow jobs |
| `work_dir` | string | cond. | MintPy work directory — required for MintPy jobs |
| `batch_dir` | string | cond. | Batch output directory — required for insar_run_batch jobs |
| `include_logs` | boolean | no | If true, include full log content in response (default: false) |

Provide exactly one of `project_id`, `work_dir`, or `batch_dir`.

**Returns (ISCE3 job):**
```json
{
  "job_id": "j-001",
  "project_id": "...",
  "status": "done",
  "pid": 12345,
  "exit_code": 0,
  "submitted_at": "2026-03-24T10:10:00Z",
  "started_at": "2026-03-24T10:10:01Z",
  "finished_at": "2026-03-24T11:25:00Z",
  "log_path": "/data/projects/my-insar-run/logs/j-001.log",
  "runconfig_path": "/data/projects/my-insar-run/configs/runconfig.yaml"
}
```

**Returns (MintPy job, work_dir provided):**
```json
{
  "job_id": "m-001",
  "status": "running",
  "pid": 23456,
  "submitted_at": "2026-03-24T12:00:00Z",
  "finished_at": null,
  "log_path": "/mintpy/logs/m-001.log"
}
```

**Returns (batch job, batch_dir provided):**
```json
{
  "job_id": "b-001",
  "batch_dir": "/data/stack",
  "batch_type": "stack",
  "num_pairs": 6,
  "status": "running",
  "pid": 34567,
  "exit_code": null,
  "submitted_at": "2026-03-24T14:00:00Z",
  "started_at": "2026-03-24T14:00:01Z",
  "finished_at": null,
  "log_path": "/data/stack/logs/b-001.log"
}
```

When `include_logs=true`, a `log_content` field is added with the full log text.

**Status values:** `running`, `done`, `failed`

**Errors:**
- `project_not_found`
- `job_not_found`
- `path_not_found` — work_dir or batch_dir does not exist
- `missing_param` — none of project_id, work_dir, or batch_dir provided
- `status_failed` — unexpected error reading job state

**Implementation:** `core/jobs.py`, `engines/isce3/mintpy.py`

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

---

### `insar_run_batch`

Execute a prepared stack or network batch by launching its `run_parallel.sh` script in the background.

Call `insar_prepare_stack` or `insar_prepare_network` first, then call this tool to start execution.
Returns immediately with `job_id` and `log_path`. The batch runs as a background process.

After calling, show `log_path` to the user — they can monitor real-time ISCE3 output with `tail -f <log_path>`. Poll status with `insar_get_job(job_id=..., batch_dir=...)`.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `batch_dir` | string | yes | Output directory used in `insar_prepare_stack` or `insar_prepare_network` |
| `max_jobs` | int | no | Maximum parallel ISCE3 pairs (default: 4) |

**Returns:**
```json
{
  "job_id": "b-001",
  "batch_dir": "/data/stack",
  "batch_type": "stack",
  "num_pairs": 6,
  "pid": 34567,
  "status": "running",
  "log_path": "/data/stack/logs/b-001.log",
  "poll": "insar_get_job(job_id=\"b-001\", batch_dir=\"/data/stack\")"
}
```

`batch_type` is auto-detected: `"network"` if `pair_lists/` directory exists, otherwise `"stack"`.

**Errors:**
- `not_prepared` — `run_parallel.sh` not found; call `insar_prepare_stack` or `insar_prepare_network` first
- `no_pairs_to_run` — no `*.yaml` files in `runconfigs/`
- `launch_failed` — subprocess could not be started

**Job persistence:** `{batch_dir}/.insar_agent/jobs/{job_id}.json`

**Implementation:** `mcp/server.py`, `core/jobs.py::BatchJob`

---

## Group 6: Utilities (M5)

These tools support data preparation and output conversion tasks that are independent of the project registry.

---

### `insar_extract_bbox`

Extract the union bounding box from one or more NISAR RSLC HDF5 files. Use before downloading a DEM to ensure full coverage.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `rslc_paths` | list[string] | yes | Absolute paths to NISAR RSLC `.h5` files |

**Returns:**
```json
{
  "min_lon": 120.5,
  "min_lat": 35.2,
  "max_lon": 121.3,
  "max_lat": 36.0,
  "n_files": 2
}
```

**Errors:**
- `invalid_input` — empty list
- `path_not_found` — one or more files do not exist
- `bbox_failed` — could not read bounding polygon from HDF5

**Implementation:** `engines/isce3/bbox.py::union_bbox`

---

### `insar_export_geotiff`

Convert a NISAR GUNW HDF5 product to GeoTIFF + PNG browse images. Iterates all spatial datasets in the file and writes outputs under `<output_dir>/browse/`.

Requires h5py, numpy, and GDAL — must be run inside the isce3 conda environment.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `h5_path` | string | yes | Absolute path to a NISAR GUNW `.h5` output file |
| `output_dir` | string | yes | Directory where `browse/` subdirectory will be created |

**Returns:**
```json
{
  "output_dir": "/data/.../browse",
  "n_files": 4,
  "files": ["/data/.../browse/unwrappedPhase.tif", "..."],
  "skipped": []
}
```

**Errors:**
- `path_not_found` — h5_path does not exist
- `dependency_missing` — h5py, numpy, or GDAL not available in current environment
- `export_failed` — unexpected error during conversion

**Implementation:** `engines/isce3/geotiff.py::export_geotiff`

---

## Group 7: MintPy Time-Series (M6)

These tools run MintPy time-series analysis on a completed ISCE3 interferogram network (Path B, filesystem-direct — no project registry).

---

### `insar_run_mintpy`

Launch MintPy time-series processing asynchronously. Wraps `run_mintpy_nisar_stack.sh` inside the given conda environment. Logs are written to `<mintpy_work_dir>/logs/<job_id>.log`. Job metadata is persisted to `<mintpy_work_dir>/.jobs/<job_id>.json`.

Requires MintPy and GDAL in the conda environment.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `mintpy_work_dir` | string | yes | Output directory for MintPy results |
| `gunw_glob` | string | yes | Shell glob matching GUNW `.h5` files, e.g. `/path/to/network/runs/*/products/*.h5` |
| `mintpy_config` | string | yes | Path to MintPy smallbaselineApp config file (`.cfg` or `.txt`) |
| `dem_path` | string | yes | Path to the DEM GeoTIFF used during ISCE3 processing |
| `conda_env` | string | yes | Conda environment that contains MintPy and GDAL |

**Returns:**
```json
{
  "job_id": "uuid",
  "pid": 12345,
  "status": "running",
  "log_path": "/work/mintpy/logs/uuid.log",
  "submitted_at": "2026-01-01T00:00:00+00:00",
  "poll": "insar_get_job(job_id='uuid', work_dir='/work/mintpy')",
  "work_dir": "/work/mintpy"
}
```

**Errors:**
- `invalid_input` — `gunw_glob` is empty
- `path_not_found` — `mintpy_config` or `dem_path` does not exist
- `launch_failed` — subprocess could not be started

**Implementation:** `engines/isce3/mintpy.py::run_mintpy`

---

### _Removed: `insar_get_mintpy_status`_

Use `insar_get_job(job_id=..., work_dir=<mintpy_work_dir>)` instead.
The `poll` field returned by `insar_run_mintpy` already contains the correct call.

---

### `insar_plot_baseline`

Generate a spatiotemporal baseline network plot and CSV files from a completed interferogram network. Reads perpendicular baseline from GUNW HDF5 products, solves per-scene baselines via least-squares, and saves PNG, PDF, and two CSV files.

Requires h5py, matplotlib, and numpy — must be run inside the isce3 conda environment.

**Parameters:**

| Name | Type | Required | Description |
|------|------|----------|-------------|
| `network_dir` | string | yes | Network output directory containing `runs/` and `pair_lists/` |
| `pair_list` | string | no | Path to a pair-list file (`YYYYMMDD_YYYYMMDD` per line). Leave empty to use `pair_lists/pairs_selected.txt` |
| `title` | string | no | Figure title (default: `"ISCE3 Spatiotemporal Baseline Network"`) |

**Returns:**
```json
{
  "png_path": "/network/pair_lists/baseline_network.png",
  "pdf_path": "/network/pair_lists/baseline_network.pdf",
  "pair_csv": "/network/pair_lists/pair_baselines.csv",
  "scene_csv": "/network/pair_lists/scene_baselines.csv",
  "n_pairs": 12
}
```

**Errors:**
- `path_not_found` — `network_dir` or explicit `pair_list` does not exist
- `dependency_missing` — h5py, matplotlib, or numpy not available
- `plot_failed` — unexpected error during plot generation

**Implementation:** `engines/isce3/baseline.py::plot_baseline_network`
