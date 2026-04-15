---
name: stack-insar-isce2
description: >
  Use for Sentinel-1 time-series InSAR processing with ISCE2 (stackSentinel.py + MintPy).
  Invoke when the user wants to process multiple S1 scenes to produce a deformation
  time series or velocity map.
  Triggers on: "S1 time series", "Sentinel-1 stack", "stackSentinel", "S1 velocity",
  "s1 time-series insar", "sentinel stack processing", "isce2 stack".
  If Sentinel SAFE/ZIP inputs are not already organized into grouped SAFE paths,
  invoke `data-prep` first.
---

# Sentinel-1 Time-Series InSAR with ISCE2

## Required confirmations (ask only if missing)

- Grouped Sentinel-1 SAFE directory (e.g., `safe/s1a_asc_rel014/`)
- DEM path (`.tif`) — if missing, invoke `data-prep` first
- Precise orbit directory — if missing, can be downloaded via `data-prep`
- Workspace / output directory (absolute path)
- Conda environment name — run `conda env list` and let user choose from isce2-related envs

## Execution modes

- Default to `interaction_mode="interactive"`.
- At the start, tell the user they can switch to `interaction_mode="auto"` if they want
  the AI to keep going with minimal interruptions.
- **interactive**: At Step 5.5, pause and ask the user whether to run param-advisor (engine=isce2).
  Wait for confirmation before proceeding.
- **auto**: At Step 5.5, automatically enter param-advisor (engine=isce2) without asking.
  Skip only if the user has explicitly said to use default parameters.


## Prerequisites

```
insar_check_env()
```

Confirm `envs.isce2.status == "ok"`.
If missing, invoke the `env-setup` skill first.

---

## Workflow

### Step 1 — Ensure Sentinel data is prepared

If the user only has raw SAFE ZIP / SAFE / burst inputs, stop and invoke:

```
data-prep
```

Use one returned grouped SAFE directory plus the returned `dem_path` and `orbit_dir` as the handoff for this skill.

---

### Step 2 — Inspect a representative scene

```python
insar_describe_s1(zip_path="/mnt/.../safe/s1a_asc_rel014/S1A_IW_SLC__...SAFE")
```

Note: relative orbit, polarization, pass direction, bbox.

---

### Step 3 — Reuse prepared DEM and orbits

Prefer the `dem_path` and `orbit_dir` returned by `data-prep`.
Only ask the user for replacements if they explicitly want to override them.
The user still needs to provide:

- `workspace_root`

---

### Step 4 — Create stack project

```
insar_create_project(
    engine="isce2",
    workflow="stack",
    workspace_root="/mnt/HDD2T/August/<project>/<stack_name>",
    name="s1-stack-<region>",
    conda_env="isce2"
)
```

---

### Step 5 — Set stack parameters

Mandatory fields:

```
insar_set_processing_param(project_id, key="slc_dir",
    value="/mnt/.../safe/s1a_asc_rel014", justification="directory containing grouped S1 SAFE inputs for one stack")

insar_set_processing_param(project_id, key="orbit_dir",
    value="/mnt/.../orbits", justification="prepared POEORB orbit files directory")

insar_set_processing_param(project_id, key="dem_file",
    value="/mnt/.../dem/dem.tif", justification="prepared DEM path from data-prep")
```

Key optional parameters:

| Key | Default | Notes |
|-----|---------|-------|
| `bbox` | None | Crop to AOI: `[S, N, W, E]` |
| `swaths` | `[1,2,3]` | Process subset for speed |
| `num_connections` | 3 | Interferogram connections per scene |
| `coregistration` | `"NESD"` | ESD-based; use `"geometry"` if ESD fails |
| `range_looks` / `azimuth_looks` | 20 / 4 | Multilook factors |
| `filter_strength` | 0.5 | Goldstein filter strength |
| `unwrap_method` | `"snaphu"` | Unwrapping algorithm |

---

### Step 5.5 — Optional parameter tuning

If the user wants help choosing looks, network density, coregistration mode,
filtering, or swath/bbox tradeoffs, enter:

```
param-advisor (engine=isce2)
```

This should happen **after required fields are set and before `insar_run_workflow`**.
The advisor flow should build a compressed evidence profile from:

- `insar_get_runconfig(format='yaml')`
- `insar_describe_s1(...)` on 1–3 representative scenes from `slc_dir`

The skill then delegates recommendation generation to:

- `.claude/agents/param-advisor.md`

and applies accepted changes via `insar_set_processing_param` only.

---

### Step 6 — Run stackSentinel (prepare + execute)

```
insar_run_workflow(project_id=project_id)
```

This calls `stackSentinel.py` which:
1. Reads the SAFE inputs from the selected grouped directory
2. Downloads orbit files if needed
3. Generates a series of `run_*` shell scripts in `<workspace>/run_files/`
4. Executes those scripts in order (coregistration → interferogram → unwrap)

For multi-hour stack jobs, prefer a background launcher or background shell session instead of blocking the main conversation. Always return:

- the background job id or PID
- the absolute log path
- the exact polling command or MCP status call

Monitor with `insar_get_job(job_id=job_id, project_id=project_id)`.
Plugin-controlled launcher logs are written under `<workspace_root>/.insar_logs/`.
If you need to execute generated `run_*` scripts manually, also redirect stdout/stderr to a durable log file under `<workspace>/run_files/` and show that path to the user.

> Runtime: several hours to days depending on scene count and AOI size.

---

### Step 7 — MintPy time-series analysis

After stack processing completes, delegate to the unified **mintpy** skill with `engine=isce2`:

```
Invoke the /insar-agent:mintpy skill
- engine: isce2
- stack_work_dir: "/mnt/.../sentinel-stack/..."
- mintpy_work_dir: "/mnt/.../sentinel-stack/.../mintpy"
- interaction_mode: interactive (default) or auto
```

The mintpy skill will:
- Validate the ISCE2 stack structure
- Prepare the MintPy config if needed
- Launch `insar_run_mintpy_isce2` with appropriate parameters
- Poll the background job and report completion

MintPy reads the ISCE2 stack outputs and performs:
- Network inversion → displacement time series
- Velocity estimation
- Tropospheric / DEM error correction (optional)

For advanced tuning of MintPy parameters, the user can edit the MintPy config file directly.


---

### Step 8 — Optional baseline inspection

For ISCE2 stacks, baseline products are typically prepared by topsStack itself under
`<stack_work_dir>/merged/baselines/` and `baselines_txt/`. Do **not** call the
ISCE3-only `insar_plot_baseline(network_dir=...)` tool here.

If the user wants to inspect baseline connectivity, point them to the generated
baseline text products inside the stack work directory or continue through the unified
`mintpy` skill, which treats ISCE2 baseline plotting as optional.

---

### Step 9 — Export results

```
insar_list_outputs(project_id=project_id)
insar_export_geotiff(project_id=project_id, product="velocity")
```

Key MintPy outputs:

| File | Description |
|------|-------------|
| `timeseries.h5` | Displacement time series (m) |
| `velocity.h5` | Line-of-sight velocity (m/yr) |
| `temporalCoherence.h5` | Temporal coherence mask |
| `geometryGeo.h5` | Incidence angle, heading, DEM |

---

## Hard constraints

- All scenes must share the same relative orbit number.
- If raw Sentinel inputs are not yet organized, always go through `data-prep` first.
- `data-prep` is expected to prepare grouped SAFE paths, `dem_path`, and `orbit_dir`.
- Orbit files (POEORB) must be pre-downloaded or accessible online.
  ISCE2 can auto-download them if `fetchOrbit.py` can reach ESA servers.
- `slc_dir` must contain only the S1 ZIPs/SAFEs for this stack (no mixed orbits).
- Sentinel MintPy runs in the `isce2` conda env after MintPy is installed there.
- Do not mix ascending and descending pass scenes in the same stack.
- Processing must run inside `conda run -n isce2` (handled automatically by the tool).
