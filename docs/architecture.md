# Architecture

> 接入新引擎（GAMMA/GMTSAR 等）请先读 [engine-onboarding.md](./engine-onboarding.md)
> ——三层接入模型 + 流程清单。输出目录统一机制见 `core/output_resolver.py`：所有产物
> 必须经 `resolve_output` 落到 `<output_root>/<task>_<timestamp>/insar_product/<subdir>/`，
> 不得泄漏到树外。

## 系统总览

insar-agent 是一个 Python 包，通过 MCP stdio 服务器向 AI agent 客户端（Claude Code、Codex 等）暴露 NISAR/Sentinel-1 InSAR 处理能力。agent 只通过 MCP 工具与系统交互，不直接执行 conda/Python 命令。

论文方法章节的三层架构图稿维护在 papers 仓库：`InSAR-Agent小论文/latex/figures/insar-agent-three-layer-architecture.svg`。该图按当前 `refactor/output-layout-and-modularization` 分支的真实模块边界绘制：交互层负责 agent-facing 路由，MCP 编排层负责工具契约、项目状态与输出约束，引擎执行层负责 ISCE3/ISCE2/MintPy 处理与产物落盘。

## 层次结构

```
Layer 1: Agent interaction
  Agent Client (Claude Code / Codex / etc.)
  Plugin command + skills + param-advisor subagent
  ↓ MCP stdio / skill routing

Layer 2: MCP orchestration and contracts
  insar_agent.mcp       # FastMCP registration, tools, resources, prompts
  insar_agent.core      # Project, Job, BatchJob, config, session, output_resolver
  insar_agent.runtime   # workspace layout, environment checks, logging
  ↓ validated project state + run layout

Layer 3: Engine execution and products
  insar_agent.engines.base  # EngineAdapter Protocol and registry contract
  insar_agent.engines.isce3 # NISAR/ISCE3: runner, stack, network, DEM, bbox,
                            # GeoTIFF, metadata, MintPy, param advisor
  insar_agent.engines.isce2 # Sentinel-1/ISCE2: runner, Sentinel prep, stack,
                            # stack runtime, MintPy, param advisor, validator
  ↓ conda run
  local processing envs     # isce3, isce3gpu, isce2, mintpy, ...
```

**关键分层原则：**
- 交互层只表达任务意图、工作流路由和人工确认门控；不得绕过 MCP 直接执行处理命令。
- MCP 编排层是稳定公共契约面：工具注册、资源约束、项目状态、job 跟踪、路径安全和统一输出落点都在这里闭合。
- 引擎执行层只处理已验证输入；引擎差异被限制在 `engines/<engine>/` 与 `EngineAdapter` 插槽内。
- 所有任务产物必须经 `core/output_resolver.py::resolve_output` 落到 `<output_root>/<task>_<timestamp>/insar_product/<subdir>/`；共享输入/下载数据落在 `<output_root>/prepare/<kind>/`，按交互契约可由用户显式指定路径。

---

## 核心数据模型

### Project

持久化路径：`<output_root>/<task>_<timestamp>/.insar_agent/project.json`

`insar_create_project(output_root=...)` 返回唯一的 `project_id`，作为所有后续工具的单一句柄。

| 字段 | 类型 | 说明 |
|------|------|------|
| `project_id` | UUID str | 全局唯一标识（所有工具的单一句柄） |
| `engine` | str | `"isce3"` 或 `"isce2"` |
| `workflow` | str | `"insar"` / `"gslc"` (isce3) 或 `"tops"` / `"stack"` (isce2) |
| `output_root` | str | 顶层输出目录绝对路径（包含所有 run 目录及 prepare/ 共享输入） |
| `task` | str | 工作流派生的任务标识，如 `"d-insar-isce3"` |
| `run_id` | str | 时间戳形式的 run 标识，如 `"20260620T010203Z"` |
| `conda_env` | str | conda 环境名 |
| `runconfig` | dict | 当前活动配置（ISCE3 YAML 结构或 ISCE2 平坦参数字典） |
| `runconfig_template` | dict | 未修改的模板副本，用于重置和差分 |
| `runconfig_exported_path` | str | 最后一次导出的 YAML 路径 |

> 向后兼容：`workspace_root` 属性为只读 shim，等价于 `output_root`；旧 `task_id` 字段在
> `task` 未设置时作为降级回退。

ISCE3 runconfig 是嵌套 YAML 结构（`runconfig.groups.*`）。ISCE2 是平坦键值字典（`reference_safe`, `dem_file`, `do_esd` 等）。

### Job

持久化路径：`<output_root>/<task>_<run_id>/.insar_agent/jobs/{job_id}.json`

长时任务（`insar_run_workflow`、`insar_run_batch`、`insar_run_mintpy*`、`insar_download_*`）自动后台化，通过 `insar_get_job(project_id, job_id)` 轮询，实行睡眠-唤醒纪律（避免忙轮询）。

| 字段 | 说明 |
|------|------|
| `job_id` | 12 位 hex UUID |
| `status` | `running` / `done` / `failed` |
| `pid` | 后台进程 PID |
| `exit_code` | shell 退出码（由 `.exitcode` 文件读取） |
| `log_path` | `<run>/insar_product/logs/{job_id}.log` |
| `exit_code_path` | `<run>/insar_product/logs/{job_id}.exitcode` |
| `task_id`, `run_id`, `run_root` | 运行布局感知字段 |
| `submitted_at`, `started_at`, `finished_at` | ISO 8601 时间戳 |

### BatchJob

持久化路径：`{batch_dir}/.insar_agent/jobs/{job_id}.json`

与 Job 类似，但面向批处理场景，额外记录 `batch_dir`、`batch_type`（`"stack"` 或 `"network"`）、`num_pairs`。

### DownloadJob

持久化路径：`<output_root>/<task>_<run_id>/.insar_agent/jobs/{job_id}.json`

跟踪后台下载/数据准备任务（RSLC、DEM、Sentinel-1 场景）。

---

## 工作区布局

`insar_create_project(output_root=<path>)` 将 `<path>` 作为顶层目录。共享输入数据（跨 run 复用）
落在 `<output_root>/prepare/`；每次运行的产物落在独立的 `<output_root>/<task>_<timestamp>/`。

### 顶层目录树

```
<output_root>/
  prepare/
    dem/                              # DEM（跨 run 复用）
    safe/                             # Sentinel-1 SAFE/ZIP（跨 run 复用）
    orbits/                           # orbit 文件（跨 run 复用）
    rslc/                             # NISAR RSLC（跨 run 复用）
  <task>_<timestamp>/                 # 每次 insar_run_workflow/prepare_stack 一个，如 d-insar-isce3_20260620T010203Z
    .insar_agent/                     # agent 状态目录
      project.json
      jobs/                           # Job JSON 文件
      progress.log                    # Layer-1 简洁进度日志（watch: tail -f progress.log）
    insar_product/                    # 所有处理产物
      products/                       # GUNW .h5 等核心产品
      scratch/                        # ISCE3/ISCE2 临时文件
      configs/                        # 导出的 runconfig.yaml
      logs/                           # Layer-2 原始引擎日志（{job_id}.log, {job_id}.exitcode）
      stack/                          # stack 批处理 runconfigs + 脚本（Path B）
      network/                        # network 批处理 runconfigs + 脚本（Path B）
      mintpy/                         # MintPy 时序输出
      exports/                        # GeoTIFF 等导出产物
      param_advisor/                  # param-advisor 建议快照
      troposphere/                    # ISCE2 对流层改正产物
```

### 日志两层模型

| 层级 | 路径 | 内容 | 用途 |
|------|------|------|------|
| Layer-1 | `<run>/.insar_agent/progress.log` | 简洁时间戳进度条目 | agent/用户监控：`tail -f progress.log` |
| Layer-2 | `<run>/insar_product/logs/` | 引擎原始输出 | 调试：`{job_id}.log`, `{job_id}.exitcode` |

### 单对 D-InSAR（Path A）

```
<output_root>/
  prepare/
    dem/                              # DEM（复用）
    safe/ 或 rslc/                    # 输入数据（复用）
  d-insar-isce3_20260620T010203Z/    # 任务运行目录
    .insar_agent/
      project.json
      jobs/
      progress.log                    # Layer-1 简洁进度（tail -f 监控）
    insar_product/
      products/                       # GUNW .h5 等产品
      scratch/                        # ISCE3 临时文件
      configs/                        # runconfig.yaml
      logs/                           # Layer-2 原始引擎日志
      param_advisor/                  # param-advisor 输出快照
```

### 批处理 Stack + Network（Path B）

```
<output_root>/
  prepare/
    dem/
    rslc/
  stack-insar-isce3_20260620T010203Z/
    .insar_agent/
      project.json
      jobs/
      progress.log
    insar_product/
      stack/
        runconfigs/                   # 每个 secondary 景一个 YAML
        run_all.sh
        run_parallel.sh
        stack_manifest.csv
        reference_date.txt
      network/
        runconfigs/                   # 每个干涉对一个 YAML
        run_all.sh
        run_parallel.sh
        pair_lists/pairs_selected.txt
        stack_manifest.csv
        runs/{date1}_{date2}/products/*.h5
      logs/                           # Layer-2 批处理日志
```

---

## MCP 接口层

MCP server 通过 FastMCP 注册三类对象：

| 类型 | 数量 | 说明 |
|------|------|------|
| **Tools** | 28 | 源码实际注册的 AI 可调用操作；全部 `@mcp.tool()` |
| **Resources** | 1 + 1 template | `insar://workflow-guide` 为静态 resource；`insar://allowed-fields/{workflow}` 为 resource template |
| **Prompts** | 2 | 预填路径的引导式任务模板 |

详细规范见 [developer-documents/MCP-tools.md](developer-documents/MCP-tools.md)。

> 校准记录：当前 FastMCP 实际注册面与 `insar-mcp-server --describe` 均为
> 28 tools、1 resource、1 resource template、2 prompts。

### Resources

- `insar://workflow-guide` — 主路由 skill 内容（读取 `skills/insar-agent/SKILL.md`，由该 skill 统一维护路由、硬约束与参数顾问入口）
- `insar://allowed-fields/{workflow}` — 指定工作流可写字段的动态列表

### Prompts

- `process_insar_pair` — 单对 RSLC ISCE3 处理的 8 步引导模板
- `process_insar_batch` — 批处理 stack + network 准备的 2 步引导模板

---

## 引擎启动机制

两个引擎均通过 `_launch_detached_shell_job()` 以 **nohup 方式脱离会话**启动：

```python
launcher = (
    f"nohup bash -lc {shlex.quote(shell_command)} "
    f"> {shlex.quote(log_path)} 2>&1 < /dev/null & "
    "printf '%s\\n' \"$!\""
)
```

shell_command 内部包含 exit code 持久化逻辑：
```bash
<engine_cmd>; status=$?; printf '%s' "$status" > <job_id>.exitcode; exit $status
```

| 引擎 | 命令格式 |
|------|---------|
| ISCE3 | `conda run -n {env} --no-capture-output python -m nisar.workflows.{workflow} {runconfig.yaml}` |
| ISCE2 tops | `conda run -n {env} ... topsApp.py [--dostep esd]`（以 `topsApp.xml` 为配置） |
| ISCE2 stack | `conda run -n {env} ... stackSentinel.py {args}`（参数直接传 CLI） |

---

## 进程状态检测（三级降级）

`_refresh_workflow_job_status()` 在每次 `insar_get_job` 调用时执行：

```
1. exitcode 文件（最可靠）
   └── {job_id}.exitcode 由 shell wrapper 原子写入
       exit 0 → done，非 0 → failed

2. PID 存活检查
   ├── os.kill(pid, 0) — 无权限说明进程存在
   └── /proc/{pid}/status 中 State 含 "Z" → 僵尸进程，视为结束

3. 日志末 80 行扫描（兜底）
   ├── WORKFLOW_LOG_FAILURE_PATTERNS：error:, Traceback, Exception:, Killed
   ├── WORKFLOW_LOG_FAILURE_SUBSTRINGS：environmentlocationnotfound, condaerror, …
   └── WORKFLOW_LOG_SUCCESS_MARKERS：workflow finished successfully, …
```

ISCE2 stack 额外要求日志中出现成功标记（`requires_success_marker=True`），因为 stackSentinel.py 多步骤运行 exit 0 不等于全部完成。

---

## Skill 系统与 MCP 的关系

Skills 位于 `skills/` 目录，打包为 Claude Code 插件（`insar-agent-plugin@insar-agent`）。

```
CLAUDE.md（应用节）
  → 调用 insar-agent-plugin:insar-agent skill
    → skills/insar-agent/SKILL.md（路由层）
      Session Bootstrap:
        1. readMcpResource("insar://workflow-guide") — 加载硬约束
        2. 收集 engine/环境等跨切面信息
      Workflow Routing:
        → d-insar-isce3 / stack-insar-isce3 / d-insar-isce2 / stack-insar-isce2
          → 调用 insar_* MCP 工具执行
      Parameter Advisory:
        → param-advisor skill
          → insar-agent-plugin:param-advisor subagent
            → insar_describe_rslc / insar_describe_s1
            → insar_set_processing_param（用户确认后）
            → insar_record_param_advice（存档）
```

**约束层级：**
```
insar-agent skill（会话引导 + 路由）
  → 工作流 skills（步骤排序 + 交互门控）
    → param-advisor skill（参数建议编排）
      → param-advisor subagent（建议生成，仅顾问角色）
        → MCP server 白名单 + 验证器（硬性执行）
```

MCP 工具不验证 skill 委派链路是否被遵守——它只校验参数更新本身。

---

## 参数白名单机制

### 路径类字段（`insar_set_runconfig_value`）

由 `engines/isce3/defaults.py::ALLOWED_SET_FIELDS` 和 `engines/isce2/defaults.py::ALLOWED_SET_FIELDS` 按 workflow 维护允许列表。未在列表中的键返回 `key_not_allowed`。

### 处理参数（`insar_set_processing_param`）

由 YAML 注册表文件维护：
- `engines/isce3/assets/processing_params_insar.yaml`
- `engines/isce2/assets/processing_params_tops.yaml` / `processing_params_stack.yaml`

每条注册表项包含：`key`, `label`, `type`, `valid_values`/`valid_range`/`list_shape`, `risk_level`, `depends_on`。`justification` 字段不能为空或模糊（如 `"better performance"`）——空/模糊字符串会被拒绝。

---

## 处理路径速览

| 路径 | 场景 | 核心工具序列 |
|------|------|-------------|
| **Path A — 单对 D-InSAR（ISCE3）** | 单 RSLC 对 → GUNW | `create_project` → `set_runconfig_value`×N → `[param-advisor]` → `run_workflow` → `get_job`(poll) → `list_outputs` |
| **Path A — 单对 D-InSAR（ISCE2）** | 单 S1 对 → 干涉图 | `create_project` → `set_processing_param`×N → `run_workflow` → `get_job`(poll) |
| **Path B — 批处理（ISCE3）** | 多 RSLC → 干涉图网络 | `prepare_stack` → `run_batch` → `prepare_network` → `run_batch` → `plot_baseline` → `run_mintpy` |
| **Path B — 时序（ISCE2）** | S1 stack → 形变时序 | `create_project`(stack) → `run_workflow` → `run_mintpy_isce2` |

---

## 测试

```bash
pytest                                # 默认套件，排除 real_data 标记
pytest -m real_data tests/integration # 真实数据测试（需手动选择）
pytest --cov=src --cov-report=term-missing  # 覆盖率
```

测试分布：
- `tests/unit/` — 单元测试（不需要 conda 环境或真实数据）
- `tests/integration/` — 集成测试，标记 `real_data`

---

## 知识库来源

| 目录 | 内容 |
|------|------|
| `docs/archive/knowledge-base/tianxiaolong/` | 工作流约束、runconfig 模板、DEM/GeoTIFF 脚本 |
| `docs/archive/knowledge-base/wangshuai/` | stack/network 准备、MintPy 时序、基线可视化脚本 |

引擎层模块保留了上述脚本的核心逻辑，移除了 argparse/sys.argv 入口，改为函数参数；原始文件只做存档。
