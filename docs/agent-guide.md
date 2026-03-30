# insar-agent Constraint Reference

For step-by-step workflow guidance, invoke the appropriate skill:
`insar-agent` → `d-insar-isce3` / `stack-insar-isce3` / `data-prep-nisar` / `env-setup-nisar` / `param-advisor-isce3`

---

## Hard constraints (NEVER violate)

1. Only official ISCE3 NISAR workflows. Do not invent custom workflows.
2. Path fields may be changed through `insar_set_runconfig_value`.
   Core processing parameters remain locked by default, except for the whitelist
   exposed through `param-advisor-isce3` + `insar_set_processing_param`.
   Attempting to set a non-whitelisted processing key returns `key_not_allowed`.
3. For skill-aware clients, parameter advice is a plugin contract: the main agent
   must delegate advice generation to the project-level subagent defined in
   `.claude/agents/param-advisor-isce3.md`. MCP cannot verify this at protocol
   level; it only enforces the MCP contract (allowlists + validation).
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
- `insar_create_project(...).guidance` — one-time reminder that skill-aware clients must enter `param-advisor-isce3` and use the project-level subagent before validate/export/run when parameter tuning is needed
