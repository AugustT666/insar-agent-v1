# Exp-1 — NISAR ISCE3 D-InSAR Single Pair

Autonomous regression run. Do not ask questions.

## Task

Process a NISAR L-band RSLC pair into a GUNW interferogram using ISCE3 D-InSAR.

Use the `d-insar-isce3` skill to execute the full workflow.

## Data

- Reference RSLC: `/mnt/HDD2T/August/third-agent-test/nisar/RSLC/NISAR_L1_PR_RSLC_005_172_A_008_2005_DHDH_A_20251122T024618_20251122T024652_X05009_N_F_J_001_cropped.h5`
- Secondary RSLC: `/mnt/HDD2T/August/third-agent-test/nisar/RSLC/NISAR_L1_PR_RSLC_006_172_A_008_2005_DHDH_A_20251204T024618_20251204T024653_X05009_N_F_J_001_cropped.h5`
- DEM: `/mnt/HDD2T/August/third-agent-test/common/dem/dem.tif`
- Base runconfig template: `/mnt/HDD2T/August/NISAR_test/reference_yaml_script/insar_nisar.yaml`
- Preferred ISCE3 conda env: `isce3` (fallback: `isce3gpu`)
- Workspace root: `./workspace`

## Policy

- Skip `param-advisor` — use default runconfig parameters for this autonomous regression.
- Do not run conda/python/ISCE commands directly; use `insar_*` MCP tools only.

## Success criteria

`insar_get_job` reports `completed`. Report job id, log path, output path(s), and GeoTIFF path(s).
