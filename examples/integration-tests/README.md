# Integration Test Examples

Four end-to-end integration tests covering all supported engines, workflows, and sensor types.
Each test ran in a fully isolated Claude Code session (AUTO mode, no human confirmation).

## Test Matrix

| Test | Engine | Workflow | Sensor | Skill Sequence | Duration |
|------|--------|----------|--------|----------------|----------|
| E1 | ISCE3 | insar | NISAR RSLC | insar-agent → d-insar-isce3 | ~2 min |
| E2 | ISCE2 | tops | Sentinel-1 | insar-agent → data-prep-sentinel → d-insar-isce2 | ~45 min |
| E3 | ISCE3 | stack | NISAR RSLC | insar-agent → stack-insar-isce3 → mintpy | ~35 min |
| E4 | ISCE2 | stack | Sentinel-1 | insar-agent → data-prep-sentinel → stack-insar-isce2 → mintpy | ~2.5 hr |

## Launch Prompts

Tests were launched via the workspace harness script, which starts an isolated Claude Code session
in tmux with `--dangerously-skip-permissions` (integration test environment only).

```bash
# E1 — NISAR / ISCE3 / D-InSAR single pair
bash scripts/launch-insar-claude-tmux.sh \
  --task-id d-insar-isce3 \
  --prompt '/insar-agent-plugin:insar-agent 处理 E1 任务'

# E2 — Sentinel-1 / ISCE2 / D-InSAR single pair
bash scripts/launch-insar-claude-tmux.sh \
  --task-id d-insar-isce2 \
  --prompt '/insar-agent-plugin:insar-agent 处理 E2 任务'

# E3 — NISAR / ISCE3 / Stack-InSAR + MintPy
bash scripts/launch-insar-claude-tmux.sh \
  --task-id stack-insar-isce3 \
  --prompt '/insar-agent-plugin:insar-agent 处理 E3 任务'

# E4 — Sentinel-1 / ISCE2 / Stack-InSAR + MintPy
bash scripts/launch-insar-claude-tmux.sh \
  --task-id stack-insar-isce2 \
  --prompt '/insar-agent-plugin:insar-agent 处理 E4 任务'
```

The `/insar-agent` slash command triggers the insar-agent skill, which:

1. Reads `insar://workflow-guide` MCP resource to load routing constraints
2. Calls `insar_check_env` to verify conda environments (isce3gpu, isce2, mintpy)
3. Loads the task-appropriate workflow skill
4. Runs the full workflow in AUTO mode — param-advisor, batch launch, polling, MintPy

## Results

| Test | run_id | Key Products | Stack Exit |
|------|--------|-------------|------------|
| E1 | `d-insar-isce3_20260524T152121Z` | GUNW.h5 (11 MB), 48 browse GeoTIFFs | 0 |
| E2 | `d-insar-isce2_20260524T153207Z` | filt_topophase.unw.geo (129 MB), cor.geo (129 MB), los.rdr.geo (129 MB) | 0 |
| E3 | `stack-insar-isce3_20260524T162918z` | 6+15 GUNW.h5 (stack+network), velocity.h5 (43 MB), timeseries.h5 (61 MB) | 0 |
| E4 | `stack-insar-isce2_20260524T181041Z` | 22× filt_fine.unw (~53 MB each), velocity.h5 (133 MB), timeseries.h5 (213 MB) | 0 |

## Key Observations

### E1 — Param-advisor automatically tuned multilook and ionosphere

Default NISAR ISCE3 processing params were replaced by the param-advisor subagent (~5m39s, 17 tool uses):

| Parameter | Default | Applied |
|-----------|---------|---------|
| `azimuth_looks` | 11 | 7 |
| `range_looks` | 11 | 7 |
| `ionosphere_phase_correction.enabled` | false | true |

The 7×7 multilook is appropriate for the NISAR L-band cropped RSLC scene geometry.
Ionosphere correction was enabled because L-band is dispersive at the spatial scale of this dataset.
All 3 changes were accepted automatically in AUTO mode.

### E2 — Three runs: ESD failure → SNAPHU NaN → ICU success

| Run | Config | Failure | Resolution |
|-----|--------|---------|------------|
| Run 1 | `do_esd=true`, `snaphu` | ESD: "Coherence threshold too strict. No points left for reliable ESD estimate." | Disabled ESD, resubmitted |
| Run 2 | `do_esd=false`, `snaphu` | SNAPHU: "NaN or infinity found in input float data" (phase noise from skipped ESD) | Switched to ICU, raised `filter_strength 0.5→0.8` |
| Run 3 | `do_esd=false`, `icu`, `filter_strength=0.8` | — | Success (~30 min) |

Afar Depression has low coherence in burst overlap zones, making ESD unreliable.
ICU unwrapper is more robust to noisy input than SNAPHU for this region.
The agent self-diagnosed all three failures and adapted without developer intervention.

Final params applied (see `configs/e2-topsapp.xml`):
```
swaths: [1, 2]   do_esd: false   range_looks: 7   azimuth_looks: 3
filter_strength: 0.8   unwrap_method: icu
```

### E3 — Pre-tuned base runconfig reused; dual-batch parallel execution

A `base_runconfig_param_tuned.yaml` already existed from a prior param-advisor run.
The stack-insar-isce3 skill detected it and skipped param-advisor automatically.

Two batches ran in parallel:
- **Stack** (Option A): 6 pairs (single reference 20251029), 13.3 min, exit 0
- **Network** (Option B): 15 pairs (tbase ≤36d), 20.3 min, exit 0

MintPy ran on the 15-pair network, producing velocity.h5 (43 MB) and timeseries.h5 (61 MB) in ~4 min.

### E4 — ISCE2 DEM format compatibility: GDAL Copernicus causes infinite loop

Three projects were created before the root cause was identified:

| Version | DEM | `num_proc` | Outcome |
|---------|-----|-----------|---------|
| V1 | Copernicus 30m (GDAL/WGS84) | 8 | topo infinite loop, 48 min, 99.8% CPU, zero output |
| V2 | Copernicus 30m (GDAL/WGS84) | 1 | Same infinite loop — not a parallelism bug |
| V3 | ISCE2-native SRTM (`backend="isce2"`, `dem_type="version3"`) | default | Log grew 91→13,117 lines in 15 min; 16/16 steps, 22/22 SNAPHU pairs → success |

**Root cause**: ISCE2 `topozero` zerodop polynomial fitting fails silently on GDAL-format
geographic-coordinate DEMs, entering a busy-loop with "Polynomial Order: 0" output.

**Fix**: Use `insar_download_dem(backend="isce2", dem_type="version3")` for all ISCE2 workflows.
This downloads SRTM tiles via ISCE2's native fetcher and stitches them into a properly projected DEM.

After the DEM fix, stack processing ran ~2h14min (16 run files, 22 SNAPHU pairs).
MintPy completed in ~5m25s.

## Files in This Directory

```
integration-tests/
  README.md                          ← this file
  transcripts/
    e1-nisar-isce3-dinsar.txt        ← full Claude Code terminal output, E1
    e2-sentinel-isce2-dinsar.txt     ← full Claude Code terminal output, E2
    e3-nisar-isce3-stack.txt         ← full Claude Code terminal output, E3
    e4-sentinel-isce2-stack.txt      ← full Claude Code terminal output, E4
  configs/
    e2-topsapp.xml                   ← ISCE2 topsApp config (final tuned, E2 run 3)
```

Each transcript contains:
- The slash command prompt used to start the run
- All tool calls (Skill, MCP, Bash) with outputs
- Mid-run progress notes and status tables
- Final structured processing summary (流程记录 / 成功结果 / 关键产物)

Note: Absolute paths in configs are environment-specific and must be updated when reusing.
