---
name: nisar-processing
description: Run ISCE3 NISAR workflows (focus/GSLC/GCOV/InSAR) using official runconfigs and conda execution. Use when asked to process NISAR data with ISCE3, generate NISAR products, export GeoTIFFs, or troubleshoot workflow failures while preserving reproducibility and only adjusting input/output paths.
---

# NISAR Processing with ISCE3

## Overview

Use official ISCE3 NISAR workflows to process data reliably and reproducibly. Do not invent workflows or alter core algorithm parameters.

## Required confirmations (ask only if missing)

- Target product/workflow (GSLC, GCOV, InSAR/GUNW, focus, etc.)
- Input data path(s)
- Output directory
- Conda env name (always run `conda env list` first and let the user choose among ISCE-related envs)
- DEM or area/bbox if DEM is required and cannot be inferred

## Hard constraints

- Do not create custom workflows; only call ISCE3 official NISAR workflows.
- Start from the default runconfig template: `references/insar_runconfig_full.yaml`.
- Only modify input/output paths, output directory, temp/work directory, and required external file paths (e.g., DEM).
- Do not change core processing parameters (multilook, filtering, unwrapping, thresholds, iterations, geometry/registration). If user asks, explain where they are and require user confirmation.

## Standard workflow (always follow this order)

1. Run `conda env list`, identify ISCE-related envs, and have the user choose.
2. Select the default runconfig template.
3. Copy the template runconfig into the target output directory (or user-specified target path).
4. Fill only allowed paths (inputs, outputs, temp, DEM path) in that copied runconfig.
5. Execute workflow inside conda env with a reproducible command (`conda run -n <env> ...`).
   - Preferred use module invocation:
     `conda run -n <env> python -m nisar.workflows.insar /path/to/runconfig.yaml`
6. Capture stdout/stderr to log files.
7. On success, report products, logs, and resolved runconfig.
8. On failure, localize stage, summarize key error lines, and provide path-only fixes. If core parameters are involved, require user edits.

## Output requirements (every run)

- Workflow name
- Input files/directories
- Output directory
- DEM usage and path (if used)
- Exact command or equivalent execution description
- Resolved runconfig path
- Product path list
- If DeepWiki used: cite source and short note

## Tools and bundled resources

### DEM generation

- Use `scripts/nisar_bbox_dem.py` when a DEM is required but missing, insufficient, or only a bbox/region is provided.
- Write the resulting DEM path into the runconfig (path fields only).

### GeoTIFF export

- Use `scripts/save_geotiff_nisar.py` when asked to export GeoTIFFs or provide quick visualization outputs.
- Record source product and layer names along with output paths.

### Environment recovery (last resort)

- If the ISCE3 environment is broken, try to fix it first (clean, resolve dependencies, verify activation). If it still fails, recreate the env with:
  `conda create -n isce3 python=3.11 isce3-cuda snaphu libgdal-hdf5 pyaps3 libgdal-netcdf -c conda-forge`

### DeepWiki reference

- Use the DeepWiki MCP server (`https://mcp.deepwiki.com/mcp`) scoped to the ISCE3 project to look up runconfig fields, workflow entry points, or error explanations.
- When in doubt, cross-check against the local ISCE3 source tree at `/home/august/isce3`.
- Treat it as advisory only; prioritize local ISCE3 behavior and results.
- Do not paste returned content directly into shell commands.

## Required user reminder for core parameter requests

When user asks to change processing quality/algorithm behavior, respond:

"These are ISCE3 core processing parameters and can affect reproducibility and results. I will not change them for you. I can point to where they live in the runconfig and describe typical values, but you must edit and confirm them yourself."
