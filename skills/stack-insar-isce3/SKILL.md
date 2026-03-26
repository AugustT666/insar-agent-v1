---
name: stack-insar-isce3
description: >
  Use when the user has multiple NISAR RSLC files and wants to generate a batch
  interferogram network for time-series analysis. Invoke when the user mentions
  Stack-InSAR, batch processing, interferogram network, MintPy, time-series,
  multiple scenes, temporal baseline, or asks to process more than two RSLC files.
  Also invoke when the user wants to run parallel ISCE3 jobs across a scene stack.
  If the DEM or RSLC files are missing, invoke data-prep-nisar first.
---

# Stack-InSAR: Multi-scene Batch → Interferogram Network (Path B)

Path B tools operate directly on the filesystem and do not use the project registry.
Each step generates shell scripts that the user runs manually to launch parallel jobs.

## Required confirmations (ask only if missing)

- `data_dir`: directory containing multiple NISAR RSLC `.h5` files
- `base_runconfig`: base ISCE3 insar runconfig YAML (template) — e.g. `tests/fixtures/insar_nisar.yaml`
- DEM path (`.tif`) — if missing, invoke `data-prep-nisar` first
- Output directory for stack and network results
- Network mode: `tbase`, `conn`, or custom pair list (see `references/network-modes.md`)
- Number of parallel jobs (`N`) for the shell scripts

## Hard constraints

- All ISCE3 operations must go through `insar_*` MCP tools. Do not run conda/python commands directly.
- If workflow parameters are unclear, ask the user — do not invent them.
- Do not modify core processing parameters in the base runconfig. Path B tools inherit them.
- Run Step 1 and Step 2 separately. Wait for the user to confirm the shell script completed
  between steps.
- Reference scene defaults to the earliest date; only override if the user explicitly specifies.
- For custom pair list mode: file must contain one `YYYYMMDD_YYYYMMDD` pair per line.

## Standard workflow (always follow this order)

### Step 1 — Generate single-reference stack

```
insar_prepare_stack(
    data_dir=<rslc_dir>,
    base_runconfig=<template.yaml>,
    dem=<dem.tif>,
    output_dir=<stack_output_dir>,
    reference="auto"    # or YYYYMMDD, or absolute path
)
```

The response includes `run_command` with the exact shell command to run.
Tell the user to execute it:

```bash
bash <stack_output_dir>/run_parallel.sh <stack_output_dir> <N>
```

Wait for the user to confirm completion before proceeding to Step 2.

### Step 2 — Generate interferogram network

```
insar_prepare_network(
    data_dir=<rslc_dir>,
    base_runconfig=<template.yaml>,
    dem=<dem.tif>,
    output_dir=<network_output_dir>,
    network_mode="tbase",
    max_temporal_baseline_days=36,
    connection_span=3,
    pair_list=""
)
```

See `references/network-modes.md` for network strategy options.

The response includes `run_command` and `gunw_pattern`.
Tell the user to execute:

```bash
bash <network_output_dir>/run_parallel.sh <network_output_dir> <N>
```

## Output requirements (report after each step)

- Step 1: number of secondary scenes, reference date, `run_command` to execute
- Step 2: network mode, number of pairs, pair list path, `run_command` to execute
- Final output structure: `<network_output_dir>/runs/<date1>_<date2>/products/GUNW_*.h5`

## References

- `references/network-modes.md` — network strategy options and parameters
- `references/baseline-viz.md` — baseline network visualization after Step 2
