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
  through `insar_set_runconfig_value`. If the user wants to tune them, this workflow must
  invoke `param-advisor-isce3` **between Step 2 and Step 3** (after setting paths,
  before launch).
- Always start from the default runconfig template — `insar_create_project` loads it automatically.
- If `insar_set_runconfig_value` returns `key_not_allowed`, do NOT attempt workarounds. Tell the
  user that only whitelist-controlled processing parameters may be changed through
  `param-advisor-isce3` + `insar_set_processing_param`.

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

2.5. **（可选）参数调优** — 若用户需要调整处理参数：
   进入 `param-advisor-isce3`。该 skill 负责：
   - 调 `insar_describe_rslc`
   - 调 `.claude/agents/param-advisor-isce3.md`
   - 展示参数 diff 和三选一确认
   - 如用户接受建议，调用 `insar_set_processing_param`
   - 调 `insar_get_runconfig(format='yaml')` 展示完整 YAML
   完成后再回到本 workflow 继续 Step 3。

3. **Run workflow**
   ```
   insar_run_workflow(project_id)
   ```
   This call already validates and exports the YAML before launch. Save the returned `job_id`
   and `log_path`. Tell the user the log path so they can monitor
   real-time ISCE3 output if desired:
   ```bash
   tail -f <log_path>
   ```
   The response also includes a `poll` field with the exact call to use.

4. **Poll status** — call `insar_get_job(job_id, project_id)` every ~30 s until
   `status` is `done` or `failed`.

5. **If failed — read logs**
   ```
   insar_get_job(job_id, project_id, include_logs=True)
   ```
   Summarize the key error lines. Suggest path-only fixes. For whitelist-controlled
   processing issues, re-enter `param-advisor-isce3`.

6. **List outputs**
   ```
   insar_list_outputs(job_id, project_id)
   ```

7. **Export GeoTIFF (optional)** — if the user wants raster visualization:
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
