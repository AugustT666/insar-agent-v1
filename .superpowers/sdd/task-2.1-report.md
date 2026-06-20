# Task 2.1 Report: Project State Under run_root/.insar_agent

## New Project Field Names

| Field | Type | Notes |
|---|---|---|
| `output_root` | `str` | Replaces `workspace_root`; top-level dir holding all runs |
| `task` | `str \| None` | New: workflow task identifier (e.g. `"stack-insar-isce2"`) |
| `run_id` | `str \| None` | Unchanged; pinned run identifier |
| `task_id` | `str \| None` | Retained for backwards-compatible JSON loading only |

`workspace_root` is no longer a dataclass field. A `@property` shim on `Project` returns `output_root` for Phase-3-unfixed call sites that read the attribute.

`new_project()` signature: `new_project(name, engine, workflow, output_root="", ..., workspace_root=None, task_id=None)` — legacy kwargs accepted transparently.

## Method Return Paths

| Method | Returns |
|---|---|
| `run_root()` | `<output_root>/<task or task_id or name>_<run_id>/` |
| `insar_dir()` | `run_root() / ".insar_agent"` |
| `jobs_dir()` | `insar_dir() / "jobs"` |
| `configs_dir()` | `run_root() / "insar_product" / "configs"` (via RunLayout) |
| `logs_dir()` | `run_root() / "insar_product" / "logs"` (via RunLayout) |
| `outputs_dir()` | `run_root() / "insar_product"` (via RunLayout) |

## project.json Schema

Required keys (written by `save()`, read by `find_run_root` / `_layout_from_run_root`):

```json
{
  "output_root": "<absolute path to output root>",
  "task": "<task identifier, e.g. stack-insar-isce2>",
  "run_id": "<run timestamp, e.g. 20260620T010203Z>",
  "task_id": null,
  ...other Project fields...
}
```

File location: `<output_root>/<task>_<run_id>/.insar_agent/project.json`

## Test Summary

`tests/unit/test_create_project_layout.py`: **13 passed**

## Downstream Breakage (Expected per Brief)

12 additional tests newly fail in `test_output_resolver.py`, `test_isce2_workflow_dedup.py`, `test_output_containment.py` — all use `Project(workspace_root=...)` directly. These are the "downstream callers" the brief identifies as Phase-3 work.

1 previously-passing test (`test_project_task_scoped_management_dirs_stay_under_task_root`) now fails because it asserted the old path `<workspace>/<task_id>/.insar_agent` (without run_id) which Task 2.1 intentionally changes.
