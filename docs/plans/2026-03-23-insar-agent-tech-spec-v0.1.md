# insar-agent 技术方案 v0.1

状态：Draft  
日期：2026-03-23  
范围：V1 / PoC  
默认假设：项目从第一天起就以独立仓库 `insar-agent` 启动，不放在 `cli-anything` 目录树下；首版先支持 `ISCE3`，先做本地 `MCP server`，已有原型仅作为外部参考。

## 1. 背景

目标是开发一个名为 `insar-agent` 的独立项目，作为可被多个 agent 客户端接入的 InSAR 处理能力层，让 `Codex`、`Claude Code`、`OpenCode` 这类支持外部工具接入的客户端，都能以统一方式调用开源遥感处理软件。

首版不追求“一次支持所有软件”，而是按软件逐个接入。当前优先软件为 `ISCE3`，后续可扩展到 `ISCE2`、`GMTSAR` 等。

现阶段有两类外部参考资产可供借鉴，但 `insar-agent` 应从一开始就保持独立仓库、独立包名和独立发布边界：

- 工作流知识摘要：原型仓库中的 `docs/deepwiki-workflows-summary.md`
- ISCE3 状态化 CLI harness 原型：原型仓库中的 `agent-harness/ISCE3.md` 与 `agent-harness/cli_anything/isce3/README.md`

本方案的核心判断是：V1 应该先做 `MCP` 能力层，而不是直接做某一家宿主的原生插件。

## 2. 问题定义

当前 InSAR 开源软件存在以下接入成本：

- 工作流入口分散，通常需要人工查找模块、默认配置、schema 和示例。
- 运行配置复杂，参数层级深，不适合由通用 agent 直接手写。
- 任务耗时长，日志、状态和输出产物需要单独管理。
- 不同 agent 客户端的“插件”机制并不统一，直接做原生插件会增加重复实现。

因此需要一个独立于宿主客户端的执行与编排层，向上暴露稳定的工具接口，向下调用真实的 InSAR 软件。

## 3. 目标与非目标

### 3.1 V1 目标

- 提供一个本地运行的 `MCP server`，让多个 agent 客户端能以统一接口调用 `ISCE3`
- 在独立项目 `insar-agent` 中沉淀项目、配置、执行逻辑，不把运行时依赖绑定到 `cli-anything`
- 参考现有 `cli-anything-isce3` 原型中已验证的项目、配置、执行逻辑，不重复摸索工作流后端
- 支持 `runconfig` 的创建、读取、修改、校验、导出与执行
- 支持长任务的状态查询、日志读取和输出产物定位
- 为后续接入 `ISCE2`、`GMTSAR` 预留 adapter 扩展位

### 3.2 V1 非目标

- 不做图形化桌面 UI、地图交互面板或复杂参数表单
- 不做远程集群调度、Kubernetes、Slurm 等分布式执行
- 不在 V1 中同时支持多个 InSAR 引擎
- 不在 V1 中覆盖所有 NISAR 工作流与全部高级配置项
- 不把“宿主 skill”作为核心依赖；skill 只作为可选增强层

## 4. 为什么优先选择 MCP

`MCP` 在本项目中的角色是“跨 agent 的能力接口”，而不是“简化版插件”。

优先选择 `MCP` 的原因：

- 一个后端可以被多个客户端接入，降低重复开发成本
- 适合封装 InSAR 这类重计算、长任务、强工作流的软件能力
- 能把宿主差异限制在接入层，而不是污染核心执行逻辑
- 可以和独立 CLI 工具共存，形成 `CLI + MCP` 双入口

`MCP` 相对原生插件的主要限制不在算法能力，而在宿主集成深度：

- 强项：工具调用、资源暴露、模板提示、长任务编排
- 弱项：宿主内嵌 UI、复杂交互面板、宿主专属上下文钩子

因此架构上应采取：

- 核心处理能力放在共享后端
- 跨客户端接入通过 `MCP`
- 宿主专属体验通过轻量 skill 或原生插件外壳补充

## 5. 架构总览

```text
+------------------------------+
| Agent Client                 |
| Codex / Claude Code / etc.   |
+--------------+---------------+
               |
               | MCP tools / resources / prompts
               v
+----------------------------------------------+
| insar-agent / insar-mcp-server               |
| - tool handlers                              |
| - prompt/resource registry                   |
| - job manager                                |
| - workspace policy                           |
+------------------+---------------------------+
                   |
                   v
+----------------------------------------------+
| Shared InSAR Core                            |
| - insar_agent.core.project                   |
| - insar_agent.core.session                   |
| - insar_agent.core.config                    |
| - engine adapter interface                   |
+------------------+---------------------------+
                   |
                   v
+----------------------------------------------+
| Engine Adapter: ISCE3                        |
| - insar_agent.engines.isce3                  |
| - default configs / schemas                  |
| - nisar.workflows.<workflow>                 |
| - backend command builder                    |
+------------------+---------------------------+
                   |
                   v
+----------------------------------------------+
| Runtime + Artifacts                          |
| - local conda env                            |
| - project JSON                               |
| - rendered YAML                              |
| - logs / outputs / previews                  |
+----------------------------------------------+
```

## 6. 与参考原型的关系

本方案不建议从零重新摸索后端能力，但也不建议把正式项目直接放进 `cli-anything` 仓库。

更准确地说，现有 `cli-anything-isce3` 应被视为外部参考原型，而不是正式产品的长期宿主。

`insar-agent` 的启动原则应明确为：

- 使用独立 Git 仓库
- 使用独立 Python 包 `insar_agent`
- 使用独立文档目录和发布节奏
- 不在运行时依赖 `cli-anything-isce3` 包或其目录结构
- 只在设计和实现层面借鉴已验证的原型思路

已经具备的能力包括：

- 创建项目：`project new`
- 保存与载入项目：`project save/open`
- 渲染与导出 runconfig：`project render/export-runconfig`
- 读写配置项：`config get/set/unset`
- 探测与执行 workflow：`workflow list/probe/run`
- 会话状态与撤销重做：`session status/undo/redo/history`

独立项目中的 MCP 层应优先直接调用 Python 模块，而不是通过解析 CLI 文本输出做二次封装。目标形态是：

- `insar_agent.core.*` 作为共享业务层
- `insar_agent.cli` 作为命令行入口
- `insar_agent.mcp.server` 作为协议适配层
- `insar_agent.engines.isce3` 作为首个引擎 adapter

这样可以保证：

- 独立项目中的 CLI 与 MCP 复用同一套数据模型
- 测试可以覆盖共享核心，而不是覆盖两套重复逻辑
- 后续接入 `ISCE2` 时只新增 adapter，不用重写整体框架
- 可以参考或摘取现有原型中的实现思路，但不能在两个仓库间形成长期运行时交叉依赖

### 6.1 项目命名

建议命名固定为：

- 项目 / 仓库名：`insar-agent`
- 首个 MCP 服务组件名：`insar-mcp-server`
- Python 包名：`insar_agent`

命名原则：

- 项目名要覆盖未来的 `CLI`、`MCP`、`Web UI` 和多个引擎 adapter
- 组件名可以更具体，明确当前交付物是 `MCP server`
- Python 包名使用标准下划线形式，便于发布和导入

### 6.2 仓库结构建议

独立仓库建议采用如下目录结构：

```text
insar-agent/
  README.md
  pyproject.toml
  docs/
    architecture.md
    workflows/
    decisions/
  src/
    insar_agent/
      cli.py
      core/
        project.py
        session.py
        config.py
        jobs.py
      mcp/
        server.py
        tools/
        resources/
        prompts/
      engines/
        base.py
        isce3/
          adapter.py
          defaults.py
          validator.py
          runner.py
      runtime/
        env.py
        workspace.py
        logging.py
  skills/
    SKILL.md
  examples/
    runconfigs/
  tests/
    unit/
    integration/
    e2e/
```

设计原则：

- `src/insar_agent/core` 保存与具体协议无关的共享能力
- `src/insar_agent/mcp` 只负责协议适配，不直接承载领域逻辑
- `src/insar_agent/engines` 负责多引擎扩展
- `skills/` 作为宿主增强材料保留，但不耦合到核心逻辑
- `docs/decisions/` 用于沉淀后续架构决策记录

### 6.3 文档落位

本文现已迁入 `insar-agent` 仓库。后续如果从“计划稿”进入“正式架构说明”阶段，建议收敛到以下位置之一：

- `docs/architecture.md`
- `docs/decisions/0001-project-scope.md`

原则是：设计文档应跟随正式项目走，并在实现稳定后从阶段性计划稿收敛为正式文档。

## 7. 领域模型

V1 建议统一以下核心对象：

### 7.1 Project

表示一个可持久化的处理项目，保存为 JSON。包含：

- `project_id`
- `name`
- `engine`
- `workflow`
- `runconfig`
- `runconfig_template`
- `created_at`
- `updated_at`
- `workspace_root`

### 7.2 WorkflowTemplate

表示某个引擎支持的默认工作流模板。包含：

- `engine`
- `workflow`
- `default_config_path`
- `schema_path`
- `example_paths`
- `supports_gpu`

### 7.3 Job

表示一次 workflow 执行任务。包含：

- `job_id`
- `project_id`
- `engine`
- `workflow`
- `status`
- `command`
- `submitted_at`
- `started_at`
- `finished_at`
- `log_path`
- `output_paths`

### 7.4 Artifact

表示任务输出，包括：

- 原始 `HDF5`
- 导出的 `YAML`
- 日志文本
- 预览图
- 可选 GeoTIFF

## 8. V1 范围

### 8.1 支持的软件引擎

- 仅支持 `ISCE3`

### 8.2 支持的工作流

默认建议：

- `gslc`
- `insar`

说明：

- `gslc` 适合作为较简单的验证链路
- `insar` 代表主要目标场景
- `focus`、`gcov`、`offsets` 等留到后续版本

如果为了更快落地，也可以把 V1 再缩小为仅支持 `insar`

### 8.3 运行方式

- 本地 `stdio` 模式的 `MCP server`
- 使用当前激活的 `conda` 环境执行 `nisar.workflows`
- 所有任务输出写入受控 workspace 目录

## 9. MCP 能力面设计

V1 建议以“高价值工作流工具”为主，而不是一开始暴露大量细碎低层 API。

### 9.1 建议的 tools

1. `insar_list_engines`
   返回当前服务器已安装或可用的 InSAR 引擎

2. `insar_list_workflows`
   输入 `engine`，返回支持的 workflow 列表与简要说明

3. `insar_create_project`
   创建项目，绑定 `engine`、`workflow` 和 workspace

4. `insar_get_project`
   返回项目元数据、当前配置状态和最近一次任务状态

5. `insar_get_runconfig`
   返回当前项目的 runconfig，支持 `json` 与 `yaml` 视图

6. `insar_set_runconfig_value`
   按路径修改配置，如 `runconfig.groups.worker.gpu_enabled = true`

7. `insar_unset_runconfig_value`
   删除某个配置路径上的值

8. `insar_validate_runconfig`
   执行 schema 与必需字段校验，返回错误列表与建议修复项

9. `insar_export_runconfig`
   导出原生 YAML 到指定目录，供人工复查或直接执行

10. `insar_run_workflow`
    以当前项目配置启动工作流，可选 `dry_run` 或真实执行

11. `insar_get_job_status`
    返回任务状态、退出码、开始结束时间、关键摘要

12. `insar_get_job_logs`
    返回完整日志或 tail

13. `insar_list_outputs`
    返回输出文件、目录、产品类型与推荐查看方式

14. `insar_generate_preview`
    为常见结果生成轻量预览，如 PNG、统计摘要或简单栅格导出

### 9.2 建议的 resources

- `insar://isce3/workflows`
- `insar://isce3/defaults/<workflow>`
- `insar://isce3/schema/<workflow>`
- `insar://isce3/examples/<workflow>`
- `insar://jobs/<job_id>/summary`

### 9.3 建议的 prompts

- `draft_runconfig_from_goal`
- `review_failed_job`
- `suggest_insar_defaults`
- `explain_output_products`

说明：不同客户端对 `resources` 和 `prompts` 的支持程度可能不同，但服务端可以先统一设计，客户端按能力消费。

## 10. 执行流程

典型交互流程如下：

1. agent 调用 `insar_list_engines`
2. agent 调用 `insar_list_workflows(engine="isce3")`
3. agent 调用 `insar_create_project(workflow="insar")`
4. agent 读取默认 runconfig
5. agent 根据用户输入修改路径、DEM、GPU、输出目录等参数
6. agent 调用 `insar_validate_runconfig`
7. agent 调用 `insar_export_runconfig`
8. agent 调用 `insar_run_workflow`
9. agent 轮询 `insar_get_job_status`
10. agent 调用 `insar_get_job_logs` 与 `insar_list_outputs`
11. 如需要，agent 调用 `insar_generate_preview`

## 11. 运行环境与安全策略

V1 需要约束执行面，避免把 `MCP` 变成任意 shell 代理。

### 11.1 环境策略

- 默认使用当前 Python 解释器与当前激活的 `conda` 环境
- 优先支持 CPU 路径，GPU 能力作为可选增强
- 后续版本可增加 `docker` runner，但不作为 V1 必需项

### 11.2 安全策略

- 仅允许调用白名单工作流模块
- 项目工作目录限制在受控 workspace 下
- 禁止任意 shell 命令执行
- 所有输出文件路径必须归档到项目目录中
- 明确区分只读工具和会修改状态的工具

## 12. Skill 与 MCP 的关系

在本项目中：

- `MCP` 负责跨客户端的稳定能力接口
- `skill` 负责在具体宿主中提供更好的提示模板、工作流指导和使用说明

因此建议同时保留两层：

1. `MCP server`
   负责真正执行 InSAR 能力

2. 宿主增强材料
   如 `SKILL.md`、提示模板、使用手册

现有原型中的 `agent-harness/cli_anything/isce3/skills/SKILL.md` 可以作为参考，但正式项目应在独立仓库的 `skills/` 目录中维护自己的宿主增强材料。即使某个客户端不支持 skill，只要支持 `MCP`，核心能力仍然可用。

## 13. 测试与验证

V1 至少需要以下验证层次：

### 13.1 单元测试

- 项目模型读写
- runconfig 路径读写与渲染
- workflow 命令构造
- job 状态机

### 13.2 集成测试

- MCP tool 到共享核心模块的调用链
- 导出 YAML 后能被真实 `nisar.workflows` 接受
- 错误输入时返回可操作的错误信息

### 13.3 端到端验证

- 选取一个最小可运行的 `gslc` 或 `insar` 用例
- 从“创建项目”一路跑到“查看输出”
- 记录耗时、日志位置、产物结构和失败模式

## 14. 里程碑建议

### M0: Server Skeleton

- 创建独立仓库 `insar-agent`
- 将本文纳入 `insar-agent/docs/` 并作为初始技术方案维护
- 初始化 `insar-mcp-server`
- 接通 `insar_list_engines`
- 接通 `insar_list_workflows`
- 接通 `insar_create_project`

### M1: Config Management

- 接通 `get/set/unset/validate/export runconfig`
- 支持把共享核心直接暴露为 MCP tools

### M2: Job Execution

- 接通 `run_workflow`
- 增加 `job status` 与 `job logs`
- 记录输出目录

### M3: Output Interpretation

- 增加 `list_outputs`
- 增加简单预览
- 加入结果解释 prompt / resource

### M4: Second Engine

- 设计通用 `EngineAdapter`
- 评估 `ISCE2` 或 `GMTSAR` 的接入差异

## 15. 已知风险

- 不同客户端对 `MCP` feature 的支持不完全一致
- ISCE3 工作流依赖数据、环境和目录结构，PoC 很容易卡在输入准备
- 长任务如果仅靠同步 `subprocess.run`，后续会限制并发与状态查询能力
- `insar` 工作流真实执行耗时较长，需要先有 `dry_run` 或轻量样例路径

## 16. 需要确认的事项

以下问题不影响先写 v0.1，但需要在实现前拍板：

1. V1 是只支持 `isce3`，还是希望文档里同时预留 `isce2/gmtsar` 的明确接口示例
2. V1 workflow 是支持 `gslc + insar`，还是进一步收缩到只支持 `insar`
3. 首版运行环境是只做 `conda`，还是同时规划 `docker`
4. 首版是否需要“输出预览”，还是先做到“能跑、能查状态、能取日志和文件路径”
5. 首版目标客户端优先级是什么，是 `Codex` 优先，还是从一开始就按多客户端等权设计

## 17. 当前建议

如果没有额外约束，建议按下面的默认路线推进：

- 软件引擎：`ISCE3`
- workflow：`insar` 为主，`gslc` 作为轻量验证链路
- 运行环境：本地 `conda`
- 协议入口：`MCP stdio`
- 项目形态：从 Day 1 使用独立仓库 `insar-agent`
- 核心实现：参考 `cli-anything-isce3` 原型，但在新仓库内独立实现 `insar_agent.core.*`
- 宿主增强：保留 `SKILL.md`，但作为附加层而不是系统中心

这个路线的优点是最容易形成第一个可演示闭环，同时不会把架构锁死在某一个 agent 客户端上。
