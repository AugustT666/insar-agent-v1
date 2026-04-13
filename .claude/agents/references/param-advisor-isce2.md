# Param Advisor ISCE2 Reference Asset

This document stores Sentinel / ISCE2 parameter-advisory heuristics and workflow templates used by
`.claude/agents/param-advisor-isce2.md`.

## Evidence Priority

Prefer evidence in this order:

1. `insar_describe_s1` local metadata
2. current parameter set / project context
3. explicit user-provided scene facts
4. external references adopted after web search

## Shared Sentinel Factors That Matter Most

- relative orbit consistency
- pass direction
- polarization
- bbox / swath subset
- temporal separation
- land cover / expected coherence
- whether the user prioritizes detail or stability

## Workflow Template: tops (Single Pair D-InSAR)

Template id: `sentinel-isce2-dinsar`

Default template summary:

- `swaths = [1,2,3]`
- `do_esd = true`
- `esd_coherence_threshold = 0.85`
- `filter_strength = 0.5`
- `range_looks = 4`
- `azimuth_looks = 1`
- `unwrap_method = icu`

Use this template when the user wants a single-pair interferogram / coherence / unwrapped phase result.

Heuristics:

- If the user wants faster processing or only one useful burst/swath, recommend `swaths=[2]` or the clearest single swath.
- If coherence is weak, increase looks and/or filter strength conservatively.
- If SNAPHU is preferred for robustness, explain that it trades speed for unwrap stability.

## Workflow Template: stack (Time-Series / Interferogram Stack)

Template id: `sentinel-isce2-stack`

Default template summary:

- `workflow = interferogram`
- `num_connections = 3`
- `coregistration = NESD`
- `esd_coherence_threshold = 0.85`
- `filter_strength = 0.5`
- `range_looks = 9`
- `azimuth_looks = 3`
- `unwrap_method = snaphu`

Use this template when the user wants repeated-scene interferogram generation for time-series analysis.

Heuristics:

- Prefer coherence/stability over aggressive detail because one template propagates across many pairs.
- Reduce `num_connections` when the user prioritizes speed or when sample scene count is small.
- Switch `coregistration` to `geometry` only when overlap/NESD behavior is unreliable or the user explicitly prioritizes speed.
- Keep `unwrap_method = snaphu` unless the user explicitly wants a faster, less robust path.

## Default vs Change Guidance

Prefer defaults when:

- metadata is sparse or ambiguous
- the user has not stated a strong tradeoff preference
- a proposed change would reduce stack stability across many pairs

Prefer recommending a change when:

- the user explicitly prioritizes faster turnaround or higher detail
- bbox/swath narrowing clearly reduces runtime without breaking the science goal
- local metadata and scene context point to a known coherence or unwrap mismatch
