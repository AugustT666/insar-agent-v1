# insar-agent Constraint Reference

For step-by-step workflow guidance, invoke the appropriate skill:
`insar-agent` → `d-insar-isce3` / `stack-insar-isce3` / `data-prep-nisar` / `env-setup-nisar`

---

## Hard constraints (NEVER violate)

1. Only official ISCE3 NISAR workflows. Do not invent custom workflows.
2. Only PATH fields may be changed via MCP. Core processing parameters
   (multilook, filtering, unwrapping, thresholds, iterations) are LOCKED.
   Attempting to set them returns `key_not_allowed`.
3. Always start from the default runconfig template —
   `insar_create_project` loads it automatically.
4. Execution command is always:
   `conda run -n <env> python -m nisar.workflows.<workflow> /path/to/runconfig.yaml`

---

## Error codes

| Code | Meaning |
|------|---------|
| `key_not_allowed` | Core processing parameter — locked, edit YAML manually |
| `project_not_found` | Wrong `project_id` |
| `key_not_found` | Dotted path does not exist in runconfig |
| `runconfig_invalid` | Required path fields missing or null |
| `runconfig_not_exported` | Call `insar_export_runconfig` before `insar_run_workflow` |
| `path_not_found` | Filesystem path argument does not exist |
| `invalid_input` | Bad parameter value (e.g. negative baseline, unknown network_mode) |
| `dependency_missing` | Required library (e.g. GDAL) not available in current environment |

---

## Resources

- `insar://allowed-fields/{workflow}` — authoritative list of settable fields per workflow
