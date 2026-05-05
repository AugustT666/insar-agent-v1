# Exp-4 — Sentinel-1 ISCE2 Time-Series Stack + MintPy

Autonomous regression run. Do not ask questions.

## Task

Prepare a Sentinel-1 SAFE stack with ISCE2 topsStack, run the stack workflow, then run MintPy for time-series displacement analysis.

Use the `stack-insar-isce2` skill for the stack workflow, then use the `mintpy` skill for time-series analysis.

## Data

- SAFE stack directory: `/mnt/HDD2T/August/third-agent-test/sentinel/safe/s1a_desc_rel079`
- Orbit directory: `/mnt/HDD2T/August/inasr-agent-test/temp/general/orbits`
- DEM: `/mnt/HDD2T/August/third-agent-test/common/dem/dem.tif`
- ISCE2 conda env: `isce2`
- MintPy conda env: `mintpy` (separate from ISCE2)
- Stack output directory: `./outputs/sentinel-stack`
- MintPy work directory: `./outputs/sentinel-mintpy`

## Policy

- Use SAFE scenes already in the directory — do not download new scenes.
- Skip `param-advisor` — use default parameters for this autonomous regression.
- Do not start MintPy until stack job reports completed/done.
- Do not run conda/python/ISCE/MintPy commands directly; use `insar_*` MCP tools only.

## Success criteria

Stack job `completed` AND MintPy job `completed`. Report all job ids, log paths, and displacement/baseline product paths.
