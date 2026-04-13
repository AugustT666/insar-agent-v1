# End-to-End Audit Guide: Sentinel-1/ISCE2 D-InSAR Workflows

**Date**: April 13, 2026  
**Scope**: ISCE2 engine (`tops` and `stack` workflows) for Sentinel-1 processing  
**Status**: Implementation Complete; Real-Data Testing Gaps Identified

---

## Quick Navigation

- **Full Research**: `/home/august/insar-agent/docs/RESEARCH-ISCE2-SENTINEL-20260413.md`
- **Findings Summary**: `/home/august/insar-agent/docs/FINDINGS-SUMMARY-20260413.txt`
- **This Guide**: `/home/august/insar-agent/docs/AUDIT-GUIDE-ISCE2-SENTINEL.md`

---

## Audit Checklist

### Pre-Execution (Unit-Level Validation)

- [ ] **Documentation**
  - [ ] Verify `/home/august/insar-agent/skills/d-insar-isce2/SKILL.md` covers 8-step workflow
  - [ ] Verify `/home/august/insar-agent/skills/data-prep-sentinel/SKILL.md` exists and is referenced
  - [ ] Check `/home/august/insar-agent/docs/agent-guide.md` hard constraints (lines 8-29)
  
- [ ] **Source Code Structure**
  - [ ] Verify `/home/august/insar-agent/src/insar_agent/engines/isce2/` directory with all 6 modules
  - [ ] Verify `SUPPORTED_WORKFLOWS` in `defaults.py` lists `tops` and `stack`
  - [ ] Verify `REQUIRED_PARAM_FIELDS` for each workflow

- [ ] **Unit Tests**
  - [ ] Run: `pytest tests/unit/test_isce2_sentinel_prep.py -v`
  - [ ] Verify all 10+ tests PASS
  - [ ] Check coverage: SAFE/ZIP, metadata parsing, grouping, DEM, orbits

### Execution (Integration-Level Validation)

- [ ] **Configuration Validation**
  - [ ] Test: `insar_create_project(engine="isce2", workflow="tops", ...)`
  - [ ] Test: `insar_set_processing_param(project_id, key="reference_safe", ...)`
  - [ ] Verify: `validate_params()` returns empty list for valid config
  - [ ] Verify: Invalid paths return error codes

- [ ] **Pre-Run Checks**
  - [ ] Test: `insar_validate_runconfig(project_id)` → `valid: True`
  - [ ] Test: `insar_export_runconfig(project_id)` → produces parseable YAML
  - [ ] Test: `insar_run_workflow(project_id, dry_run=True)` → command contains env + workflow

- [ ] **Real-Data Testing** (Requires Sentinel-1 SAFE files)
  - [ ] [ ] Setup test Sentinel-1 scenes (ascending, same orbit, 12-day baseline)
  - [ ] [ ] Create real-data integration test file (e.g., `tests/integration/test_isce2_sentinel_real.py`)
  - [ ] [ ] Run: `pytest tests/integration/test_isce2_sentinel_real.py -v -s -m real_data --timeout=3600`
  - [ ] [ ] Verify outputs: `merged/filt_topophase.unw.geo`, `merged/phsig.cor.geo`
  - [ ] [ ] Check log: No FATAL/ERROR in `.insar_logs/` + ISCE2 output

### Output Validation

- [ ] **File Presence**
  - [ ] TOPS: `merged/filt_topophase.unw.geo` (unwrapped phase)
  - [ ] TOPS: `merged/phsig.cor.geo` (coherence)
  - [ ] TOPS: `merged/filt_topophase.flat.geo` (flat-earth wrapped phase)
  - [ ] Stack: Interferogram network directory structure

- [ ] **Data Quality**
  - [ ] Coherence values in `[0, 1]` range
  - [ ] Wrapped phase in `[-π, π]` range
  - [ ] Unwrapped phase continuous (no unrealistic jumps)
  - [ ] DEM crop matches bbox (if specified)
  - [ ] Metadata timestamps match input SAFE files

- [ ] **Log Inspection**
  - [ ] No FATAL/ERROR lines in `.insar_logs/*`
  - [ ] Processing milestones logged: coregistration → interferogram → unwrap → geocode
  - [ ] Return code = 0 for main subprocess

---

## Pass Criteria Summary

### Unit Tests
✓ All path/bbox/swaths validation passes  
✓ XML generation produces well-formed output  
✓ Manifest parsing extracts correct metadata  
✓ Skill routing text matches expectations  

### Integration (Pre-Execution)
✓ Runconfig validates without errors  
✓ YAML export produces parseable file  
✓ Dry-run command references conda env + workflow  

### Integration (Full Execution)
✓ Job returns `job_id` + `log_path` + `pid > 0`  
✓ Status polling: `"pending"` → `"running"` → `"done"`  
✓ Reaches `"done"` within timeout (1h default)  
✓ Output files exist and are non-empty  
✓ Log inspection: no fatal errors  
✓ Return code = 0  

### Data Quality (Advanced)
✓ Coherence/phase values in valid ranges  
✓ Unwrapped phase continuous  
✓ Timestamps match inputs  

---

## Fail Criteria Summary

### Unit Tests
✗ Required field missing or null  
✗ Path does not exist  
✗ Invalid bbox/swaths range  
✗ XML generation raises exception  

### Integration (Pre-Execution)
✗ Validation returns errors  
✗ YAML export unparseable  
✗ Dry-run missing environment/workflow  

### Integration (Full Execution)
✗ Job submission returns error (missing env, invalid config)  
✗ Status polling returns `"failed"` before timeout  
✗ Timeout reached without completion (>1h)  
✗ Output files missing or zero-size  
✗ Log contains FATAL/ERROR  
✗ Return code ≠ 0  

### Data Quality (Advanced)
✗ NaN/Inf dominant in coherence  
✗ Phase values outside valid ranges  
✗ Large coherence dropouts in baseline areas  
✗ DEM crop region ≠ requested bbox  

---

## Key Hard Constraints

1. **Same relative orbit required**: Reference & secondary from same track
2. **No mixed passes**: Do NOT mix ascending/descending
3. **Temporal baseline**: 6–48 days (S-1 repeat = 12 days)
4. **Orbit files**: Must exist in `orbit_dir`; ISCE2 auto-downloads if online
5. **Environment**: Always `conda run -n isce2`; never bare `topsApp.py`
6. **XML editing**: Use `insar_set_processing_param`; never manually edit
7. **DEM quality**: Reasonable resolution (Copernicus 30m; not 1° SRTM)

---

## Quick Commands

```bash
# Unit tests (no real data needed)
pytest tests/unit/test_isce2_sentinel_prep.py -v

# Real-data integration (Sentinel-1, requires SAFE files)
pytest tests/integration/test_isce2_sentinel_real.py -v -s -m real_data --timeout=3600

# Dry-run validation
python -c "
from insar_agent.mcp.server import insar_create_project, insar_set_processing_param, insar_run_workflow
pid = insar_create_project(engine='isce2', workflow='tops', workspace_root='/tmp/test', name='test', conda_env='isce2')['project_id']
insar_set_processing_param(pid, key='reference_safe', value='/path/to/ref.SAFE', justification='test')
insar_set_processing_param(pid, key='secondary_safe', value='/path/to/sec.SAFE', justification='test')
insar_set_processing_param(pid, key='orbit_dir', value='/path/to/orbits', justification='test')
insar_set_processing_param(pid, key='dem_file', value='/path/to/dem.tif', justification='test')
result = insar_run_workflow(pid, dry_run=True)
print('Dry-run command:', ' '.join(result['command']))
"
```

---

## Implementation Gaps (As of April 13, 2026)

### Critical for Audit Completion
- **Real-data integration test for Sentinel-1**: None exists yet
  - Current `test_real_dinsar.py` is NISAR-specific (ISCE3GPU)
  - Need: `test_isce2_sentinel_real.py` with Sentinel-1 SAFE files
  - Estimated effort: ~200 lines (mirror NISAR pattern)

### Secondary Improvements
- **Error recovery**: No auto-retry for transient failures (network timeouts)
- **Stack workflow maturity**: Defined but end-to-end validation primarily via ISCE3 path
- **Parameter advisory**: Path B (time-series) needs conservative tuning guidance

---

## File Manifest

### Documentation
- `RESEARCH-ISCE2-SENTINEL-20260413.md` — Comprehensive research (16KB)
- `FINDINGS-SUMMARY-20260413.txt` — Concise findings (16KB)
- `AUDIT-GUIDE-ISCE2-SENTINEL.md` — This file

### Implementation
- `src/insar_agent/engines/isce2/adapter.py` — Adapter
- `src/insar_agent/engines/isce2/defaults.py` — Workflows & parameters
- `src/insar_agent/engines/isce2/validator.py` — Validation logic
- `src/insar_agent/engines/isce2/runner.py` — XML generation & commands
- `src/insar_agent/engines/isce2/sentinel_prep.py` — Data prep
- `src/insar_agent/engines/isce2/stack.py` — Stack command building

### Skills (User Guidance)
- `skills/d-insar-isce2/SKILL.md` — D-InSAR workflow
- `skills/stack-insar-isce2/SKILL.md` — Time-series workflow
- `skills/data-prep-sentinel/SKILL.md` — Data preparation

### Tests
- `tests/unit/test_isce2_sentinel_prep.py` — 446 lines, full unit coverage
- `tests/integration/test_real_dinsar.py` — NISAR real-data (no ISCE2 yet)

---

## Recommendations for Next Steps

1. **Create Sentinel-1 real-data test**: 
   - Setup 2 ascending Sentinel-1 SAFE files (12-day baseline)
   - Write `tests/integration/test_isce2_sentinel_real.py` (mirror NISAR pattern)
   - Run: `pytest -v -s -m real_data --timeout=3600`

2. **Add error recovery**:
   - Implement auto-retry for transient failures (orbit download timeouts)
   - Consider exponential backoff + max retries (3x default)

3. **Enhance parameter advisory for stacks**:
   - Document conservative baseline/filter/looks defaults for time-series
   - Add warnings when parameters diverge from ISCE3 Path B norms

4. **Documentation improvements**:
   - Add troubleshooting section to `d-insar-isce2/SKILL.md`
   - Document expected runtime (30–120 minutes for typical scenes)

---

## Contact & Context

**Research Prepared By**: Claude Code (April 13, 2026)  
**Reviewed In**: `/home/august/insar-agent` repository  
**Test Command**: `pytest tests/unit -q` (default, no real-data)  

**Related Documents**:
- `docs/developer-documents/dev-plan.md` (milestone history)
- `docs/architecture.md` (system layer design)
- `CLAUDE.md` (developer collaboration guide)

---

**END OF AUDIT GUIDE**
