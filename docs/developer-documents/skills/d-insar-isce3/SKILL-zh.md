---
name: d-insar-isce3
description: >
  当用户要把一对 NISAR RSLC 文件处理成 GUNW 干涉图产品时使用。用户提供
  参考景和次级景路径、提到 D-InSAR / interferogram / coherence / GUNW，
  或者说“处理一对数据”时，都应进入本 skill。如果 DEM 或 RSLC 缺失，
  先进入 data-prep-nisar。
---

# D-InSAR：单对 RSLC → GUNW（Path A）

## 必要确认项（仅在缺失时询问）

- 参考景 RSLC 路径（`.h5`）
- 次级景 RSLC 路径（`.h5`）
- DEM 路径（`.tif`）；若缺失，先进入 `data-prep-nisar`
- 工作空间 / 输出目录（绝对路径）
- conda 环境名；先运行 `conda env list`，让用户从 ISCE 相关环境里选择

## 硬约束

- 所有 ISCE3 操作必须通过 `insar_*` MCP 工具完成，不直接运行 conda/python 命令。
- 如果 workflow 参数不清楚，就问用户，不要自行猜测。
- multilook、滤波、解缠、阈值等核心处理参数不能通过 `insar_set_runconfig_value` 修改。
  如果用户要调这些参数，必须在 Step 2 和 Step 3 之间切入 `param-advisor`。
- 必须从默认 runconfig 模板开始；`insar_create_project` 会自动加载。
- 如果 `insar_set_runconfig_value` 返回 `key_not_allowed`，不要尝试旁路方案。明确告诉用户：只有白名单处理参数才能通过 `param-advisor` + `insar_set_processing_param` 修改。

## 标准流程（始终按此顺序）

1. **创建项目**

   ```text
   insar_create_project(engine="isce3", workflow="insar",
                        workspace_root=<path>, conda_env=<env>)
   ```

   保存返回的 `project_id`。响应里还会带 `required_fields`。

2. **设置必填路径字段**（通过 `insar_set_runconfig_value` 调 6 次）

   完整 dotted-key 名称见 `references/runconfig-fields.md`。

   必填字段：

   - `reference_rslc_file`
   - `secondary_rslc_file`
   - `dem_file`
   - `product_path`
   - `scratch_path`
   - `sas_output_file`

   可选字段：

   - `worker.gpu_enabled`
   - `worker.gpu_id`
   - `logging.path`

2.5. **（可选）参数调优**

如果用户要改处理参数，就进入 `param-advisor`。该 skill 负责：

- 调 `insar_describe_rslc`
- 调 `.claude/agents/param-advisor.md`
- 展示参数 diff 与三选一确认
- 如用户接受建议，调用 `insar_set_processing_param`
- 调 `insar_get_runconfig(format='yaml')` 展示完整 YAML

完成后再回到本 workflow 继续 Step 3。

3. **运行 workflow**

   ```text
   insar_run_workflow(project_id)
   ```

   这个调用内部已经完成 validate + export + launch。保存返回的 `job_id`
   和 `log_path`。同时告诉用户日志路径，以便用户需要时实时观察输出：

   ```bash
   tail -f <log_path>
   ```

   响应里还会带精确的 `poll` 调用方式。

4. **轮询状态**

   每隔约 30 秒调用一次：

   ```text
   insar_get_job(job_id, project_id)
   ```

   直到 `status` 变成 `done` 或 `failed`。

5. **若失败，读取日志**

   ```text
   insar_get_job(job_id, project_id, include_logs=True)
   ```

   提炼关键报错行。优先建议路径级修复；如果是白名单处理参数问题，则重新进入 `param-advisor`。

6. **列出输出**

   ```text
   insar_list_outputs(job_id, project_id)
   ```

7. **（可选）导出 GeoTIFF**

如果用户需要栅格可视化：

```text
insar_export_geotiff(h5_path=<GUNW .h5 路径>, output_dir=<workspace>/browse)
```

该步骤要求 ISCE3 conda 环境中可用 GDAL。

## 完成后必须汇报的内容

- 使用的引擎和 workflow：`isce3 / insar`
- 参考景与次级景 RSLC 路径
- 使用的 DEM 路径
- 产品输出目录与文件名
- 最终 job 状态：`done` / `failed`
- `insar_list_outputs` 返回的产物列表

## 参考

- `references/runconfig-fields.md`：所有可设置字段的完整 dotted-key 列表
