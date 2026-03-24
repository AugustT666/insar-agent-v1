# Domain Model

This document defines the core data objects in `insar-agent`: their fields, types, lifecycle, storage format, and location in the codebase.

For system context see [architecture.md](architecture.md).

---

## Project

Represents one InSAR processing project. A project binds an engine, a workflow, and a workspace together, and holds the current runconfig state.

**Python location:** `src/insar_agent/core/project.py`

**Persisted as:** JSON file at `{workspace_root}/.insar_agent/project.json`

### Fields

| Field | Type | Description |
|---|---|---|
| `project_id` | `str` (UUID) | Unique identifier, generated at creation |
| `name` | `str` | Human-readable name |
| `engine` | `str` | Engine name, e.g. `"isce3"` |
| `workflow` | `str` | Workflow name, e.g. `"insar"` |
| `runconfig` | `dict` | Current runconfig state (nested dict) |
| `runconfig_template` | `dict` | Original default template (read-only reference) |
| `workspace_root` | `str` | Absolute path to the project workspace directory |
| `created_at` | `str` (ISO 8601) | Creation timestamp |
| `updated_at` | `str` (ISO 8601) | Last modification timestamp |

### Lifecycle

```
insar_create_project
  → Project created with default runconfig template loaded from engines/isce3/defaults.py
  → Saved to workspace_root/.insar_agent/project.json

insar_set_runconfig_value / insar_unset_runconfig_value
  → runconfig dict mutated via core/config.py
  → Project re-saved, updated_at refreshed

insar_export_runconfig
  → runconfig dict rendered to YAML at workspace_root/configs/runconfig.yaml
  → export path recorded on Project
```

### Runconfig structure

The `runconfig` field mirrors the ISCE3 YAML structure as a nested Python dict. Keys are accessed using dotted paths via `core/config.py`:

```python
# Example key: "runconfig.groups.input_file_group.reference_rslc_file"
get_path(project.runconfig, "runconfig.groups.input_file_group.reference_rslc_file")
set_path(project.runconfig, "runconfig.groups.worker.gpu_enabled", True)
```

---

## Job

Represents one execution of a workflow. A project can have multiple jobs (one at a time in V1).

**Python location:** `src/insar_agent/core/jobs.py`

**Persisted as:** JSON file at `{workspace_root}/.insar_agent/jobs/{job_id}.json`

### Fields

| Field | Type | Description |
|---|---|---|
| `job_id` | `str` (UUID) | Unique identifier |
| `project_id` | `str` (UUID) | Parent project |
| `engine` | `str` | Engine used for this run |
| `workflow` | `str` | Workflow executed |
| `status` | `JobStatus` (enum) | See status values below |
| `command` | `list[str]` | Full command passed to subprocess |
| `runconfig_path` | `str` | Path to the YAML file used for this run |
| `submitted_at` | `str` (ISO 8601) | When `insar_run_workflow` was called |
| `started_at` | `str \| None` | When the subprocess started |
| `finished_at` | `str \| None` | When the subprocess exited |
| `exit_code` | `int \| None` | Subprocess exit code (0 = success) |
| `log_path` | `str` | Path to the log file |
| `output_paths` | `list[str]` | Paths of output files recorded after completion |

### Status enum

| Value | Meaning |
|---|---|
| `pending` | Created but not yet started |
| `running` | Subprocess is active |
| `done` | Subprocess exited with code 0 |
| `failed` | Subprocess exited with non-zero code or raised an exception |

### Lifecycle

```
insar_run_workflow
  → Job created with status=pending
  → Command built by engines/isce3/runner.py
  → Subprocess launched; status → running
  → On exit: status → done or failed, exit_code recorded

insar_get_job_status
  → Reads job JSON; if process still running, checks subprocess state

insar_get_job_logs
  → Reads log_path; supports tail parameter

insar_list_outputs
  → Scans workspace_root/outputs/ and records paths into output_paths
```

---

## WorkflowTemplate

Describes a workflow supported by an engine: its default runconfig, GPU support, and human-readable description. This object is not persisted — it lives in-memory from `defaults.py`.

**Python location:** `src/insar_agent/engines/base.py` (dataclass), `src/insar_agent/engines/isce3/defaults.py` (instances)

### Fields

| Field | Type | Description |
|---|---|---|
| `engine` | `str` | Engine name |
| `workflow` | `str` | Workflow name |
| `supports_gpu` | `bool` | Whether GPU acceleration is available |
| `description` | `str` | One-line description of the workflow |

> **Note:** `default_config_path` and `schema_path` fields are planned for M1 to support loading ISCE3 default YAML templates from disk. Currently `SUPPORTED_WORKFLOWS` in `defaults.py` only carries the fields above.

### Current instances (`defaults.py`)

| workflow | supports_gpu | description |
|---|---|---|
| `gslc` | `True` | Geocode SLC products from RSLC inputs |
| `insar` | `True` | Generate interferometric products from reference/secondary RSLC inputs |

---

## Artifact

Represents a single output file produced by a job. Artifact records are stored as entries in the `output_paths` list of a `Job`, with metadata inferred from file extension and ISCE3 naming conventions.

**Python location:** planned for `src/insar_agent/core/jobs.py` or a dedicated `artifacts.py`

### Fields

| Field | Type | Description |
|---|---|---|
| `job_id` | `str` | Parent job |
| `artifact_type` | `ArtifactType` (enum) | See type values below |
| `path` | `str` | Absolute file path |
| `description` | `str` | Human-readable label |
| `recommended_viewer` | `str` | Suggested tool to open this file |

### Artifact type enum

| Value | Extension | Description |
|---|---|---|
| `hdf5` | `.h5`, `.hdf5` | ISCE3 / NISAR science products |
| `yaml` | `.yaml`, `.yml` | Exported runconfig |
| `log` | `.log` | Workflow execution log |
| `geotiff` | `.tif`, `.tiff` | Exported raster product |
| `preview` | `.png` | Lightweight preview image |

---

## Workspace Layout

A project workspace at `workspace_root/` has this structure:

```text
workspace_root/
  .insar_agent/
    project.json          ← Project record
    jobs/
      {job_id}.json       ← Job record per run
  configs/
    runconfig.yaml        ← Last exported runconfig
  logs/
    {job_id}.log          ← Per-job log file
  outputs/
    {job_id}/             ← Output files for each run
      *.h5
      *.tif
      preview.png
```
