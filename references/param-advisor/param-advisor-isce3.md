# Param Advisor ISCE3 Reference Asset

This document stores parameter-advisory heuristics and evidence patterns used by
`agents/param-advisor.md` (engine=isce3). It is a reference asset, not the
subagent contract.

## Evidence Profile Guidance

Prefer evidence in this order:

1. `insar_describe_rslc` local metadata
2. current runconfig / project context
3. explicit user-provided scene facts
4. external references adopted after web search

For real-data runs, web search is expected rather than optional. Use it to enrich,
not override, local metadata with study-area and sensor context.

Preferred external source classes:

1. NASA/JPL/NISAR mission and product documentation
2. ASF / Alaska Satellite Facility data and SAR documentation
3. USGS or relevant national geological survey resources for geology / hazards
4. ESA / Copernicus documentation for Sentinel-1 comparisons
5. Peer-reviewed papers for study-area deformation mechanisms
6. Official ISCE / SNAPHU documentation for algorithm behavior

Each inferred fact should be tagged as one of:

- `user_provided`
- `runconfig_inferred`
- `metadata_inferred`
- `external_lookup`

If local metadata and user context are insufficient, web search is allowed, but
local observational facts remain primary.

## Scene Factors That Matter Most

- sensor / satellite
- band (`L`, `C`, `X`)
- wavelength and nominal resolution / pixel spacing
- revisit cycle and temporal baseline
- polarization
- orbit direction
- perpendicular baseline when available
- study-area geology, tectonic / volcanic setting, and known deformation style
- terrain relief
- land cover type
- climate / moisture regime
- deformation goal and spatial scale

## Parameter Heuristics

### Multilook: `crossmul.range_looks` / `crossmul.azimuth_looks`

Defaults: `11 / 11`

- Urban + L-band + short baseline: consider smaller looks such as `5 / 5` to preserve resolution
- Agriculture / vegetation + long baseline: consider larger looks such as `15-20 / 15-20` to improve coherence
- Desert / dry bare land: defaults often remain acceptable
- Time-series / MintPy-oriented processing: prefer coherence-preserving defaults or slightly larger looks

### Geocode Output Posting: `geocode.output_posting.A.x_posting` / `y_posting`

Defaults: `null / null` (ISCE3 auto-derives spacing from the radar grid + DEM)

**Units follow `geocode.output_epsg`.** When `output_epsg` is `null`, ISCE3
inherits the DEM CRS, which for Copernicus/SRTM DEMs is geographic
**EPSG:4326 (degrees)**. A metric-looking value such as `30` is then
interpreted as **30 degrees per pixel** and collapses the geocoded grid to a
1×1 raster (observed failure mode).

- **Strongly prefer leaving `output_posting` `null`** — auto-derivation yields
  a correct ~30 m-equivalent spacing in whatever CRS applies. This matches the
  stack/network path, which keeps it `null` and geocodes correctly.
- Only recommend an explicit posting when the user needs a specific pixel size,
  and then it MUST be unit-consistent with the output grid:
  - For metric posting (e.g. `30` m), also recommend setting
    `geocode.output_epsg` to the scene-center UTM zone in the **same** package.
  - For a geographic grid (EPSG:4326), express posting in **degrees**
    (≈ `0.000277` for ~30 m), never in metres.
- Never recommend a bare metric `output_posting` while `output_epsg` is `null`.

## Time-series / Path B Guidance

When a single tuned `base_runconfig` will be propagated to many stack or network pairs:

- Prefer conservative changes over aggressive single-pair optimization
- Prioritize stable coherence and unwrap robustness across the stack
- Treat weak-evidence tuning as a reason to keep defaults
- Ask the main agent to preserve user control if pair/network design may still change
- Only recommend sharper / lower-look settings when the evidence strongly supports that tradeoff

### Interferogram Filtering: `filter_interferogram.filter_type`

Default: `no_filter`

- High-coherence urban or desert scenes: usually keep `no_filter`
- Low-coherence vegetated scenes: filtering may help, but only recommend changes when evidence is strong

### Unwrapping Algorithm: `phase_unwrap.algorithm`

Default: `snaphu`

- `snaphu` remains the default recommendation for most scenes
- Faster alternatives are acceptable only for quick-look or clearly high-coherence cases

### Snaphu Cost Mode: `phase_unwrap.snaphu.cost_mode`

Default: `smooth`

- Slow, spatially smooth deformation: `smooth`
- Large localized deformation or coseismic motion: consider `defo`
- Terrain-dominated phase or large DEM-sensitive relief: consider `topo`

### Snaphu Nlooks / Tiles

Defaults: `nlooks = null`, `ntiles = null`

- Keep `nlooks = null` unless poor unwrap quality strongly suggests manual tuning
- Consider `ntiles` for very large, high-gradient deformation scenes

### Additional Unwrap Looks: `phase_unwrap.range_looks` / `phase_unwrap.azimuth_looks`

Defaults: `1 / 1`

- Usually keep defaults
- Increase only when unwrap instability is more important than spatial detail

### Ionosphere Correction: `ionosphere_phase_correction.enabled`

Default: `false`

- L-band + high latitude or strong ionospheric conditions: consider enabling
- L-band equatorial / scintillation-prone regions: consider enabling
- C-band: usually keep disabled
- Treat this as high-risk if required ancillary inputs are missing

### Troposphere Correction: `troposphere_delay.enabled`

Default: `false`

- Large relief + wide coverage: consider enabling
- Humid / coastal / monsoon regions with broad coverage: consider enabling
- Dry, compact scenes: usually keep disabled
- Treat this as high-risk if weather-model inputs are not prepared

## Default vs Change Guidance

Prefer keeping defaults when:

- evidence is weak or contradictory
- changing the parameter would require ancillary inputs that are not available
- the run goal is exploratory and defaults are already standard for the workflow

Prefer recommending a change when:

- local metadata plus user context point to a known high-impact mismatch
- the change is whitelist-controlled and has a clear justification
- the user goal explicitly prioritizes coherence, deformation sensitivity, or resolution tradeoffs

## Output Expectations

For each recommended change, include:

- current value
- default value
- proposed value
- reason
- risk
- confidence
- provenance
