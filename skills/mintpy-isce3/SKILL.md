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

## Execution modes

- Default to `interaction_mode="interactive"`.
- At the start, tell the user they can switch to `interaction_mode="auto"` if they want
  the AI to keep going with minimal interruptions.
- In `interactive` mode, obey MCP handoff points. In particular, baseline review is a
  mandatory pause before MintPy.
- In `auto` mode, keep going when inputs are complete, but still show `log_path`, `poll`,
  and output paths after every background launch.

## Required confirmations (ask only if missing)

- `network_dir`: completed interferogram network directory with real GUNW products under
  `runs/*/products/*.h5`
- `mintpy_work_dir`: output directory for MintPy results
- `mintpy_config`: path to MintPy smallbaselineApp config file (`.cfg` or `.txt`)
- `dem_path`: path to DEM GeoTIFF (`.tif`) — same DEM used in ISCE3 processing
- `conda_env`: conda environment name that contains MintPy and GDAL
- Confirm that the chosen `conda_env` can actually run `smallbaselineApp.py`
- Pair list path (optional — defaults to `pair_lists/pairs_selected.txt`)
- Interaction mode: `interactive` (default) or `auto`

## Hard constraints

- All ISCE3 and MintPy operations must go through `insar_*` MCP tools. Do not run conda/python commands directly.
- If workflow parameters are unclear, ask the user — do not invent them.
- Run Step 1 (baseline plot) before Step 2 (MintPy).
- Do not modify `mintpy_config` content. If MintPy parameters need tuning, tell the user to edit the config manually.
- Do not continue to MintPy if the network has not actually produced GUNW products.
- Baseline plotting and MintPy are different runtime concerns: baseline review depends on the
  tool runtime being able to read GUNW products and plot, while MintPy execution depends on
  the user-confirmed `conda_env`.

## Standard workflow (always follow this order)

### Step 1 — Visualise baseline network

```
insar_plot_baseline(
    network_dir=<network_dir>,
    pair_list="",          # leave empty to use pairs_selected.txt
    title="ISCE3 Spatiotemporal Baseline Network",
    interaction_mode=<interactive|auto>
)
```

The response includes `handoff_required`, `handoff_reason`, `review_artifacts`, and
`next_recommended_action`.

Report to the user:
- `n_pairs`: number of interferogram pairs
- `png_path`: baseline network figure path
- `pair_csv` / `scene_csv`: CSV files with baseline statistics

If `handoff_required=true`, stop and ask the user to review the baseline plot before
proceeding. If the network looks unreasonable (e.g. very long temporal baselines,
sparse connections), return to `insar_prepare_network` and adjust the pair selection.
If `handoff_required=false`, show the same review artifacts briefly, then continue.

### Step 2 — Launch MintPy time-series processing

```
insar_run_mintpy(
    mintpy_work_dir=<mintpy_work_dir>,
    gunw_glob="<network_dir>/runs/*/products/*.h5",
    mintpy_config=<mintpy_config>,
    dem_path=<dem_path>,
    conda_env=<conda_env>,
    interaction_mode=<interactive|auto>
)
```

Save the returned `job_id`. Show `log_path`, `poll`, and `progress_hint`.

### Step 3 — Poll status

Call `insar_get_job(job_id=<job_id>, work_dir=<mintpy_work_dir>)`
every ~60 s until `status` is `done` or `failed`.

### Step 4 — If failed, read logs

Call `insar_get_job(job_id=<job_id>, work_dir=<mintpy_work_dir>, include_logs=True)`
or read the last lines of `log_path`. Summarise key error lines. Suggest:
- Path issues → fix and re-run `insar_run_mintpy`
- MintPy parameter issues → user must edit `mintpy_config` manually, then re-run

## Output requirements (report after completion)

- Final job status (`done` / `failed`)
- `mintpy_work_dir` contents (timeseries.h5, velocity.h5, etc.)
- `log_path` location for the user's reference
- Baseline plot paths (from Step 1)
- `mintpy_config` path and chosen `conda_env`
