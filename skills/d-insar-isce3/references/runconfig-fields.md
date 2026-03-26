# Runconfig Field Reference — `insar` workflow

Use these dotted-key paths with `insar_set_runconfig_value(project_id, key, value)`.

## Required fields (must be set before validation passes)

| Field | Dotted key | Example value |
|-------|-----------|---------------|
| Reference RSLC | `runconfig.groups.input_file_group.reference_rslc_file` | `/data/ref.h5` |
| Secondary RSLC | `runconfig.groups.input_file_group.secondary_rslc_file` | `/data/sec.h5` |
| DEM | `runconfig.groups.dynamic_ancillary_file_group.dem_file` | `/data/dem.tif` |
| Output directory | `runconfig.groups.product_path_group.product_path` | `/workspace/outputs` |
| Scratch directory | `runconfig.groups.product_path_group.scratch_path` | `/workspace/scratch` |
| Output filename | `runconfig.groups.product_path_group.sas_output_file` | `GUNW_product.h5` |

## Optional fields

| Field | Dotted key | Default |
|-------|-----------|---------|
| GPU enabled | `runconfig.groups.worker.gpu_enabled` | `false` |
| GPU device ID | `runconfig.groups.worker.gpu_id` | `0` |
| Log file path | `runconfig.groups.logging.path` | (none) |
| Water mask | `runconfig.groups.dynamic_ancillary_file_group.water_mask_file` | (none) |

## Notes

- All other runconfig keys are core processing parameters (multilook, filtering, unwrapping).
  They are locked via `ALLOWED_SET_FIELDS` and return `key_not_allowed` if set via MCP.
  Edit them manually in the exported YAML after `insar_export_runconfig`.
- Use `insar://allowed-fields/insar` MCP resource to get the authoritative current list.
