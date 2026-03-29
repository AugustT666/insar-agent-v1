---
name: d-insar-isce3
description: >
  Use when the user wants to process a single pair of NISAR RSLC files into a GUNW
  interferogram product. Invoke when the user provides reference and secondary RSLC
  paths, mentions D-InSAR, interferogram, coherence map, unwrapped phase, GUNW, or
  asks to "process a pair". Also invoke when the user has finished data preparation
  and has two RSLC files ready. If the DEM or RSLC files are missing, invoke
  data-prep-nisar first.
---

# D-InSAR: Single RSLC Pair → GUNW (Path A)

## Required confirmations (ask only if missing)

- Reference RSLC path (`.h5`)
- Secondary RSLC path (`.h5`)
- DEM path (`.tif`) — if missing, invoke `data-prep-nisar` first
- Workspace / output directory (absolute path)
- Conda environment name — run `conda env list` and let user choose from ISCE-related envs

## Hard constraints

- All ISCE3 operations must go through `insar_*` MCP tools. Do not run conda/python commands directly.
- If workflow parameters are unclear, ask the user — do not invent them.
- Core processing parameters (multilook, filtering, unwrapping, thresholds) cannot be changed
  via this skill. If the user wants to tune them, invoke `param-advisor-isce3` **between
  Step 2 and Step 3** (after setting paths, before validation). `param-advisor-isce3` will
  apply parameters via `insar_set_processing_param` and show the full runconfig for confirmation.
- Always start from the default runconfig template — `insar_create_project` loads it automatically.
- Never skip validation (`insar_validate_runconfig` must return `valid=true`) before Step 4.
- Never skip export (`insar_export_runconfig`) before Step 5.
- If `insar_set_runconfig_value` returns `key_not_allowed`, do NOT attempt workarounds. Tell the
  user the parameter must be edited manually in the exported YAML.

## Standard workflow (always follow this order)

1. **Create project**
   ```
   insar_create_project(engine="isce3", workflow="insar",
                        workspace_root=<path>, conda_env=<env>)
   ```
   Save the returned `project_id`. The response also includes `required_fields`.

2. **Set required path fields** (6 calls via `insar_set_runconfig_value`)

   See `references/runconfig-fields.md` for the full dotted-key names.

   Required fields: reference_rslc_file, secondary_rslc_file, dem_file,
   product_path, scratch_path, sas_output_file.

   Optional: `worker.gpu_enabled`, `worker.gpu_id`, `logging.path`

2.5. **（可选）参数调优** — 若用户需要调整处理参数（多视数、解缠算法等），在此步骤调用
   `param-advisor-isce3` skill。该 skill 会收集研究区和数据特征，给出参数建议，
   经用户三选一确认后通过 `insar_set_processing_param` 应用参数。
   完成后继续执行 Step 3。

3. **Validate**
   ```
   insar_validate_runconfig(project_id)
   ```
   If `valid=false`, fix the reported fields with `insar_set_runconfig_value` and re-validate.

4. **Export runconfig to disk**
   ```
   insar_export_runconfig(project_id)
   ```

5. **Run workflow**
   ```
   insar_run_workflow(project_id)
   ```
   Save the returned `job_id`. The response includes a `poll` field with the exact call to use.

6. **Poll status** — call `insar_get_job_status(job_id, project_id)` every ~30 s until
   `status` is `done` or `failed`.

7. **If failed — read logs**
   ```
   insar_get_job_logs(job_id, project_id, tail=50)
   ```
   Summarize the key error lines. Suggest path-only fixes. For core-parameter issues,
   tell the user to edit the YAML manually.

8. **List outputs**
   ```
   insar_list_outputs(job_id, project_id)
   ```

9. **Export GeoTIFF (optional)** — if the user wants raster visualization:
   ```
   insar_export_geotiff(h5_path=<GUNW .h5 path>, output_dir=<workspace>/browse)
   ```
   Requires GDAL in the isce3 conda environment.

## Output requirements (report after completion)

- Engine and workflow used (`isce3 / insar`)
- Reference and secondary RSLC paths
- DEM path used
- Product output path and filename
- Final job status (`done` / `failed`)
- List of output artifacts from `insar_list_outputs`

## References

- `references/runconfig-fields.md` — full dotted-key paths for all settable fields
