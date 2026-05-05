# Exp-2 — NISAR ISCE3 Time-Series Network + MintPy

Autonomous regression run. Do not ask questions.

## Task

Prepare a short-temporal-baseline NISAR RSLC network, run ISCE3 batch interferograms, then run MintPy time-series analysis.

Use the `stack-insar-isce3` skill for the stack/network/batch workflow, then use the `mintpy` skill for time-series analysis.

## Data

- RSLC directory: `/mnt/HDD2T/August/third-agent-test/nisar/RSLC` (use all `.h5` files, ignore `QA_STATS`)
- DEM: `/mnt/HDD2T/August/third-agent-test/common/dem/dem.tif`
- Base runconfig template: `/mnt/HDD2T/August/NISAR_test/reference_yaml_script/insar_nisar.yaml`
- Preferred ISCE3 conda env: `isce3` (fallback: `isce3gpu`)
- MintPy conda env: `mintpy` (must be separate from ISCE3)
- Batch output directory: `./outputs/nisar-network`
- MintPy work directory: `./outputs/nisar-mintpy`
- Network mode: short-temporal-baseline
- Max parallel jobs: `2`

## Policy

- Skip `param-advisor` — use default parameters for this autonomous regression.
- Do not start MintPy until batch job reports completed/done.
- Do not run conda/python/ISCE/MintPy commands directly; use `insar_*` MCP tools only.

## Success criteria

Batch job `completed` with zero failures AND MintPy job `completed`. Report all job ids, log paths, and output directories.
