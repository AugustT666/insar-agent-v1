# insar-agent Constraint Reference

For step-by-step workflow guidance, invoke the appropriate skill:
`insar-agent` → `d-insar-isce3` / `stack-insar-isce3` / `d-insar-isce2` / `stack-insar-isce2` / `data-prep-nisar` / `env-setup-nisar`

---

## Hard constraints (NEVER violate)

1. Only official ISCE3 NISAR workflows. Do not invent custom workflows.
2. Path fields may be changed through the engine-appropriate setter.
   Core processing parameters remain locked by default, except for the whitelist
   exposed through the engine-appropriate param-advisor skill +
   `insar_set_processing_param`.
   Attempting to set a non-whitelisted processing key returns `key_not_allowed`.
3. For skill-aware clients, parameter advice is a plugin contract: the main agent
   must route into the engine-appropriate advisor skill and that skill must
   delegate advice generation to its project-level subagent.
   - NISAR / ISCE3: `skills/param-advisor-isce3/SKILL.md` → `.claude/agents/param-advisor-isce3.md` → `insar_describe_rslc`
   - Sentinel / ISCE2: `skills/param-advisor-isce2/SKILL.md` → `.claude/agents/param-advisor-isce2.md` → `insar_describe_s1`
   MCP cannot verify this at protocol level; it only enforces the MCP contract (allowlists + validation).
   Every parameter advisory call should perform web search.
   External search results are advisory only, cannot replace local observational facts,
   and the user remains responsible for deciding whether to trust or apply them.
4. Always start from the default runconfig template —
   `insar_create_project` loads it automatically.
5. Execution command is always:
   `conda run -n <env> python -m nisar.workflows.<workflow> /path/to/runconfig.yaml`

---

## Error codes

| Code | Meaning |
|------|---------|
| `key_not_allowed` | Key is not whitelisted for the chosen MCP tool |
| `project_not_found` | Wrong `project_id` |
| `key_not_found` | Dotted path does not exist in runconfig |
| `runconfig_invalid` | Required path fields missing or null — returned directly by `insar_run_workflow` |
| `path_not_found` | Filesystem path argument does not exist |
| `invalid_input` | Bad parameter value (e.g. negative baseline, unknown network_mode) |
| `dependency_missing` | Required library (e.g. GDAL) not available in current environment |

---

## Resources

- `insar://allowed-fields/{workflow}` — authoritative list of settable fields per workflow
- `insar_create_project(...).guidance` — one-time reminder that skill-aware clients must enter the engine-appropriate parameter advisor before validate/export/run when parameter tuning is needed
- `insar_describe_rslc(...)` — metadata-first summary for NISAR/ISCE3 parameter advice
- `insar_describe_s1(...)` — metadata-first summary for Sentinel/ISCE2 parameter advice
