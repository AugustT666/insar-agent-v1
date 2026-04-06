# Runconfig 字段参考 — `insar` workflow

这些 dotted-key 路径用于：

```text
insar_set_runconfig_value(project_id, key, value)
```

## 必填字段

这些字段在 `insar_run_workflow` 启动前必须完成设置。

| 字段 | Dotted key | 示例值 |
|------|------------|--------|
| 参考景 RSLC | `runconfig.groups.input_file_group.reference_rslc_file` | `/data/ref.h5` |
| 次级景 RSLC | `runconfig.groups.input_file_group.secondary_rslc_file` | `/data/sec.h5` |
| DEM | `runconfig.groups.dynamic_ancillary_file_group.dem_file` | `/data/dem.tif` |
| 输出目录 | `runconfig.groups.product_path_group.product_path` | `/workspace/outputs` |
| scratch 目录 | `runconfig.groups.product_path_group.scratch_path` | `/workspace/scratch` |
| 输出文件名 | `runconfig.groups.product_path_group.sas_output_file` | `GUNW_product.h5` |

## 可选字段

| 字段 | Dotted key | 默认值 |
|------|------------|--------|
| GPU 开关 | `runconfig.groups.worker.gpu_enabled` | `false` |
| GPU 设备 ID | `runconfig.groups.worker.gpu_id` | `0` |
| 日志文件路径 | `runconfig.groups.logging.path` | （无） |
| 水体掩膜 | `runconfig.groups.dynamic_ancillary_file_group.water_mask_file` | （无） |

## 说明

- 其余 runconfig keys 都属于核心处理参数，例如 multilook、滤波、解缠。
- 这些参数被 `ALLOWED_SET_FIELDS` 锁定；如果试图通过 MCP 直接设置，会返回 `key_not_allowed`。
- 如果需要改白名单处理参数，应进入 `param-advisor-isce3`，再由 `insar_set_processing_param` 应用。
- 当前权威字段列表也可以通过 MCP 资源 `insar://allowed-fields/insar` 获取。
