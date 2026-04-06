---
name: insar-agent
description: >
  insar-agent 的统一入口 skill。用户提到 NISAR、ISCE3、RSLC、GUNW、
  interferogram、DEM 准备、MintPy、时序分析、baseline plot，或者不知道
  应该走哪条流程时，都应先进入本 skill。所有其他 insar-agent skills 之前
  先走这里。
---

# insar-agent — 会话路由器

## 核心原则

- 所有 ISCE3 操作都通过 `insar_*` MCP 工具完成，不直接运行 ISCE3 shell 命令。
- Skills 定义做什么、按什么顺序做；MCP 工具只负责执行动作并返回事实结果。
- 路径字段通过 `insar_set_runconfig_value` 设置；核心处理参数通过 `insar_set_processing_param` 设置。两者都由服务器侧 allowlist 约束。
- 用户一旦提出调参诉求，或给出会影响 multilook、滤波、解缠、大气校正的场景信息，就应切入 `param-advisor-isce3`。
- `param-advisor-isce3` 是统一参数建议入口，负责 `insar_describe_rslc`、项目级 subagent 委派、diff 展示和用户确认。
- 参数建议的 metadata-first 入口始终是 `insar_describe_rslc`；只有在本地证据不足时才允许自动外部搜索。
- 参考资料不完整时不要发明 workflow 参数，直接向用户确认。

## 会话启动时需要先确认的事实

在切入具体执行型 skill 前，每个会话至少确认一次以下跨流程事实：

- ISCE3 应使用哪个 conda 环境：`isce3` / `isce3gpu` / 项目自定义名称
- 选定环境是否真的能跑 `nisar.workflows.insar`
- MintPy 使用哪个 conda 环境，是否与 ISCE3 相同
- 当前会话是否已经有用户认可的 `base_runconfig` 模板路径

如果用户当前只想看文档或评审流程，可以暂缓这些问题。
如果用户要真正处理数据，则应在这里先确认，再切入
`d-insar-isce3`、`stack-insar-isce3` 或 `mintpy-isce3`。

## Skill 路由

按用户任务选择对应 skill：

| 任务 | Skill |
|------|-------|
| 初次安装，ISCE3 或 MCP 尚未安装 | `env-setup-nisar` |
| 下载 NISAR RSLC 或准备 / 下载 DEM | `data-prep-nisar` |
| 单对 RSLC 生成 GUNW | `d-insar-isce3` |
| 多景 RSLC 生成干涉图网络（batch） | `stack-insar-isce3` |
| MintPy 时序分析、位移、基线图 | `mintpy-isce3` |
| 任何调参与参数建议需求 | `param-advisor-isce3` |

如果任务跨多行，例如“数据还没准备好，但还要做单对处理”，先走 `data-prep-nisar`，再走 `d-insar-isce3`。

关于运行时上下文的边界：

- `insar-agent` 持有会话级上下文，例如 conda env 选择
- 各 workflow skills 持有 workflow 局部输入，例如 DEM、输出目录、配对策略、MintPy config

## 约束层级

```text
skills（流程指引）  →  服务器侧 ALLOWED_SET_FIELDS（核心参数硬拦截）
```

Skills 是工作流顺序与行为的唯一指引来源。
MCP server 是最终执行与校验层，`key_not_allowed` 不能被绕过。
