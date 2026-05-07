# InSAR-Agent OpenCode Context

本项目在 OpenCode 中以 `insar-agent` 作为 primary agent 入口，目标是通过本项目自己的 skills 与 `insar-agent` MCP server 完成 InSAR 工作流实验。

## 必须遵守

- **每项 InSAR 任务开始时，立即用 `TodoWrite` 列出本次会话的所有主要步骤，并在每步完成后标记完成。** 这是会话状态追踪的唯一依据，任何未完成的 todo 都会触发续活机制。
- 只使用本项目注册的 agents、skills 和 `insar-agent` MCP server。
- InSAR/ISCE3/ISCE2/MintPy 处理动作必须通过 `insar_*` MCP tools 完成，不要直接运行 ISCE、conda、Python import 检查或处理脚本。
- 数据发现、SAFE 目录探查、场景元数据读取和环境能力检查也必须通过 `insar_*` MCP tools；不要用 shell 的 `ls`、`find`、`head`、`tail`、`python` 或 direct import 来替代。
- 不要用 shell 读取、复制、修补或伪造 ISCE/MintPy 生成产物；如果 `insar_*` 工具报告路径/结构错误，直接报告 blocker，让项目维护者修 MCP/engine/skill。
- 环境能力检查只通过 `insar_check_env`；不要用 shell 自行验证 conda env、ISCE import 或 MintPy import。
- OpenCode skill 名使用裸名，例如 `env-setup`、`d-insar-isce3`、`stack-insar-isce2`。
- 路径字段通过 `insar_set_runconfig_value` 设置；核心处理参数必须走 `param-advisor` 与 `insar_set_processing_param` 的确认流程。
- 参数建议必须先读取本地 metadata：ISCE3/NISAR 用 `insar_describe_rslc`，ISCE2/Sentinel 用 `insar_describe_s1`。
- 长任务优先后台 job，启动后记录 log path 或 job_id，并用 `insar_get_job` 轮询。
- 可以简短说明下一步，但不要把“Now let me ... / 我将调用 ...”作为独立回合；承诺调用 `insar_*` 工具时必须在同一回合完成工具调用。

## 自动实验模式

- 当任务文件声明为 autonomous regression / autonomous experiment 时，不要向用户提问。
- 自动实验中如需参数确认，使用任务文件指定的默认策略；没有默认策略时停止并报告 blocker。
- 自动实验中缺少 reference、DEM、orbit、conda env、base runconfig 或数据路径时，直接报告缺失项，不要等待用户补充。

## 实验目标

1. Exp-1：NISAR L-band / ISCE3 / D-InSAR 单对处理。
2. Exp-2：NISAR L-band / ISCE3 + MintPy / 时序网络处理。
3. Exp-3：Sentinel-1 C-band / ISCE2 / D-InSAR 单对处理。
4. Exp-4：Sentinel-1 C-band / ISCE2 + MintPy / 时序栈处理。

## 失败处理

- 如果工具返回错误，不要反复用同一参数重试超过 2 次。
- 如果缺少 reference、DEM、orbit、conda env、base runconfig 或数据路径，先向用户明确缺失项。
- 不要编造 workflow 参数；缺证据时停止并说明需要什么。
