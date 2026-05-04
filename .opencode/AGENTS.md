# InSAR-Agent OpenCode Context

本项目在 OpenCode 中以 `insar-agent` 作为 primary agent 入口，目标是通过本项目自己的 skills 与 `insar-agent` MCP server 完成 InSAR 工作流实验。

## 必须遵守

- 只使用本项目注册的 agents、skills 和 `insar-agent` MCP server。
- InSAR/ISCE3/ISCE2/MintPy 处理动作必须通过 `insar_*` MCP tools 完成，不要直接运行 ISCE、conda 或处理脚本。
- OpenCode skill 名使用裸名，例如 `env-setup`、`d-insar-isce3`、`stack-insar-isce2`。
- 路径字段通过 `insar_set_runconfig_value` 设置；核心处理参数必须走 `param-advisor` 与 `insar_set_processing_param` 的确认流程。
- 参数建议必须先读取本地 metadata：ISCE3/NISAR 用 `insar_describe_rslc`，ISCE2/Sentinel 用 `insar_describe_s1`。
- 长任务优先后台 job，启动后记录 log path 或 job_id，并用 `insar_get_job` 轮询。

## 实验目标

1. Exp-1：NISAR L-band / ISCE3 / D-InSAR 单对处理。
2. Exp-2：NISAR L-band / ISCE3 + MintPy / 时序网络处理。
3. Exp-3：Sentinel-1 C-band / ISCE2 / D-InSAR 单对处理。
4. Exp-4：Sentinel-1 C-band / ISCE2 + MintPy / 时序栈处理。

## 失败处理

- 如果工具返回错误，不要反复用同一参数重试超过 2 次。
- 如果缺少 reference、DEM、orbit、conda env、base runconfig 或数据路径，先向用户明确缺失项。
- 不要编造 workflow 参数；缺证据时停止并说明需要什么。
