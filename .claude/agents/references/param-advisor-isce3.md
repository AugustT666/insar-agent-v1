# Param Advisor ISCE3 Reference Asset

This document stores parameter-advisory heuristics and evidence patterns used by
`.claude/agents/param-advisor-isce3.md`. It is a reference asset, not the
subagent contract.

## Evidence Profile Guidance

Prefer evidence in this order:

1. `insar_describe_rslc` local metadata
2. current runconfig / project context
3. explicit user-provided scene facts
4. external references adopted after web search

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
- polarization
- orbit direction
- temporal baseline
- perpendicular baseline when available
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
