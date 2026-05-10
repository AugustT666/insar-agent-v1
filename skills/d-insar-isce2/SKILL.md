---
name: d-insar-isce2
description: >
  Use for Sentinel-1 single-pair D-InSAR processing with ISCE2 (topsApp.py).
  Invoke when the user wants to process a pair of Sentinel-1 scenes to produce
  an interferogram, coherence map, or unwrapped displacement.
  Triggers on: "S1 interferogram", "Sentinel-1 DInSAR", "topsApp", "isce2 process",
  "S1 pair", "sentinel deformation", "C-band interferogram".
  If Sentinel SAFE/ZIP inputs are not already organized into grouped SAFE paths,
  invoke `data-prep` first.
---

# Sentinel-1 D-InSAR with ISCE2 (Single Pair)

## Required confirmations (ask only if missing)

- Reference and secondary Sentinel-1 SAFE paths (or SAFE ZIP files)
- DEM path (`.tif`) — if missing, invoke `data-prep` first
- Precise orbit directory (`.orb` files) — if missing, can be downloaded via `data-prep`
- Workspace / output directory (absolute path)
- Conda environment name — run `conda env list` and let user choose from isce2-related envs

## Execution modes

- Default to `interaction_mode="interactive"`.
- At the start, tell the user they can switch to `interaction_mode="auto"` if they want
  the AI to keep going with minimal interruptions.
- **interactive**: At Step 4.5, pause and ask the user whether to run param-advisor (engine=isce2).
  Wait for confirmation before proceeding.
- **auto**: At Step 4.5, automatically enter param-advisor (engine=isce2) without asking.
  Skip only if the user has explicitly said to use default parameters.

## Prerequisites

Before starting, verify the ISCE2 environment is available:

```
insar_check_env()
```

Confirm `envs.isce2.status == "ok"`. If missing, invoke the `env-setup` skill first.

---

## Workflow

### Step 1 — Ensure Sentinel data is prepared

If the user only has raw SAFE ZIP / SAFE / burst inputs, stop and invoke:

```
data-prep
```

Select `engine=sentinel` and use the returned `grouped_safe_paths`, `dem_path`, and `orbit_dir` as the handoff.

---

### Step 2 — Inspect scene metadata

For the two selected SAFE / ZIP inputs, check key parameters before processing:

```python
insar_describe_s1(zip_path="/mnt/.../safe/s1a_asc_rel014/S1A_IW_SLC__...SAFE")
```

Confirm:
- Same `relative_orbit` for reference and secondary (required for InSAR)
- Same `mode` (IW)
- Compatible `polarizations` (e.g. both contain VV)
- `pass_direction` is consistent
- Temporal baseline is reasonable (6–48 days typical for S1)

---

### Step 3 — Reuse prepared DEM and orbits

Prefer the `dem_path` and `orbit_dir` returned by `data-prep`.
Only ask the user for replacements if they explicitly want to override them.
The user still needs to provide:

- `workspace_root`

---

### Step 4 — Create project

```
insar_create_project(
    engine="isce2",
    workflow="tops",
    workspace_root="/mnt/HDD2T/August/<project>/<pair_name>",
    name="s1-dinasr-<region>-<date>",
    conda_env="isce2"
)
```

Returns `project_id` and `required_fields` list.

---

### Step 5 — Set required parameters

Set all `required_fields` using `insar_set_processing_param`. Mandatory fields:

```
insar_set_processing_param(project_id, key="reference_safe",
    value="/mnt/.../safe/s1a_asc_rel014/S1A_IW_SLC__...SAFE", justification="reference scene path")

insar_set_processing_param(project_id, key="secondary_safe",
    value="/mnt/.../safe/s1a_asc_rel014/S1A_IW_SLC__...SAFE", justification="secondary scene path")

insar_set_processing_param(project_id, key="orbit_dir",
    value="/mnt/.../orbits", justification="prepared POEORB orbit files directory")

insar_set_processing_param(project_id, key="dem_file",
    value="/mnt/.../dem/dem.tif", justification="prepared DEM path from data-prep")
```

Optional parameters (change only if needed):

| Key | Default | When to change |
|-----|---------|---------------|
| `bbox` | None (full swath) | Limit to AOI: `[S, N, W, E]` |
| `swaths` | `[1,2,3]` | Process subset, e.g. `[2]` for speed |
| `polarization` | `"vv"` | Use `"vh"` for cross-pol applications |
| `range_looks` / `azimuth_looks` | 20 / 4 | Adjust for different resolution |
| `filter_strength` | 0.5 | 0 = no filter, 1 = max filter |
| `do_esd` | True | Set False if ESD fails in low-coherence |
| `unwrap_method` | `"snaphu"` | `"icu"` for faster but less robust |

---

### Step 4.5 — Optional parameter tuning

If the user wants help choosing looks, filtering, ESD, swaths, or unwrapping settings,
enter:

```
param-advisor (engine=isce2)
```

This should happen **after required path fields are set and before `insar_run_workflow`**.
The advisor flow must build a metadata-first evidence profile using:

- `insar_describe_s1(reference_safe)`
- `insar_describe_s1(secondary_safe)`
- `insar_get_runconfig(format='yaml')`

The skill then delegates recommendation generation to:

- `agents/param-advisor.md`

and applies accepted changes via `insar_set_processing_param` only.

---

### Step 5 — Run workflow

```
insar_run_workflow(project_id=project_id)
```

ISCE2 will:
1. Generate `configs/topsApp.xml` from project parameters
2. Launch `topsApp.py` in the `isce2` conda env
3. Return `job_id`, `log_path`, `pid`

---

### Step 6 — Monitor progress

```
insar_get_job(job_id=job_id, project_id=project_id)
```

Typical runtime: 30–120 minutes depending on scene size and number of swaths.

If the run is expected to take a long time, prefer launching it in the background rather than blocking the main session. Always provide the job id or PID plus the absolute log path so the user can inspect progress independently.

Show the user the log path for real-time monitoring:
```bash
tail -f <log_path>
```
Plugin-controlled launcher logs are written under `<workspace_root>/.insar_logs/`.

---

### Step 7 — Inspect outputs

```
insar_list_outputs(project_id=project_id)
```

Key output files (located under `workspace_root/`):

| File | Description |
|------|-------------|
| `merged/filt_topophase.unw.geo` | Geocoded unwrapped interferogram |
| `merged/filt_topophase.unw.geo.vrt` | VRT for GIS viewing |
| `merged/phsig.cor.geo` | Geocoded coherence |
| `merged/filt_topophase.flat.geo` | Flat-Earth corrected wrapped phase |
| `merged/dem.crop` | Cropped DEM used in processing |

---

## Hard constraints

- Reference and secondary must be from the same relative orbit (same track).
- Do NOT mix ascending and descending pass scenes.
- If raw Sentinel inputs are not yet organized, always go through `data-prep` first with `engine=sentinel`.
- `data-prep` is expected to prepare grouped SAFE paths, `dem_path`, and `orbit_dir`.
- `orbit_dir` must contain the correct POEORB files. ISCE2 downloads them
  automatically if `do_download_orbit` is enabled and internet is available.
- Processing must run inside `conda run -n isce2` — never run `topsApp.py` directly
  without the isce2 environment active.
- `insar_run_workflow` generates `topsApp.xml` automatically from project params.
  Do not edit the XML manually — use `insar_set_processing_param` instead.

---

## Troubleshooting

### Orbit Download Timeouts

**Symptom**: `RETRY attempt X after transient failure: Connection timeout` appears repeatedly in logs.

**Cause**: Network connectivity issues reaching `dataspace.copernicus.eu` (ESA Dataspace service).

**Solutions**:
1. **Auto-Retry (Default)**: The MCP tool automatically retries orbit downloads with exponential backoff (3 attempts, 2–8 second delays). Check logs to see if the retry succeeds.
2. **Pre-Download Orbits**: Use `data-prep` with `engine=sentinel` and `download_orbits=True` before workflow launch.
3. **Provide Orbit Directory**: If orbits are already cached, set `orbit_dir` to the directory containing `.EOF` files and omit `download_orbits`.
4. **Check Credentials**: Verify dataspace.copernicus.eu credentials are correct (in `~/.netrc` or via `orbit_username`/`orbit_password`).

### ESD Failures in Low-Coherence Areas

**Symptom**: `EstimateSlant2GroundRange (ESD) failed` appears in logs, but interferogram generation succeeds.

**Cause**: Enhanced Spectral Diversity (ESD) is sensitive to low coherence (< 0.3) in forests, water, or complex terrain.

**Solutions**:
1. **Disable ESD**: Set `do_esd=False` in Step 5 (optional parameters).
2. **Increase Filter Strength**: Set `filter_strength=0.8` to pre-filter phase before ESD.
3. **Reduce Swaths**: Process only high-coherence swaths (e.g., `swaths=[1]` instead of `[1,2,3]`).

### Unwrapping Failures (SNAPHU)

**Symptom**: SNAPHU phase unwrapper crashes or produces unrealistic displacement fields.

**Cause**: Often caused by wrapped-phase discontinuities in low-coherence regions or incorrect cost function parameters.

**Solutions**:
1. **Use ICU Instead**: Set `unwrap_method="icu"` for faster, albeit less robust, unwrapping.
2. **Reduce Looks**: Increase `azimuth_looks` to 6 or higher to smooth phase before unwrapping.
3. **Increase Filter**: Set `filter_strength=0.8–1.0` to maximize coherence before unwrapping.
4. **Subset Swaths**: Try `swaths=[2]` to isolate a single high-coherence swath.

### Low Coherence Output

**Symptom**: Coherence map (`.cor.geo`) is predominantly < 0.3, making phase unreliable.

**Cause**: Temporal decorrelation (scenes too far apart), geometric decorrelation (steep topography), or volumetric scattering (dense vegetation).

**Solutions**:
1. **Check Temporal Baseline**: Run `insar_describe_s1` on both scenes and verify baseline is 6–48 days (Sentinel-1 typical).
2. **Check Baseline Direction**: Perpendicular baseline > 150 m can amplify geometric decorrelation. Choose scenes with smaller perpendicular separation.
3. **Subset to Coherent Regions**: Use `bbox` parameter to focus on stable areas (water bodies, urban areas, bare rock).
4. **Use Ascending + Descending Pair**: Combine ascending and descending geometries in a stack (use `stack-insar-isce2` instead) to decorrelate topographic effects.

### Memory or Compute Constraints

**Symptom**: Process hangs, OOM kill, or extreme runtime (> 4 hours).

**Cause**: Processing full-resolution multi-swath interferogram uses 40–80 GB RAM; large datasets or low-spec hardware.

**Solutions**:
1. **Reduce Looks Aggressively**: Set `azimuth_looks=8`, `range_looks=40` to downsample.
2. **Limit Swaths**: Use `swaths=[2]` instead of `[1,2,3]`.
3. **Use Smaller AOI**: Set `bbox=[lon_min, lat_min, lon_max, lat_max]` to clip to region of interest.
4. **Increase System Swap**: If out of RAM, temporarily increase swap space, but note processing will be very slow.

### No Output Files Generated

**Symptom**: `insar_list_outputs` returns empty list; no `merged/` directory created.

**Cause**: `topsApp.py` failed early (before merging step) or was killed.

**Solutions**:
1. **Check Job Status**: Run `insar_get_job(job_id=...)` to see if job is `failed`, `timeout`, or still `running`.
2. **Inspect Raw Logs**: View full topsApp output at the log path from Step 6:
   ```bash
   tail -200 /path/to/workspace_root/.insar_logs/isce2_*.log
   ```
3. **Validate Inputs**: Verify both SAFE/ZIP paths exist and contain valid manifest files:
   ```bash
   unzip -l <safe.zip> | grep manifest.safe
   ```
4. **Check DEM Coverage**: Ensure DEM covers the interferogram AOI; run `insar_describe_s1` to see scene bounds.

### XML Generation or Parameter Errors

**Symptom**: Error message mentions `topsApp.xml` validation or `<parameter> not recognized`.

**Cause**: Project parameters do not conform to ISCE2 `topsApp` XML schema, or a path is invalid.

**Solutions**:
1. **Re-validate Paths**: Ensure `reference_safe`, `secondary_safe`, `dem_file`, `orbit_dir` all exist and are readable.
2. **Check Parameter Types**: Confirm numeric parameters (`range_looks`, `azimuth_looks`) are integers, not strings.
3. **Use Default Parameters**: If unsure, omit optional parameters and use defaults in Step 5.

---

## Expected Runtimes

For reference (Intel i7 with 32 GB RAM, NVMe storage):

| Swaths | Resolution | Typical Runtime |
|--------|------------|-----------------|
| 1      | 2-looks    | 15–30 min       |
| 2      | 2-looks    | 30–60 min       |
| 3      | 2-looks    | 60–120 min      |
| 3      | 1-looks    | 150–240 min     |

---

## Log Inspection

All processing logs are saved under `<workspace_root>/.insar_logs/`:

- `isce2_<job_id>.log` — Main ISCE2 process output (text format)
- `sentinel_prep_<job_id>.log` — Data preparation log (if data-prep was used)
- `sentinel_orbit_<job_id>.log` — Orbit download log with retry messages

To stream logs in real time during processing:
```bash
tail -f /path/to/workspace_root/.insar_logs/isce2_*.log
```

To search for error patterns:
```bash
grep -i "error\|failed\|exception" /path/to/workspace_root/.insar_logs/*.log
```
