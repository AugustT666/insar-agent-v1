---
name: mintpy-isce3
description: >
  Use when the user wants to run MintPy time-series analysis on a completed
  ISCE3 interferogram network, or wants to visualise the spatiotemporal
  baseline network. Invoke when the user mentions MintPy, time-series,
  displacement time series, smallbaselineApp, temporal coherence, baseline
  plot, or asks to analyse results from insar_prepare_network.
  If the interferogram network is not yet ready, invoke stack-insar-isce3 first.
---

# MintPy Time-Series Analysis (Path B)

Path B tools operate directly on the filesystem and do not use the project registry.

## Required confirmations (ask only if missing)

- `network_dir`: interferogram network directory produced by `insar_prepare_network`
  (contains `runs/` and `pair_lists/`)
- `mintpy_work_dir`: output directory for MintPy results
- `mintpy_config`: path to MintPy smallbaselineApp config file (`.cfg` or `.txt`)
- `dem_path`: path to DEM GeoTIFF (`.tif`) — same DEM used in ISCE3 processing
- `conda_env`: conda environment name that contains MintPy and GDAL
- Pair list path (optional — defaults to `pair_lists/pairs_selected.txt`)

## Hard constraints

- All ISCE3 and MintPy operations must go through `insar_*` MCP tools. Do not run conda/python commands directly.
- If workflow parameters are unclear, ask the user — do not invent them.
- Run Step 1 (baseline plot) before Step 2 (MintPy). Wait for user confirmation between steps.
- Do not modify `mintpy_config` content. If MintPy parameters need tuning, tell the user to edit the config manually.

## Standard workflow (always follow this order)

### Step 1 — Visualise baseline network

```
insar_plot_baseline(
    network_dir=<network_dir>,
    pair_list="",          # leave empty to use pairs_selected.txt
    title="ISCE3 Spatiotemporal Baseline Network"
)
```

Report to the user:
- `n_pairs`: number of interferogram pairs
- `png_path`: baseline network figure path
- `pair_csv` / `scene_csv`: CSV files with baseline statistics

Ask the user to review the baseline plot before proceeding. If the network
looks unreasonable (e.g. very long temporal baselines, sparse connections),
suggest re-running `insar_prepare_network` with different parameters.

### Step 2 — Launch MintPy time-series processing

```
insar_run_mintpy(
    mintpy_work_dir=<mintpy_work_dir>,
    gunw_glob="<network_dir>/runs/*/products/*.h5",
    mintpy_config=<mintpy_config>,
    dem_path=<dem_path>,
    conda_env=<conda_env>
)
```

Save the returned `job_id`. Tell the user MintPy is running and to wait.

### Step 3 — Poll status

Call `insar_get_mintpy_status(job_id=<job_id>, mintpy_work_dir=<mintpy_work_dir>)`
every ~60 s until `status` is `done` or `failed`.

### Step 4 — If failed, read logs

Read the last 50 lines of `log_path` (use the Read tool or ask the user to
share the content). Summarise key error lines. Suggest:
- Path issues → fix and re-run `insar_run_mintpy`
- MintPy parameter issues → user must edit `mintpy_config` manually, then re-run

## Output requirements (report after completion)

- Final job status (`done` / `failed`)
- `mintpy_work_dir` contents (timeseries.h5, velocity.h5, etc.)
- `log_path` location for the user's reference
- Baseline plot paths (from Step 1)
