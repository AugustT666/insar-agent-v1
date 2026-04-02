# insar-agent 技术路线评估：CLI-Anything 风格 CLI vs MCP

日期：2026-04-02

## 1. 评估目标

本文评估 `insar-agent` 是否应该继续坚持当前的 `MCP-first` 技术路线，还是转向一条以 `CLI-Anything` 思路为代表的 `CLI-first` 路线：先把 ISCE3、MintPy、下载、参数设置、批处理和作业查询统一封装为稳定 CLI，再让 AI agent 通过 shell 调用这些 CLI。

这不是对当前代码实现细节的复盘，而是对项目长期产品形态、开发效率、agent 适配性和领域约束的路线判断。

---

## 2. 项目约束与判断基线

从仓库现有文档可以看出，`insar-agent` 的问题不是“怎样让 agent 随便调几个脚本”，而是“怎样把真实 InSAR 处理知识收敛成稳定、可约束、可恢复、可持续扩展的 agent-native 运行面”。项目当前有几个非常明确的约束：

1. 领域工作流长且有强顺序性。
   Path A 是 `create_project -> set_runconfig_value -> optional describe/tune -> run_workflow -> get_job -> list_outputs`。
   Path B 是 `prepare_stack/network -> run_batch -> get_job -> run_mintpy`。

2. 项目不是单次命令触发，而是有显式状态模型。
   `Project`、`Job`、`BatchJob`、workspace layout、日志路径、输出目录、轮询行为，都是一等公民。

3. 配置修改有严格边界。
   路径字段与 processing 参数是分开的；processing 参数还要经过 whitelist 和技能流程。

4. 长任务与错误恢复是核心，不是附属功能。
   `insar_get_job`、批处理、MintPy、日志回看、失败诊断，都属于主线能力。

5. 项目面向的是 AI 客户端协作，而不是传统终端用户优先。
   README 和 architecture 已经把项目定义为 `MCP-first InSAR orchestration project`，并强调 tools/resources/prompts 的稳定对外接口。

因此，路线选择的核心标准不是“哪条路线更通用”，而是：

- 哪条路线更适合表达结构化工作流
- 哪条路线更适合让 agent 少犯错
- 哪条路线更适合长期维护 InSAR 领域约束
- 哪条路线更适合长任务状态追踪与恢复
- 哪条路线更适合未来接入多个宿主

---

## 3. 路线定义

### 3.1 路线 A：MCP-first

核心思想：把 `insar-agent` 定义为一个 agent-facing 服务，暴露稳定的 MCP tools/resources/prompts；CLI 只保留少量本地运维和诊断入口。

特点：

- 结构化输入输出天然明确
- 工具边界可精确设计
- 可把“允许什么、不允许什么”编码进工具层
- 更适合宿主通过工具选择、资源读取、prompt 模板来完成复杂工作流
- 对长任务、状态机、资源文档、引导模板支持更自然

### 3.2 路线 B：CLI-first（参考 CLI-Anything）

核心思想：先把项目能力做成一组完整 CLI 命令，要求具备：

- 清晰命令层级
- `--help` 自描述
- `--json` 结构化输出
- 适合 shell 编排和 agent 直接调用
- 必要时附带 REPL 或会话状态

然后再由 Claude Code、Codex 或其他 agent 通过终端命令调用这些 CLI，而不是优先通过 MCP。

`CLI-Anything` 官方定位就是把软件转成 “structured, composable, self-describing, agent-first” 的 CLI，并强调 `--help`、`--json`、真实后端调用和 shell 可组合性。这个路线本质上是在说：CLI 可以成为 agent 的通用协议层。

---

## 4. 适配性对比

### 4.1 对你的项目本体，MCP 的结构匹配度更高

`insar-agent` 不是“给某个现有 GUI 软件补一个调用壳”，而是在构建一个新的、领域化的 agent orchestration layer。这里的重点不是把现有软件表面能力暴露出来，而是定义一套经过裁剪、约束、抽象后的领域语义：

- `insar_create_project`
- `insar_set_runconfig_value`
- `insar_set_processing_param`
- `insar_run_workflow`
- `insar_get_job`
- `insar_prepare_stack`
- `insar_run_batch`
- `insar_run_mintpy`

这些接口明显不是底层软件原生命令，而是对领域工作流做过重构后的“任务语义接口”。这类接口最适合 MCP，而不是先退回到 shell 命令拼装。

原因很简单：MCP 工具本来就是“语义动作”，而 CLI 更擅长表达“命令动作”。你的项目里，“创建项目”“设置白名单参数”“轮询 job”这些动作是带业务约束的语义单元，不只是命令。

结论：如果项目目标是“为 agent 提供稳定、低歧义、强约束的 InSAR 处理面”，MCP 的匹配度高于 CLI-first。

### 4.2 如果目标改成“先统一封装底层软件能力”，CLI-first 有明显价值

如果你把目标下沉为：

- 把 ISCE3 / MintPy / 数据下载 / 可视化脚本统一包装成命令
- 让人和 agent 都能直接在终端调用
- 优先解决“可调用性”和“开发速度”
- 暂时不追求 MCP 级别的宿主协议整合

那么 CLI-first 会变得很有吸引力。

它的优点在于：

- 对开发者和终端用户都直观
- shell 里更容易调试
- 容易接入任何支持命令执行的 agent
- 天然支持 `bash`/`make`/脚本编排
- 和现有科研工作流习惯更接近

对于 InSAR 这种强依赖本地环境、conda、文件路径和外部二进制的系统，CLI 作为“底层执行面”其实非常自然。它比直接让 agent 乱写 shell 稳定得多，也比 GUI 自动化靠谱得多。

结论：CLI-first 很适合做“底层执行层”，但不自动意味着它适合做你的“最终对外主接口”。

### 4.3 长任务与状态机：MCP 更容易做成一致协议

你的项目大量能力都不是同步返回：

- workflow 运行数十分钟到数小时
- batch 跑多个 job
- MintPy 运行周期长
- 用户需要统一轮询、日志查看、失败恢复

这些在 MCP 里用统一 `Job` 模型表达，非常自然。agent 看到的是：

- 一个启动工具
- 一个状态查询工具
- 一个输出查询工具

这对 agent 的决策复杂度是友好的。

CLI 当然也能做，但通常会退化成：

- 命令 A 启动并打印 job_id
- 命令 B 查状态
- 命令 C 查日志
- 命令 D 查输出

如果再叠加 workspace 路径、batch_dir、work_dir、不同 workflow 的特殊参数，CLI 命令集合很容易膨胀。对人类终端用户这未必是问题，但对 agent 来说，命令树一旦过深、参数一旦过散，出错率会上升。

结论：在“长流程 + 状态机 + 多工作流共享轮询模型”这一点上，MCP 明显更适合做统一上层协议。

### 4.4 参数约束与防误用：MCP 更强

`insar-agent` 当前一个关键设计点是把“能改什么”做成了显式边界：

- 路径字段用 `insar_set_runconfig_value`
- processing 参数走 `insar_set_processing_param`
- 还叠加了 skill 和 advisory 流程

这类能力在 MCP 工具里很容易强约束，因为工具就是协议面，宿主天然按 schema 调用。

CLI 也能做校验，但 CLI 的天然使用文化是“用户可以拼更多命令、拼更多脚本、绕过更多路径”。只要 CLI 暴露得足够底层，用户和 agent 就会尝试跳过推荐流程，直接调用执行命令。你当然可以限制，但限制的强度通常不如 MCP 调用面自然。

结论：如果你特别看重“约束 agent 不要乱改 processing 参数、不要绕开工作流边界”，MCP 更合适。

### 4.5 跨宿主集成：MCP 更清晰，但 CLI 更通用

这里两者都强，只是方向不同。

MCP 的优势：

- 对 Claude Code、Codex、OpenCode 这类工具调用型宿主更清晰
- resources/prompts/tools 三层接口比单纯 CLI 更丰富
- 宿主能感知工具 schema，而不是只看 `--help`

CLI 的优势：

- 几乎任何 agent、脚本系统、CI、SSH 环境都能调用
- 不需要宿主支持 MCP 协议
- 对人工操作和排障也更友好

结论：如果你追求“最广兼容性”，CLI 更通用；如果你追求“面向 agent 的高质量集成”，MCP 更优雅。

### 4.6 开发与维护成本：单独选任何一边都不是最优

只做 MCP 的风险：

- 人工调试体验不如 CLI 直观
- 非 MCP 宿主复用能力变弱
- 本地集成测试和运维操作可能还要额外补脚本

只做 CLI 的风险：

- 工具面容易变大，参数树容易变深
- prompt/resource/workflow guide 这类 agent 引导资产无天然归宿
- agent 在 shell 中的误调用概率高于 schema 化工具调用
- 未来如果再补 MCP，很可能要重新做一轮“从命令到语义工具”的二次抽象

结论：从长期维护成本看，最稳的不是二选一，而是分层。

---

## 5. 对 CLI-Anything 路线的专门判断

`CLI-Anything` 适合的典型场景是：

- 已有大型软件代码库
- 需要快速生成 agent-friendly CLI 表面
- 重点是覆盖已有功能，而不是重新设计领域语义

而 `insar-agent` 的核心难点不是“如何把某个现成应用完整映射成 CLI”，而是“如何把多个科学处理软件和脚本重组为正确的领域工作流”。这两件事不一样。

对于你的项目，直接把 `CLI-Anything` 当主路线，会有三个风险：

1. 它容易把注意力放在“命令覆盖率”而不是“工作流语义质量”上。
   你的核心价值不在于命令多，而在于把高风险 InSAR 处理步骤抽象成正确的动作边界。

2. 它更像是在统一现有软件表层接口，而你的项目更需要定义新的领域接口。
   `insar-agent` 实际上是 orchestration product，不只是 software wrapper。

3. 它对底层软件调用是好事，但不足以自然承载 skills、workflow-guide、prompt contracts 这些上层 agent 资产。

所以，`CLI-Anything` 的思路对你有启发，但更适合借鉴为“执行层建设方法”，不适合作为整个项目的主产品路线。

---

## 6. 最终建议

### 6.1 主结论

对 `insar-agent` 这个项目，当前 `MCP-first` 技术选型总体是正确的，而且从长期看比 `CLI-first` 更贴合项目目标。

原因不是 MCP 更“先进”，而是它更适合你这个项目真正要解决的问题：

- 稳定的领域语义接口
- 严格的参数和流程约束
- 长任务状态抽象
- 资源与提示模板并存
- 面向 agent 的低歧义调用面

### 6.2 但应当补一层“执行级 CLI”，而不是转向 CLI-first

更合理的路线不是改成 `CLI-first`，而是演进成：

`Engine/Domain Core -> Stable CLI execution layer -> MCP semantic layer`

也就是：

1. 保持 MCP 作为主对外接口和产品定位。
2. 在内部或半公开层补一套高质量 CLI，专门承载：
   - 本地调试
   - 人工运维
   - CI / shell 集成
   - 非 MCP 宿主接入
   - 对底层执行行为的稳定封装
3. MCP 工具尽可能调用同一套 core/CLI 执行能力，而不是各自分叉逻辑。

这条路线能同时吸收两边优点：

- 对 agent：继续用更安全、更语义化的 MCP
- 对开发者和运维：获得更强 CLI 体验
- 对未来平台兼容：保留 shell 通道

### 6.3 对你项目的具体落地建议

建议不要把 CLI 做成“另一套独立产品逻辑”，而是做成 MCP 下面的统一执行面。优先建设的 CLI 能力应包括：

- `project create/get`
- `runconfig get/set/unset`
- `workflow run`
- `job get`
- `outputs list`
- `stack prepare`
- `network prepare`
- `batch run`
- `mintpy run`
- `baseline plot`
- `data download-rslc`
- `data download-dem`

要求：

- 所有命令默认可读，必要时支持 `--json`
- 参数命名和对象命名尽量与 MCP 工具保持一致
- 不把 domain logic 复制到 CLI 层，CLI 只是稳定入口
- 不开放破坏当前安全边界的“万能执行命令”

换句话说，你应该借鉴 `CLI-Anything` 的优点：

- `--help` 自描述
- `--json` 机器可读
- 命令分组清晰
- 易于 shell 调用

但不应该把项目重心从 MCP 语义层转移到 CLI 覆盖率竞赛。

---

## 7. 建议的路线决策

建议采用以下决策：

- 主路线：继续 `MCP-first`
- 辅路线：补“高质量执行级 CLI”
- 不建议：把项目整体重构为 `CLI-first`

一句话总结：

对 `insar-agent`，CLI 应该是 MCP 的执行底座和通用适配层，而不是替代 MCP 的主产品接口。

---

## 8. 参考依据

仓库内依据：

- `README.md`
- `docs/architecture.md`
- `docs/developer-documents/mcp-tools.md`
- `docs/developer-documents/dev-plan.md`
- `src/insar_agent/cli.py`
- `src/insar_agent/mcp/server.py`

外部依据：

- CLI Anything 官方站点：https://clianything.org/
  关键定位包括：one-command CLI generation、`--help` 自描述、`--json` 输出、真实后端调用、agent-first CLI。
