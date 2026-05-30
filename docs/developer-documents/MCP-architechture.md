# MCP 架构说明

本文档描述 `insar-mcp-server` 的 MCP 层设计，包括 Resources、Prompts、Tools 的组织方式、引擎调用机制和进程管理模型。

系统整体分层、数据模型与工作区布局请见 [architecture.md](../architecture.md)。
每个工具的完整参数规范请见 [MCP-tools.md](MCP-tools.md)。

---

## MCP Server 注册面

服务器通过 FastMCP 注册，名称为 `"insar-mcp-server"`：

```python
mcp = FastMCP("insar-mcp-server")
```

启动方式：
```bash
insar-mcp-server --stdio          # stdio 模式（供 agent 客户端接入）
insar-mcp-server --describe       # 打印全部工具/资源/prompt 的 JSON 摘要
```

插件模式下服务器名为 `plugin:insar-agent-plugin:insar-mcp-server`（冒号，非下划线）。

---

## Resources（2 个）

Resources 是只读文档，AI 客户端在处理任务前加载，不触发副作用。

### `insar://workflow-guide`

**内容：** 指向 `insar-agent-plugin:insar-agent` skill 的入口引导——告知直接访问 MCP server 的 agent 应通过 skill 获取完整工作流约束和路由逻辑。

**实现：** 内联于 `mcp/server.py::_WORKFLOW_GUIDE` 字符串常量，不读取文件系统。

```python
@mcp.resource("insar://workflow-guide")
def get_workflow_guide() -> str:
    return _WORKFLOW_GUIDE
```

### `insar://allowed-fields/{workflow}`

**内容：** 动态生成指定工作流的可写字段列表（Required + Optional 两节）。数据来自 `engines/isce3/defaults.py::ALLOWED_SET_FIELDS` 与 `REQUIRED_PATH_FIELDS`。

**URI 参数：** `workflow`，例如 `insar`、`gslc`。未知 workflow 返回错误消息字符串（不抛异常）。

---

## Prompts（2 个）

Prompts 是任务引导模板，调用后返回预填好的分步说明字符串。

### `process_insar_pair`

用于处理单对 RSLC（Path A）的引导式模板。参数：`reference_rslc`, `secondary_rslc`, `dem`, `output_dir`, `conda_env`（均可留空，留空时返回通用占位符）。

返回 8 步说明，包含参数调优入口（param-advisor）和约束提醒。

### `process_insar_batch`

用于批处理 stack + network 准备（Path B）的引导式模板。参数：`data_dir`, `base_runconfig`, `dem`, `output_dir`, `network_mode`, `max_temporal_baseline_days`。

返回 2 步说明（stack → network），包含可选的参数调优前置步骤和输出结构说明。

---

## Tools（25 个）

按功能分 9 组，全部通过 `@mcp.tool()` 注册。

| 组 | 工具（按注册顺序） | 说明 |
|----|-------------------|------|
| **G1 发现** | `insar_discover`, `insar_get_project` | 引擎/工作流发现；项目元数据查询 |
| **G2 配置** | `insar_create_project`, `insar_get_runconfig`, `insar_set_runconfig_value`, `insar_record_param_advice`, `insar_set_processing_param`, `insar_export_runconfig` | 项目生命周期；runconfig 读写；参数建议存档 |
| **G3 执行** | `insar_run_workflow`, `insar_get_job` | 启动工作流；轮询任意类型 Job |
| **G4 输出** | `insar_list_outputs` | 列举完成 Job 的产品文件 |
| **G5 Stack** | `insar_prepare_stack`, `insar_prepare_network`, `insar_run_batch`, `insar_plot_baseline` | 批量 runconfig 生成；网络准备；并行批处理；基线可视化 |
| **G6 数据** | `insar_describe_rslc`, `insar_download_rslc`, `insar_download_dem` | RSLC 元数据摘要；RSLC/DEM 下载 |
| **G7 分析** | `insar_export_geotiff`, `insar_run_mintpy`, `insar_run_mintpy_isce2` | GeoTIFF 导出；ISCE3/ISCE2 MintPy 时序分析 |
| **G8 Sentinel** | `insar_download_scene`, `insar_describe_s1`, `insar_prepare_sentinel_data` | S1 场景下载；SAFE 元数据；ISCE2 输入整理 |
| **G9 环境** | `insar_check_env` | conda 环境 + MCP + skill 安装状态检查 |

---

## 引擎调用流程

所有引擎均通过 `_launch_detached_shell_job()` 脱离 MCP server 进程启动，避免阻塞 stdio 通道：

```
insar_run_workflow()
  ├── 1. 校验 runconfig（validate_runconfig）
  ├── 2. 导出 YAML（yaml.dump → run_root/configs/runconfig.yaml）
  ├── 3. 构建命令（build_workflow_command）
  │       ISCE3: ["conda","run","-n",env,"python","-m","nisar.workflows.insar",runconfig]
  │       ISCE2 tops: ["conda","run",...,"python","...topsApp.py","--dostep","esd"]
  │       ISCE2 stack: ["conda","run",...,"python","...stackSentinel.py",args...]
  ├── 4. 包装 exit code 持久化
  │       shell_command = f"{cmd}; status=$?; printf '%s' $status > exitcode; exit $status"
  └── 5. _launch_detached_shell_job(shell_command, cwd, env, log_path)
          nohup bash -lc <shell_command> > log 2>&1 < /dev/null &
          printf PID  →  job.pid
```

批处理（`insar_run_batch`）同样走 `_launch_detached_shell_job()`，命令为 `run_parallel.sh` 或 `run_all.sh`。

---

## Job 状态机

```
submitted
    ↓  _launch_detached_shell_job 成功
running
    ↓  _refresh_workflow_job_status（每次 insar_get_job 调用）
    ├── exitcode 文件存在 → 读取 → done (0) / failed (非0)
    ├── PID 不存在 / 僵尸 + 日志分析 → done / failed
    └── PID 存活 → 保持 running
done / failed
```

三级状态检测的优先级：exitcode 文件 > PID 存活 > 日志扫描。exitcode 文件是最可靠的信号，由 shell wrapper 原子写入。

---

## 进程管理辅助函数

| 函数 | 作用 |
|------|------|
| `_launch_detached_shell_job` | nohup 启动，捕获 PID |
| `_refresh_workflow_job_status` | 单次状态刷新（三级降级） |
| `_finalize_job_status_from_artifacts` | 根据 exitcode + 日志最终化状态 |
| `_find_reusable_workflow_job` | 去重：同 project/engine/workflow 的 running/done Job 复用 |
| `_read_log_tail` | 读日志末 N 行 |
| `_read_exit_code` | 读 .exitcode 文件 |
| `_workflow_log_has_failure` | 日志失败模式扫描 |
| `_workflow_log_has_success` | 日志成功标记扫描 |

---

## 工作区污染防护

`insar_run_workflow` 和 `insar_prepare_stack/network` 通过 `RunLayout` 将所有输出限制在 `<task_id>/outputs/<run_id>/` 子目录下。

`_task_root_pollution()` 检测 task root 下的非托管文件，若存在则在工具结果中附加 `task_root_pollution` 警告，指导 agent 清理。合法的管理目录为：`.insar_agent/`、`sessions/`、`outputs/`。

---

## 环境安全

`_conda_safe_env()` 在启动引擎前清理可能干扰 conda 的环境变量（如 `_CONDA_SET_GEOTIFF_CSV`），防止父 shell 的 GDAL 相关环境污染子进程。

敏感参数（`password`, `token`, `access_token` 等）在写入 params JSON 日志前由 `_redact_sensitive_params()` 脱敏。

---

## 交互模式（interaction_mode）

`insar_prepare_stack`、`insar_prepare_network`、`insar_run_batch`、`insar_run_mintpy`、`insar_plot_baseline` 均支持 `interaction_mode` 参数：

| 值 | 行为 |
|----|------|
| `interactive`（默认）| `handoff_required=true`，要求 agent 暂停等待用户检查产物 |
| `auto` | `handoff_required=false`，可自动推进；仍返回 review 信息供展示 |

这让 agent 可以在自主模式（最少打断）和交互模式（每步人工确认）之间切换，由 skill 和用户共同决定。
