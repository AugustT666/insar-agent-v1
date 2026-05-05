# Exp-3 — Sentinel-1 ISCE2 D-InSAR Single Pair

Autonomous regression run. Do not ask questions.

## Task

Process a Sentinel-1 C-band single pair into a D-InSAR interferogram using ISCE2 topsApp.

Use the `d-insar-isce2` skill to execute the full workflow.

## Data

- Reference SAFE: `/mnt/HDD2T/August/third-agent-test/sentinel/safe/s1a_asc_rel014/S1A_IW_SLC__1SDV_20260205T152727_20260205T152754_063086_07EAE3_929A.SAFE`
- Secondary SAFE: `/mnt/HDD2T/August/third-agent-test/sentinel/safe/s1a_asc_rel014/S1A_IW_SLC__1SDV_20260217T152727_20260217T152754_063261_07F169_2412.SAFE`
- Orbit directory: `/mnt/HDD2T/August/inasr-agent-test/temp/general/orbits`
- DEM: `/mnt/HDD2T/August/third-agent-test/common/dem/dem.tif`
- ISCE2 conda env: `isce2`
- Workspace root: `./workspace`

## Special constraint

Set `do_esd=False` — this pair has only one common burst per swath, no burst-overlap points for ESD.

## Success criteria

`insar_get_job` reports `completed`. Report job id, log path, and output directory.
