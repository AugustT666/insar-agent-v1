# Param Advisor ISCE2 Reference Asset

This document stores Sentinel / ISCE2 parameter-advisory heuristics and workflow templates used by
`agents/param-advisor.md` (engine=isce2).

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
- `range_looks = 20`
- `azimuth_looks = 4`
- `unwrap_method = snaphu`

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
- `range_looks = 10`
- `azimuth_looks = 2`
- `do_unwrap = true`
- `unwrap_method = snaphu`
- `num_proc = 1`

Use this template when the user wants repeated-scene interferogram generation for time-series analysis.

Heuristics:

- Prefer coherence/stability over aggressive detail because one template propagates across many pairs.
- Reduce `num_connections` when the user prioritizes speed or when sample scene count is small.
- Switch `coregistration` to `geometry` only when overlap/NESD behavior is unreliable or the user explicitly prioritizes speed.
- Keep `do_unwrap = true` and `unwrap_method = snaphu` for production stack products unless the user explicitly asks for a faster validation-only path without unwrapped outputs.
- Treat `num_proc` as an execution-resource parameter, not a science parameter. Use the runtime/hardware evidence profile to compare current `num_proc` with logical CPU count and memory.
- For ISCE2 stack runs, keep `num_proc` CONSERVATIVE. **`num_proc > 1` can SILENTLY DROP per-(date,swath) coregistration tasks** in stackSentinel's parallel run-steps (fullBurst geo2rdr/resample), leaving an incomplete `coreg_secondarys/<date>/IW*.xml` that later crashes `extractCommonValidRegion` with a bare `FileNotFoundError` — the dropping step logs no error and still exits 0. **Empirically observed (E1 142A, 31 scenes): `num_proc=8` silently dropped a secondary's IW2 resample (run failed); `num_proc=2` and `num_proc=1` completed coregistration cleanly.** This is a parallelism race, NOT a RAM/IO-pressure issue — ample CPU/memory does NOT prevent it. Do NOT scale `num_proc` to the logical CPU count and do NOT blindly adopt `suggested_num_proc_upper_bound`; recommend a small value (1–2; up to ~4 only with explicit caution) and verify coregistration completeness afterward (every secondary has `IW*.xml` for all swaths). Never describe a higher `num_proc` as "no correctness risk".

## Default vs Change Guidance

Prefer defaults when:

- metadata is sparse or ambiguous
- the user has not stated a strong tradeoff preference
- a proposed change would reduce stack stability across many pairs

Prefer recommending a change when:

- the user explicitly prioritizes faster turnaround or higher detail
- bbox/swath narrowing clearly reduces runtime without breaking the science goal
- local metadata and scene context point to a known coherence or unwrap mismatch
