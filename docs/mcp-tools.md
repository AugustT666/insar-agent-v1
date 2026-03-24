# MCP Tools Reference

This document is the primary implementation reference for all MCP tools exposed by `insar-mcp-server`. Each tool entry defines its parameters, return structure, error cases, and which layer owns the logic.

For system context see [architecture.md](architecture.md). For data object definitions see [domain-model.md](domain-model.md).

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
