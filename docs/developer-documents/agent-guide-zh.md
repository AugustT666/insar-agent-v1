# insar-agent 约束参考

如需分步骤工作流指导，请调用对应 skill：
`insar-agent` → `d-insar-isce3` / `stack-insar-isce3` / `d-insar-isce2` / `stack-insar-isce2` / `data-prep` / `mintpy` / `env-setup`

---

## 硬约束（绝不可违反）

1. 只允许使用官方 ISCE3 NISAR workflows。不得自造自定义 workflow。
   对 Sentinel-1 路径，只允许使用项目封装的官方 ISCE2 `topsApp.py` / `stackSentinel.py` 路径。
2. 路径字段只能通过 `insar_set_runconfig_value` 修改。
   核心处理参数默认锁定，只有 `param-advisor` +
   `insar_set_processing_param` 暴露的白名单参数可以修改。
   如果尝试设置非白名单处理参数，会返回 `key_not_allowed`。
3. 对 skill-aware 客户端，参数建议属于插件契约：
   主 agent 必须先进入 `skills/param-advisor/SKILL.md`，
   该 skill 再把建议生成委派给
   `.claude/agents/param-advisor.md` 中定义的项目级 subagent。
   MCP 无法在协议层验证这件事；它只负责执行 MCP 契约中的 allowlist
   与参数校验。NISAR / ISCE3 的 metadata-first 入口是 `insar_describe_rslc`；
   Sentinel-1 / ISCE2 的 metadata-first 入口是 `insar_describe_s1`。
   每次参数建议都应执行 web search。
   外部搜索结果仅供参考，不能替代本地 RSLC 元数据中的可观测事实，
   用户仍需自行决定是否信任并采用这些来源。
4. 必须始终从默认 runconfig 模板开始。
   `insar_create_project` 会自动加载模板。
5. 执行命令始终是：
   `conda run -n <env> python -m nisar.workflows.<workflow> /path/to/runconfig.yaml`

---

## 错误代码

| 代码 | 含义 |
|------|------|
| `key_not_allowed` | 该 key 不在当前 MCP 工具允许设置的白名单里 |
| `project_not_found` | `project_id` 错误 |
| `key_not_found` | dotted path 在 runconfig 中不存在 |
| `runconfig_invalid` | 必填路径字段缺失或为空；由 `insar_run_workflow` 直接返回 |
| `path_not_found` | 传入的文件系统路径不存在 |
| `invalid_input` | 参数值非法，例如负 temporal baseline、未知 `network_mode` |
| `dependency_missing` | 当前环境缺少必需库，例如 GDAL |

---

## 资源

- `insar://allowed-fields/{workflow}`：某个 workflow 当前可设置字段的权威列表
- `insar_create_project(...).guidance`：一次性提醒 skill-aware 客户端在需要调参时进入 `param-advisor`
- `insar_describe_rslc(...)`：为参数建议提供 metadata-first RSLC 摘要
