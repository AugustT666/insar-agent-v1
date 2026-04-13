# Sentinel-1/ISCE2 D-InSAR Workflow Research Summary

## Current Status (April 2026)

**ISCE2 Support**: ✓ IMPLEMENTED (engines/isce2/)
- Two workflows: `tops` (single pair D-InSAR) and `stack` (time-series)
- Full MCP tool exposure via insar_agent
- Skills-based guidance for user-facing workflows
- Unit + integration test structure in place

---

## Key Documentation Files

### User-Facing Guidance
| File | Purpose |
|------|---------|
| `/home/august/insar-agent/skills/d-insar-isce2/SKILL.md` | Step-by-step D-InSAR pair workflow (Sentinel-1 → TOPS → interferogram) |
| `/home/august/insar-agent/skills/stack-insar-isce2/SKILL.md` | Time-series stack workflow (Sentinel-1 → stackSentinel → MintPy) |
| `/home/august/insar-agent/skills/data-prep-sentinel/SKILL.md` | Sentinel data preparation (SAFE/ZIP organization, DEM, orbits) |
| `/home/august/insar-agent/docs/agent-guide.md` | Hard constraints and MCP tool contracts |
| `/home/august/insar-agent/CLAUDE.md` | Developer collaboration guide |

### Architecture & Implementation
| File | Purpose |
|------|---------|
| `/home/august/insar-agent/docs/architecture.md` | System layer design; MCP tool principles |
| `/home/august/insar-agent/docs/developer-documents/dev-plan.md` | Milestone history; current impl status |

---

## ISCE2 Engine Implementation

### Source Code Structure
```
src/insar_agent/engines/isce2/
  ├── adapter.py                    # ISCE2Adapter class listing workflows
  ├── defaults.py                   # SUPPORTED_WORKFLOWS, REQUIRED_PARAM_FIELDS
  ├── validator.py                  # validate_params() for path/bbox/swaths checks
  ├── runner.py                     # build_topsapp_xml(), build_workflow_command()
  ├── sentinel_prep.py              # prepare_sentinel_data(), SCENE_ID_RE patterns
  ├── stack.py                      # build_stack_command() for stackSentinel.py
  └── assets/
      └── processing_params_tops.yaml   # Parameter registry (required, optional, risk_level)
```

### Supported Workflows

#### 1. TOPS (Single Pair D-InSAR)
**File**: `/home/august/insar-agent/src/insar_agent/engines/isce2/defaults.py`

```yaml
SUPPORTED_WORKFLOWS[0]:
  engine: isce2
  workflow: tops
  supports_gpu: False
  description: Sentinel-1 TOPS D-InSAR single pair (topsApp.py)

REQUIRED_PARAM_FIELDS["tops"]:
  - reference_safe         # Path to reference SAFE or ZIP
  - secondary_safe         # Path to secondary SAFE or ZIP
  - orbit_dir              # POEORB orbit files
  - dem_file               # DEM GeoTIFF
```

**Optional Parameters**:
```
swaths: [1,2,3] (default)          # Process all 3 IW subswaths
polarization: "vv" (default)       # "vv" or "vh"
range_looks: 20, azimuth_looks: 4  # Multilook factors
filter_strength: 0.5               # Goldstein filter [0=off, 1=max]
do_esd: True                       # Spectral diversity coregistration
esd_coherence_threshold: 0.7       # ESD coherence floor
unwrap_method: "snaphu" (default)  # or "icu"
do_unwrap: True                    # or False for wrapped phase only
bbox: None (default: full swath)   # [S, N, W, E] to crop
```

#### 2. STACK (Time-Series)
**File**: `/home/august/insar-agent/src/insar_agent/engines/isce2/defaults.py`

```yaml
SUPPORTED_WORKFLOWS[1]:
  engine: isce2
  workflow: stack
  supports_gpu: False
  description: Sentinel-1 TOPS time-series stack (stackSentinel.py)

REQUIRED_PARAM_FIELDS["stack"]:
  - slc_dir                # Directory with grouped SAFE files (one orbit track)
  - orbit_dir              # POEORB files
  - dem_file               # DEM GeoTIFF
```

**Optional Parameters**:
```
num_connections: 3         # Interferogram pairs per scene
coregistration: "NESD"     # or "geometry" if ESD fails
workflow: "interferogram"  # Core pipeline type
range_looks: 20, azimuth_looks: 4
filter_strength: 0.5
unwrap_method: "snaphu"
num_proc: 1                # Parallel processing count
use_gpu: False
```

---

## Workflow Execution

### XML Configuration Generation
**File**: `/home/august/insar-agent/src/insar_agent/engines/isce2/runner.py`

```python
def build_topsapp_xml(params: dict) -> str:
    """Generate topsApp.xml from project parameters."""
    # Creates XML with component hierarchy:
    # <topsApp>
    #   <component name="topsinsar">
    #     <component name="reference"> ... </component>
    #     <component name="secondary"> ... </component>
    #     <component name="dem"> ... </component>
    #     ... additional components ...
    #   </component>
    # </topsApp>
```

### Command Execution
**File**: `/home/august/insar-agent/src/insar_agent/engines/isce2/runner.py`

```python
def build_workflow_command(
    workflow: str,
    config_path: str,
    conda_env: str | None = None,
) -> list[str]:
    """Build command for conda run -n isce2 python -m isce2.workflows.topsApp"""
```

**Actual invocation**:
```bash
conda run -n isce2 python -m isce2.workflows.topsApp /path/to/topsApp.xml
# For stack:
conda run -n isce2 python -m isce2.workflows.stackSentinel /path/to/stackApp.xml
```

---

## Validation & Error Handling

**File**: `/home/august/insar-agent/src/insar_agent/engines/isce2/validator.py`

### `validate_params(params: dict, workflow: str) -> list[str]`

Checks performed:
1. **Required fields presence**: All fields in `REQUIRED_PARAM_FIELDS[workflow]` must exist
2. **Path existence**: 
   - `reference_safe`, `secondary_safe`, `dem_file` must exist as files
   - `orbit_dir`, `slc_dir` must exist as directories
3. **Bbox validation**: If provided, must be `[south < north, west < east]`
4. **Swaths validation**: Values must be in `{1, 2, 3}`

**Error codes returned**:
```
"Required field '{field}' is not set."
"Path does not exist: {field}={value}"
"Directory does not exist: {field}={value}"
"bbox must be a list of 4 values: [south, north, west, east]"
"bbox: south < north constraint violated"
"swaths must be a non-empty list, e.g. [1, 2, 3]"
"swaths values must be 1, 2, or 3"
```

---

## Sentinel Data Preparation

**File**: `/home/august/insar-agent/src/insar_agent/engines/isce2/sentinel_prep.py`

### `prepare_sentinel_data()`
Entry point for organizing raw SAFE/ZIP/burst inputs:

```python
def prepare_sentinel_data(
    project_root: str,
    source_paths: list[str] | None = None,
    burst_manifest: str | None = None,
    dem_path: str | None = None,
    bbox: list[float] | None = None,
    download_dem: bool = False,
    dem_output_path: str | None = None,
    dem_backend: str = "general",
    download_orbits: bool = False,
    orbit_dir: str | None = None,
    orbit_username: str | None = None,
    orbit_password: str | None = None,
) -> dict
```

**Output structure**:
```python
{
    "grouped_safe_paths": {
        "s1a_asc_rel014": ["/project/safe/s1a_asc_rel014/S1A_...SAFE"],
        "s1c_desc_rel079": ["/project/safe/s1c_desc_rel079/S1C_...SAFE"],
    },
    "dem_path": "/project/dem/cop30.tif",
    "orbit_dir": "/project/orbits",
    "orbit_downloaded_count": 42,
    "orbit_failed": [],
    "prep_log_path": "/project/.insar_logs/prep_...",
    "orbit_log_path": "/project/.insar_logs/orbit_...",
}
```

### Scene ID Recognition
**Pattern**: `SCENE_ID_RE` from `sentinel_prep.py`
```
S1A_IW_SLC__1SDV_YYYYMMDDTHHMMSS_YYYYMMDDTHHMMSS_XXXXXX_YYYYYY_ZZZZ.SAFE
├─ S1A = Satellite (S1A/S1B/S1C/S1D)
├─ IW  = Instrument Mode (IW = Interferometric Wide)
├─ DHDH = Polarization (VV/VH)
└─ Embedded: absolute orbit, relative orbit, pass direction
```

---

## Testing Strategy

### Unit Tests
**File**: `/home/august/insar-agent/tests/unit/test_isce2_sentinel_prep.py`

Current coverage (446 lines):
- SAFE directory/ZIP creation with realistic manifest.safe XML
- Scene metadata parsing (`insar_describe_s1`)
- Grouped SAFE path organization
- Burst scene synthesis (from manifest)
- Real family name normalization (S1 vs SENTINEL-1)
- DEM download with isce2 backend + retry logic
- Scene download + plugin log placement
- Orbit credential validation (fail-fast on missing ~/.netrc)
- Skill routing text verification

**Key helpers**:
```python
make_fake_safe_dir(root, scene_id, pass_direction, relative_orbit) -> Path
make_fake_safe_zip(root, scene_id, pass_direction, relative_orbit) -> Path
make_fake_burst_scene(root, scene_id, pass_direction, relative_orbit) -> Path
```

### Integration Tests (Real Data)
**File**: `/home/august/insar-agent/tests/integration/test_real_dinsar.py`

**Data location**:
```
/home/august/NAS/NISAR_wangshuai_data/
├── NISAR_L1_PR_RSLC_005_172_A_008_2005_DHDH_A_20251122T024618...h5  (REF)
├── NISAR_L1_PR_RSLC_006_172_A_008_2005_DHDH_A_20251204T024618...h5  (SEC)
├── dem.wgs84
└── insar_out2/ → GUNW_product.h5
```

**Test pattern**:
```python
@pytest.mark.real_data
@pytest.mark.skipif(not NAS_AVAILABLE, reason="...")
def test_full_dinsar_produces_gunw(dinsar_project, tmp_path):
    # 1. Setup project with NAS paths
    # 2. Validate runconfig
    # 3. Export YAML
    # 4. Run workflow (conda run -n isce3gpu ...)
    # 5. Poll with insar_get_job_status (30s intervals, 1h timeout)
    # 6. Verify output: GUNW_product.h5 exists & non-empty
```

**Run command**:
```bash
pytest tests/integration/test_real_dinsar.py -v -s -m real_data --timeout=3600
```

### Pytest Configuration
**File**: `/home/august/insar-agent/pyproject.toml`

```toml
[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
addopts = "-m 'not real_data'"  # Real-data excluded by default
markers = [
  "real_data: tests that require mounted NAS data or launch real processing workflows",
]
```

---

## Pass/Fail Audit Criteria

### Unit Tests (Automated)
✓ **PASS** if:
- All path existence checks pass (reference_safe, secondary_safe, orbit_dir, dem_file exist)
- All parameter ranges valid (swaths ∈ {1,2,3}, bbox valid, lists non-empty)
- XML generation produces well-formed topsApp.xml
- Sentinel manifest parsing extracts correct metadata (orbit, pass, polarization)
- Skill text matches routing expectations

✗ **FAIL** if:
- Required field missing or null
- Path does not exist (returns `path_not_found`)
- Invalid bbox format or range (returns `invalid_input`)
- XML generation raises exception
- Manifest parsing returns None for critical fields

### Integration Tests (Real Data)

#### Pre-Execution Checks (Unit-level on real files)
✓ **PASS** if:
- `insar_validate_runconfig(project_id)` returns `valid: True`
- `insar_export_runconfig()` produces parseable YAML
- Dry-run command contains conda env name + workflow module name
- File stat confirms DEM, RSLC, orbits readable

✗ **FAIL** if:
- Validation returns errors (missing paths, invalid values)
- YAML export produces unparseable file
- Dry-run command missing environment or workflow module

#### Full Workflow Execution (Real Processing)
✓ **PASS** if:
- **Job submission**: `insar_run_workflow()` returns `job_id` + `log_path` + `pid > 0`
- **Polling**: `insar_get_job(job_id, project_id)` returns status in `["pending", "running", "done"]`
- **Completion**: Status reaches `"done"` within timeout (1h default)
- **Outputs exist**: 
  - For TOPS: `merged/filt_topophase.unw.geo`, `merged/phsig.cor.geo` exist and non-empty
  - For STACK: Interferogram network + unwrapped stack in output directory
- **Log inspection**:
  - No fatal errors in `.insar_logs/` + ISCE2 output
  - Processing milestones logged (coregistration, interferogram, unwrap, geocode)

✗ **FAIL** if:
- Job submission returns `error` key (e.g., missing conda env, invalid runconfig)
- Status polling returns `"failed"` before timeout
- Timeout reached without completion
- Output files missing or zero-size
- Log contains FATAL/ERROR (non-recoverable exception in topsApp/stackSentinel)
- Return code != 0 for subprocess call

#### Coherence & Physical Validity Checks (Advanced Audit)
✓ **PASS** if:
- Coherence map values in `[0, 1]` range
- Wrapped phase in `[-π, π]` range
- Unwrapped phase continuous (no unrealistic jumps)
- DEM crop matches bbox (if bbox was set)
- Timestamp metadata in output matches input SAFE files

✗ **FAIL** if:
- NaN/Inf pixels dominate coherence
- Phase values outside valid ranges
- Large coherence dropouts in low-baseline areas
- DEM crop region does not match requested bbox

---

## Workflow Constraints (Hard Rules)

### From `/home/august/insar-agent/docs/agent-guide.md`
1. ✓ Reference & secondary must be from **same relative orbit** (same track)
2. ✓ Do NOT mix ascending/descending passes (D-InSAR requires consistent geometry)
3. ✓ Temporal baseline: typically 6–48 days (S-1 repeat cycle = 12 days)
4. ✓ Orbit files required in `orbit_dir`; ISCE2 auto-downloads if internet available
5. ✓ Processing always runs inside `conda run -n isce2` (never bare topsApp.py)
6. ✓ Do not manually edit topsApp.xml; use `insar_set_processing_param` API
7. ✓ DEM resolution must be reasonable (e.g., Copernicus 30m, not 1° SRTM)

### From `/home/august/insar-agent/skills/d-insar-isce2/SKILL.md`
- Always invoke `data-prep-sentinel` first if inputs are raw SAFE/ZIP
- Metadata checks via `insar_describe_s1` are **advisory**, not blocking
- ESD may fail in low-coherence areas; fallback to `do_esd: False` if needed
- Swath selection can reduce runtime: `swaths: [2]` for speed vs `swaths: [1,2,3]` for full processing

---

## Command Reference

### Test Execution
```bash
# Default (excludes real_data)
pytest tests/unit -q

# Real-data integration (requires NAS mounted)
pytest tests/integration/test_real_dinsar.py -v -s -m real_data --timeout=3600

# Specific unit test
pytest tests/unit/test_isce2_sentinel_prep.py::test_prepare_sentinel_data_organizes_safe_inputs -v

# All tests including real_data
pytest tests -v -m real_data
```

### MCP Tool Commands
```python
# Project setup
insar_create_project(engine="isce2", workflow="tops", workspace_root="...", conda_env="isce2")

# Parameter setting
insar_set_processing_param(project_id, key="reference_safe", value="/path/to/safe", justification="...")

# Validation
errors = insar_validate_runconfig(project_id)

# Execution
result = insar_run_workflow(project_id)
job_id = result["job_id"]

# Monitoring
status = insar_get_job(job_id, project_id)
logs = insar_get_job_logs(job_id, project_id)

# Output inspection
outputs = insar_list_outputs(project_id)
```

---

## Development Entry Points

### Add New ISCE2 Feature
1. **Parameter tuning**: Edit `src/insar_agent/engines/isce2/assets/processing_params_tops.yaml`
2. **Validation rule**: Add logic to `src/insar_agent/engines/isce2/validator.py`
3. **XML generation**: Modify `src/insar_agent/engines/isce2/runner.py:build_topsapp_xml()`
4. **Test coverage**: Add unit test to `tests/unit/test_isce2_sentinel_prep.py` + integration if real-data

### Debug Failing Job
1. Check log: `tail -f <log_path>` from `insar_get_job_logs()`
2. Inspect XML: `cat <workspace_root>/configs/topsApp.xml`
3. Verify inputs: `insar_describe_s1(safe_path)` for metadata
4. Re-run with `dry_run=True` to see command before execution

---

## Remaining Gaps (As of April 10, 2026)

From `docs/developer-documents/dev-plan.md`:
- **Real-data validation for ISCE2**: Current tests are unit-level; ISCE2 integration test on Sentinel-1 real data (not yet added)
- **Stack workflow maturity**: `stack` workflow defined but end-to-end ISCE2 stack + MintPy tested primarily via ISCE3 path
- **Error recovery**: No auto-retry for transient failures (network timeout on orbit download, etc.)

