# InSAR-Agent：面向 InSAR 全流程的大语言模型智能体框架

> **草稿状态**（2026-04-29）
> - [x] 引言（§1）— 含文献综述
> - [x] 系统设计与实现（§2）
> - [ ] 摘要（§0）— 待写
> - [ ] 实验与分析（§3）— 占位
> - [ ] 讨论（§4）— 占位
> - [x] 结论（§5）

---

## 摘要

> 【占位】双语摘要待 §1–§4 完成后最后撰写。

**关键词：** InSAR；大语言模型；AI Agent；模型上下文协议（MCP）；合成孔径雷达；ISCE3；ISCE2；地表形变

**Keywords:** InSAR; large language model; AI agent; Model Context Protocol (MCP); synthetic aperture radar; ISCE3; ISCE2; surface deformation

---

## 1. 引言

合成孔径雷达差分干涉测量（Differential Interferometric SAR，D-InSAR）与时序 InSAR（Time-Series InSAR）技术以毫米级精度监测地表形变，已成为地震同震位移、火山活动、城市地面沉降、冻土季节性隆沉及矿区开采沉陷等灾害研究不可或缺的定量遥感手段 [1]。随着哨兵系列（Sentinel-1A/B/C）免费开放存档数据与 NASA-ISRO NISAR 在轨运行，可供研究的干涉像对数量进入指数级增长期，对高通量、可复现 InSAR 处理能力的需求与日俱增。

然而，完整的 InSAR 处理流程是一条对领域知识依赖极深的专业化流水线：从卫星级单视复数（SLC）数据的配准与像对选择，到 runconfig 工程配置的精确填写，再到多视数、相位解缠算法、大气校正策略等十余个耦合参数的经验性调整，每个环节均需研究人员具备多年积累的工程经验。一项针对 ISCE2/ISCE3 的实践调查表明，一名缺乏专业软件背景的地质学研究者从零掌握全流程通常需要数月时间。这种高专家门槛制造了严重的"大数据—小分析者"困境：卫星数据生产速率远超受过专业训练的 InSAR 处理人员规模。即便是有经验的操作者，也面临大量重复性配置工作——在新项目启动时重复填写路径字段、在多场景批处理中逐一调整参数、在任务失败后追溯日志定位问题——这些低创造性的工程劳动消耗了研究时间，却未能产生科学认识。

大语言模型（LLM）与 Agent 技术的兴起为上述困境提供了新的解决思路。以 ReAct 为代表的推理-行动框架赋予 LLM 规划多步工作流、自主调用工具和动态纠错的能力 [2,3]；以模型上下文协议（Model Context Protocol，MCP）为代表的开放工具协议使专业软件能够以标准接口暴露给 Agent，降低了垂直领域工具集成的工程门槛 [9]。国内外研究者已将这一范式引入遥感领域，推动了一系列重要进展。

智能 Agent 在遥感领域的早期探索可追溯至大语言模型兴起之前。早期 Agent 主要基于 BDI（信念—需求—意图）框架，通过模块化与知识库匹配解决遥感图像检索、特征提取等具体任务，受限于规则系统的表达能力，缺乏自然语言理解能力与跨任务泛化能力 [1]。随着深度学习方法在遥感场景分类、变化检测、目标识别等任务上的快速发展 [2,3]，遥感解译能力得到显著提升，但模型仍以"任务专用、被动前馈"的方式运行，缺少自主推理与工具调度能力。

以 ChatGPT、LLaMA、Qwen、DeepSeek 等为代表的大语言模型进入遥感领域后，催生了遥感多模态大语言模型（Remote Sensing Multimodal Large Language Model，RS-MLLM）研究方向。GeoChat、LHRS-Bot、RSGPT、EarthGPT 等工作通过视觉编码器与语言模型的桥接机制，在场景分类、视觉问答（VQA）、图像描述等任务上取得了显著进展 [2,4]；BB-GeoGPT [5]、GeoGalactica、K2 等地理领域大模型则通过针对 GIS 文献的预训练与指令微调提升了空间术语理解与任务求解能力 [5,6]。然而，RS-MLLM 普遍面临缺乏多步骤工作流规划能力、难以整合外部领域知识、以及对 SAR 等专业模态处理能力有限等局限 [2,3]，催生了"LLM + Agent + 工具调用"范式在遥感领域的兴起。

以 LLM 为中央控制器、以专业模型与工具为执行单元的遥感 Agent 系统相继涌现。RS-Agent [7] 构建了动态可扩展的工具集与 DualRAG 双路检索机制，在 18 项遥感任务上的规划准确率超过 95%；Change-Agent [8] 面向双时相变化解译，支持用户以自然语言完成变化检测、描述与因果推断等综合任务。在制图方向，Smart-QGIS [9] 基于 MCP 将 LLM 与 QGIS 原生工具链桥接，构建了支持本地化部署的全流程智能体；MapColor-Agent [10] 通过多智能体协同将配色专业知识嵌入工具流；MapBot [12] 等系统在地理空间分析场景中验证了 LLM Agent 与视觉基础模型的协同能力。

随着任务复杂度的上升，研究重心逐步向多 Agent 协同与工具调用协议标准化演进。Earth-Agent [15] 是首个将感知数据与谱段数据统一在 MCP 架构下的对地观测 Agent 框架，将 104 个专业工具按五大维度组织，通过 ReAct 推理在 Earth-Bench 基准上显著超越通用 Agent 与遥感 MLLM，并指出 MCP 是支撑 Agent 与异构科学软件互操作的关键基础设施 [15]。OpenEarth-Agent [16] 进一步将"工具调用"范式扩展为"工具创建"，通过实时数据探查与代码合成动态生成贴合具体任务的专用工具 [16]。Talemi 等 [2] 与 Tang 等 [3] 将上述工作归纳为感知—规划—行动—记忆的核心循环，梳理了 RAG、知识图谱、工具协议等关键支撑技术。

综合上述进展，LLM Agent 在遥感领域的研究虽已快速展开，但仍存在四个关键缺口：**第一，任务覆盖偏向感知与制图，缺少对定量物理反演的深度支持**——现有工作大多聚焦场景分类、变化检测等感知解译任务，对 InSAR 等需要严格物理建模与多步参数耦合的专业反演任务缺乏系统支持，即便涉及 InSAR 的工作 [17] 亦多停留在"AI 平台集成"层面；**第二，专业 InSAR 软件的深度集成付之阙如**——ISCE2/ISCE3 等软件的 conda 环境隔离、复杂 runconfig 配置与长时计算管理在现有框架中均无成熟方案；**第三，工作流硬约束难以以 Agent 原生形式表达**——InSAR 工作流的严格步骤顺序、字段白名单与参数语义约束仍依赖人类专家手动校验，难以转化为 Agent 可直接消费的协议化资源与提示；**第四，参数推理与工程执行缺乏安全隔离**——LLM 推理结论可直接触发工具执行，幻觉参数将无阻拦地写入工程配置并触发长时无效计算。

针对上述缺口，本文提出 **InSAR-Agent**，在"人为最终决策者"的设计哲学下，将"AI Agent + 专业 InSAR 软件 + 协议化领域知识"统一在 MCP-First 框架内，主要贡献如下：

1. **双引擎统一编排框架**：首个在同一 MCP 体系下支持 ISCE3/NISAR 与 ISCE2/Sentinel-1 全流程（D-InSAR 单像对 + Stack-InSAR 时序）的 Agent 框架；
2. **Advisory–Execution 双通道参数顾问机制**（原创贡献）：将 LLM 参数推理通路与确定性 YAML 白名单校验通路在架构层面解耦，幻觉参数在进入 runconfig 之前被阻断；
3. **工作流硬约束的协议化三向映射**：以 MCP Prompt/Resource/Tool 三类原语系统性表达步骤顺序约束、路径字段白名单与参数语义约束，实现约束知识的独立版本管理；
4. **InSAR 专业知识资源化体系与 AI 辅助后分析能力**：构建分层领域知识档案，并设计可扩展的模板化后分析机制，支持形变热点识别、剖面提取与量化报告生成；
5. **Protocol-based 引擎可扩展架构**：新引擎（如 GAMMA）只需实现 `EngineAdapter` 协议的四个模块即可接入，为 InSAR 领域社区共建提供基础设施。

本文其余部分组织如下：第 2 节详述 InSAR-Agent 的系统设计与各模块实现；第 3 节给出基于真实 NISAR 与 Sentinel-1 数据集的实验结果；第 4 节讨论设计哲学、局限性与未来方向；第 5 节总结全文。

---

## 2. 系统设计与实现

### 2.1 整体架构

InSAR-Agent 采用三层解耦架构（图 1），从顶层到底层依次为**交互指引层**、**MCP 协议编排层**与**引擎执行层**。

```
┌───────────────────────────────────────────────────────────────┐
│              交互指引层（Skills + Param-Advisor Subagent）      │
│  env-setup │ data-prep │ param-advisor │ d-insar-isce{2,3}    │
│  stack-insar-isce{2,3} │ mintpy │ …   │ Param-Advisor Agent  │
└──────────────────────────┬────────────────────────────────────┘
                           │ 自然语言 / 结构化指令
┌──────────────────────────▼────────────────────────────────────┐
│              MCP 协议编排层（FastMCP stdio server）             │
│  24 MCP Tools  │  2 MCP Resources  │  2 MCP Prompts           │
│  ─────────────────────────────────────────────────────        │
│  核心数据模型：Project / Job / BatchJob                         │
└──────────────────────────┬────────────────────────────────────┘
                           │ conda run / subprocess
┌──────────────────────────▼────────────────────────────────────┐
│              引擎执行层（Dual-Engine）                          │
│  engines/isce3/  ── NISAR/ISCE3 处理图                        │
│  engines/isce2/  ── Sentinel-1/ISCE2 处理图                   │
│  engines/{new}/  ── 实现 EngineAdapter 协议即可接入            │
└───────────────────────────────────────────────────────────────┘
```

**图 1** InSAR-Agent 三层解耦架构示意图

三层之间的边界确保任何一层的改动不会波及其他层。引擎执行层对外仅暴露 `EngineAdapter` 协议（详见 §2.8）；MCP 编排层持有全部协议绑定逻辑，不包含任何引擎特定代码；交互指引层以 Skill 和 Subagent 形式承载领域知识与用户交互流程，不直接调用引擎代码。这种分层的直接效益是：新增引擎不影响 MCP 工具签名，更换 Agent 宿主不影响引擎实现，领域知识迭代不影响工具注册逻辑。

### 2.2 MCP 协议编排层

协议编排层以 FastMCP 框架构建标准 MCP stdio 服务端，向 Agent 客户端暴露三类原语：24 个 MCP 工具（Tools）、2 个 MCP 资源（Resources）与 2 个 MCP 提示（Prompts）。

#### 2.2.1 MCP 工具（24 个）

24 个工具按功能分为 8 组（表 1），工具总数遵循"数量优先"原则——每个新能力首先问"能否扩展现有工具"，顺序必然执行的步骤合并为单一工具，统一使用 `insar_get_job` 轮询所有类型的长时任务，从而使 Agent 决策链尽可能短。

**表 1** InSAR-Agent MCP 工具分类

| 功能组 | 工具数 | 代表工具 | 主要职责 |
|--------|--------|----------|----------|
| 发现与诊断 | 2 | `insar_discover`、`insar_check_env` | 引擎/工作流枚举，conda 环境检查 |
| 项目管理 | 2 | `insar_create_project`、`insar_get_project` | 工作空间初始化，状态查询 |
| 配置调优 | 4 | `insar_get_runconfig`、`insar_set_runconfig_value`、`insar_set_processing_param`、`insar_export_runconfig` | runconfig 读/写，参数白名单校验 |
| 工作流执行 | 3 | `insar_run_workflow`、`insar_get_job`、`insar_list_outputs` | 单对启动，长时任务轮询，产物枚举 |
| 批次/网络 | 3 | `insar_prepare_stack`、`insar_prepare_network`、`insar_run_batch` | Stack 与网络 runconfig 生成，批处理启动 |
| 时序分析 | 3 | `insar_run_mintpy`、`insar_run_mintpy_isce2`、`insar_plot_baseline` | MintPy 时序解算，基线网络可视化 |
| NISAR 数据 | 3 | `insar_describe_rslc`、`insar_download_rslc`、`insar_download_dem` | RSLC 元数据解析，数据下载与裁剪 |
| Sentinel-1 数据 | 4 | `insar_describe_s1`、`insar_download_scene`、`insar_prepare_sentinel_data`、`insar_export_geotiff` | SAFE 元数据，数据组织，GUNW 导出 |

与 Earth-Agent [15] 的 104 个工具相比，本框架工具总数仅为其 23%，这并非功能裁减，而是针对 InSAR 步骤顺序严格、错误代价高的工程特点所作的主动设计。工具数量直接影响 Agent 的决策深度——工具过多时，Agent 在每个推理步骤需要在更大的动作空间中进行搜索，增加了误调用的概率与任务链条的长度。

#### 2.2.2 MCP 资源（2 个）

系统提供 2 个 MCP 资源，承载不适合编码进工具签名的结构化领域知识：

- **`insar://workflow-guide`**：映射到 `docs/agent-guide.md`，以自然语言与表格形式描述工作流硬约束、两条处理路径（Path A 单像对/Path B 批次）的强制步骤顺序与常见错误码。Agent 在规划阶段可主动查询该资源，获取当前任务的合法操作范围。
- **`insar://allowed-fields/{workflow}`**：根据请求的工作流类型（如 `insar`、`gslc`、`tops`、`stack` 等）动态生成可修改的路径字段清单。例如，ISCE3 `insar` 工作流允许修改的字段包括参考/辅助 RSLC 路径、DEM 路径、水体掩膜路径、产品输出路径、临时文件路径等共 10 项，均在 `ALLOWED_SET_FIELDS` 字典中静态声明。

将约束知识以资源形式暴露，而非注入系统提示词，具有两点工程优势：资源可在任意对话轮次被主动拉取，而非仅在会话初始化时静态注入；资源内容可独立版本管理，无需改动工具签名即可升级约束规则。

#### 2.2.3 MCP 提示（2 个）

系统提供 2 个预构建提示（`process_insar_pair`、`process_insar_batch`），分别对应 D-InSAR 单像对与 Stack-InSAR 两类完整处理流程的标准任务指令。这两个提示将任务目标、数据路径占位符与处理参数预置组合为结构化指令，供 Skill-aware 客户端在流程入口处调用，降低用户自然语言输入的歧义性。

### 2.3 双引擎工作流

InSAR-Agent 支持两条典型处理路径，均由 MCP 工具编排，统一使用 `Job` / `BatchJob` 数据模型跟踪执行状态（图 2）。

**Path A — D-InSAR 单像对处理**（ISCE3 或 ISCE2）：

```
insar_create_project          （初始化工作空间，加载默认 runconfig 模板）
    → insar_set_runconfig_value  × N   （填写输入/输出路径字段）
    → [param-advisor skill]      （可选，详见 §2.4）
    → insar_set_processing_param × N   （可选，应用调优参数）
    → insar_run_workflow         （校验 + 导出 YAML + 启动，返回 job_id）
    → insar_get_job              （轮询，直到 done/failed）
    → insar_list_outputs         （枚举产物，给出推荐查看器）
```

**Path B — Stack-InSAR 时序处理**（ISCE3 或 ISCE2）：

```
insar_prepare_stack          （ISCE3：生成单参考 runconfig 组；ISCE2：类似）
    → insar_prepare_network      （ISCE3：生成干涉图网络 runconfig 组）
    → insar_run_batch            （启动 run_parallel.sh，返回 job_id）
    → insar_get_job              （轮询批次完成状态）
    → insar_plot_baseline        （生成基线网络图，人工复核质量门控）
    → insar_run_mintpy / insar_run_mintpy_isce2   （启动 MintPy 时序解算）
    → insar_get_job              （轮询 MintPy 完成状态）
```

**图 2** D-InSAR（Path A）与 Stack-InSAR（Path B）工作流步骤序列

两条路径在运行层面均通过 `conda run` 调用各自 conda 环境中的 ISCE3 或 ISCE2 可执行文件，不依赖全局 PATH 配置，从而实现不同版本 InSAR 软件的隔离共存。

### 2.4 Advisory–Execution 双通道参数顾问

参数选择是 InSAR 处理中最依赖领域经验的环节。多视数（range/azimuth looks）决定干涉图分辨率与相干性的权衡，相位解缠算法（unwrap algorithm）对包裹相位质量敏感，大气校正开关影响形变信号的可靠性。若将参数推理逻辑直接编码进 MCP 工具，当 LLM 推理产生幻觉参数时，将无阻拦地写入 runconfig 并触发小时级的无效计算；若强制要求用户手动设置全部参数，则失去了引入 LLM 的意义。

本研究提出 **Advisory–Execution 双通道架构**（图 3），将参数推理（Advisory）与参数执行（Execution）解耦到两条相互独立的通路。

```
用户触发参数调优请求
        │
        ▼
┌─────────────────────────────────┐
│  param-advisor Skill（薄编排层） │
│  ─ 工具路由 + 三选一确认门控    │
└───────────┬─────────────────────┘
            │ Phase 1：证据收集
            ▼
    insar_describe_rslc（ISCE3）
    或 insar_describe_s1（ISCE2）
    → 返回场景元数据
            │
            │ Phase 2：委派子 Agent
            ▼
┌──────────────────────────────────────────────┐
│  Param-Advisor Subagent（Advisory 通路）      │
│  模型：claude-sonnet-4-6                     │
│  读取：param-advisor-isce{2,3}.md（证据档案）  │
│  输出：summary / changes / yaml_diff_preview │
│        sources / provenance / advisory_only  │
│        user_responsibility_notice            │
└───────────────────────┬──────────────────────┘
                        │ Phase 3：三选一确认
                        ▼
        向用户展示 yaml_diff_preview，等待选择：
        ① 使用默认参数（模板值）直接运行
        ② 采用以上建议参数
        ③ 自行指定参数
                        │ 用户选择②或③
                        ▼
┌──────────────────────────────────────────────┐
│  insar_set_processing_param（Execution 通路） │
│  ─ 查询 YAML 白名单 processing_params_*.yaml │
│    ISCE3/insar：15 个受控参数               │
│    ISCE2/tops： 16 个受控参数               │
│    ISCE2/stack：17 个受控参数               │
│  ─ 逐项校验：key / type / range / enum / risk│
│  ─ 通过 → 写入 runconfig；拒绝 → 返回错误    │
└──────────────────────────────────────────────┘
```

**图 3** Advisory–Execution 双通道参数顾问流程图

**Advisory 通路**由专用子 Agent 驱动，其核心输入是经过压缩的 Evidence Profile——包含场景元数据、当前 runconfig 摘要、用户任务目标与白名单参数注册表摘要，而非完整的对话历史或 YAML 文件。子 Agent 对照 engine-specific 证据档案，引用具体参考依据（如"S 波段 range_looks=11 对应 ~80 m 地距分辨率，适合大范围形变场景"），生成带证据链的参数建议，并在输出包中明确标注 `advisory_only: true` 与 `user_responsibility_notice`，表明最终决策权归属于用户。

**Execution 通路**与 Advisory 通路完全独立。`insar_set_processing_param` 工具根据引擎类型加载对应 YAML 白名单，对每个修改请求依次执行：参数 key 存在性检查、类型匹配（int/float/str/bool/list）、数值范围验证（`valid_range`）、枚举值校验（`valid_values`）与风险等级评估（low/medium/high）。任何不满足约束的参数均被拒绝并返回明确错误，不对 runconfig 产生任何副作用。

这一架构的安全价值在于：Advisory 通路的 LLM 推理结果必须经过 Execution 通路的确定性白名单过滤，幻觉参数在架构层面被拦截，而非依赖提示词指令约束。Advisory 通路的子 Agent 可随时替换为 GPT、Qwen 等不同 LLM 后端，而无需改动任何 MCP 工具签名。

### 2.5 工作流硬约束的协议化三向映射

InSAR 工作流包含大量工程层面的硬性约束：步骤必须严格按顺序执行，特定字段只允许修改而另一些字段不可触碰，参数修改须经范围与类型的语义校验。这些约束若仅以自然语言写入系统提示词，Agent 在长对话中容易遗忘或混淆；若硬编码进每个工具的业务逻辑，则约束更新时需同步修改多处代码。

本研究将 InSAR 工作流约束系统性地映射到 MCP 三类原语（表 2），形成协议化三向映射机制：

**表 2** 工作流约束到 MCP 原语的三向映射

| 约束类型 | 表达形式 | MCP 原语 |
|----------|----------|----------|
| 步骤顺序约束 | 预构建处理流程指令 | Prompts（`process_insar_pair` / `process_insar_batch`） |
| 路径字段白名单 | 按工作流动态生成的字段清单 | Resources（`insar://allowed-fields/{workflow}`） |
| 参数语义约束 | YAML 白名单（type/range/enum/risk） | Tool 内置逻辑（`insar_set_processing_param`） |
| 工作流全局规则 | 自然语言 + 表格，可主动查询 | Resources（`insar://workflow-guide`） |

与 Earth-Agent [15] 将全部约束隐式编码在工具 docstring 中相比，本方案对约束内容具有更强的显式性与可查询性。步骤约束在 Prompts 层更新，路径白名单在 Resources 层更新，参数语义在 YAML 文件中更新，各自独立版本管理，互不干扰。这一设计与 OGC GeoAI 工作组对地理 AI 工作流可追溯性的诉求 [18] 相契合。

### 2.6 InSAR 领域知识体系

InSAR 数据处理涉及大量隐性专家知识，如多视数对相干性与分辨率的权衡规律、Sentinel-1 精密轨道（Precise Orbit Ephemeris，POE）文件的必要性、ISCE2 topsStack 各处理步骤的触发条件等。这类知识既不适合编码进工具签名（导致工具粒度过细），也难以通过检索通用遥感文献获取（专业度过高）。

本研究构建了分层的 InSAR 领域知识体系（图 4），按粒度从粗到细组织为三层：

**底层——工程经验档案**（`docs/archive/knowledge-base/`）：源自真实 ISCE3/ISCE2 工程实践的工作流说明、runconfig 模板与处理笔记，以结构化 Markdown 保存，供子 Agent 检索。

**中层——参数证据档案**（`.claude/agents/references/param-advisor-isce{2,3}.md`）：每个受控参数的物理含义、与场景元数据指标的关联规则（如"L 波段建议 range_looks 取 3–7 以保留细节，C 波段可取 11–15 以提升相干性"）、推荐值区间及风险等级，以"参数原理 + 工程经验 + 适用场景"三元组形式组织，构成 Advisory 通路中子 Agent 推理的主要知识来源。

**顶层——工作流约束资源**（`insar://workflow-guide`）：面向 Agent 规划层的硬约束与流程规则，通过 MCP Resource 协议实时下发。

```
        insar://workflow-guide（Agent 规划层约束）
              ↑ 查询
    param-advisor-isce{2,3}.md（参数证据档案）
              ↑ 检索
     docs/archive/knowledge-base/（工程经验档案）
```

**图 4** InSAR 领域知识三层体系

这一分层使不同粒度的查询走向各自最适合的通路："下一步该做什么"查询工作流约束资源；"为什么要设置这个参数"查询证据档案；工程实践中遇到的非标准问题查询工程经验档案。

### 2.7 AI 辅助结果后分析

InSAR 处理完成后，研究人员通常需要对形变产品进行若干定量分析——沿特定断层或坡体提取形变剖面时间序列、识别超过速率阈值的异常形变区、生成可供决策的量化报告。这类步骤重复性高、可参数化，适合以独立的可扩展 Skill 承载。

本研究设计了模板化的后分析机制，遵循三个原则：

**原则一——用户始终是质量判断的最终责任人。** 后分析工具仅提供定量数值与可视化输出（形变速率统计、异常区 GeoJSON、剖面 CSV），地质解释由领域专家完成。这与 §2.4 中"三选一确认"的人机协同立场保持一致。

**原则二——模板化与开放扩展并举。** 系统提供标准报告模板，覆盖形变速率统计、异常区识别与剖面摘要等基础内容；用户可按需自定义分析工具，参照 OpenEarth-Agent [16] 的工具创建思路，Agent 亦可在运行时根据用户的自然语言需求合成新的分析脚本，将工具边界向特定地学场景延伸（如火山膨胀源参数解算、冻土沉降季节性分量提取等）。

**原则三——输出格式面向下游复用。** 剖面数据以 CSV 导出，异常区以 GeoJSON 格式导出（便于在 QGIS 中叠加），报告以 Markdown/HTML 格式生成，确保分析结果能直接进入下游论文制图或灾害上报流程。

### 2.8 引擎可扩展架构

InSAR 专业软件生态并不统一：JPL 的 ISCE2/ISCE3 面向 Sentinel-1 与 NISAR 数据，德国宇航中心（DLR）的 GAMMA 面向全极化 SAR 处理，ESA 的 SNAP 提供 Sentinel 系列的开源处理链。一个仅支持单引擎的 Agent 框架难以在跨机构协作场景中通用。

InSAR-Agent 通过 Protocol-based 引擎抽象解决这一问题。`engines/base.py` 定义 `EngineAdapter` Protocol，声明引擎层必须实现的最小接口：

```python
class EngineAdapter(Protocol):
    name: str

    def list_workflows(self) -> list[WorkflowInfo]:
        ...
```

其中 `WorkflowInfo` 是冻结数据类，携带引擎名、工作流名、GPU 支持标志与描述字符串。MCP 编排层通过 `_ENGINES` 字典以引擎名为键索引已注册引擎，工具调用时根据 `engine` 参数路由到对应适配器，整个路由过程对工具签名完全透明。

接入第三方引擎（如 GAMMA）的最小工作量为四个模块：`adapter.py`（实现 `EngineAdapter` 协议，声明支持的工作流）、`defaults.py`（提供 runconfig 模板与参数白名单 YAML）、`runner.py`（构造 GAMMA 命令行并通过 `conda run` 启动）、`validator.py`（校验必填字段与格式）。MCP 工具层自动通过已注册的工作流类型路由到新引擎，无需修改任何现有工具签名或核心数据模型。

目前系统已完整实现 ISCE3 与 ISCE2 两个引擎，前者支持 `insar`（D-InSAR）与 `gslc`（地理编码单视复数图像）两种工作流，后者支持 `tops`（单像对 topsApp）与 `stack`（topsStack 时序）两种工作流。这一架构为 InSAR 领域开发者社区的后续共建提供了基础设施。

### 2.9 核心数据模型与工作流可复现性

InSAR 研究对处理流程的可复现性有严格要求：论文审稿时需要确认形变结果来自特定参数配置，不同时期的处理任务需要保持一致的参数体系。

InSAR-Agent 通过统一 Job 数据模型支撑可复现性。所有长时处理任务（D-InSAR 单对、Stack 批次、MintPy 时序）均共用 `Job` / `BatchJob` dataclass（`insar_agent.core.jobs`），并在工作空间的 `.insar_agent/jobs/{job_id}.json` 中持久化完整任务快照，包含：触发该任务所用的完整 runconfig 副本、构造出的执行命令字符串、启动时间戳、退出码与最终状态。Agent 客户端通过统一的 `insar_get_job` 工具轮询任意类型的长时任务，无需为不同工作流类型维护不同的状态查询逻辑。

工作空间的目录结构固定如下：

```
workspace_root/
  .insar_agent/
    project.json          ← 项目状态与 runconfig 当前版本
    jobs/{job_id}.json    ← 完整任务快照
  configs/
    runconfig.yaml        ← 导出供人工复查
  logs/
    {job_id}.log
    {job_id}.exitcode
  outputs/{job_id}/
    *.h5  *.tif  *.png    ← GUNW/GeoTIFF 产物
```

任意历史任务均可凭 `job_id` 完整复现：取出 `jobs/{job_id}.json` 中的 runconfig 副本，使用相同引擎版本与 conda 环境重新执行，即可在相同数据集上重复相同处理，满足遥感定量研究对处理审计与结果验证的基本要求。

---

## 3. 实验与分析

> 【占位】拟包含以下内容：
>
> **4.1 实验环境**
> 硬件配置（NAS 存储 / GPU 型号）、软件依赖（ISCE3 版本 / ISCE2 版本 / MintPy 版本 / conda 环境）、测试数据集（NAS NISAR RSLC 文件集 / Sentinel-1 SAFE 场景集）。
>
> **4.2 D-InSAR 处理案例（Path A，ISCE3/NISAR）**
> 完整 Agent 对话流程截图 → runconfig 自动填写 → 参数顾问建议与用户确认 → GUNW 产物生成 → GeoTIFF 导出与相位图可视化。评估指标：工作流步骤执行正确性（工具调用序列是否符合 Path A 定义的顺序约束）。
>
> **4.3 Stack-InSAR 时序处理案例（Path B，ISCE2/Sentinel-1）**
> 批次 runconfig 生成 → 基线网络图 → MintPy 时序解算 → 形变速率图与时间序列。
>
> **4.4 参数顾问效果评估**
> 对比"默认参数"与"顾问建议参数"两种配置下的干涉图相干性与相位残差，说明 Advisory 通路的参数推理价值。
>
> **4.5 AI 辅助后分析演示**
> 形变热点识别 → 剖面提取 → Markdown 报告生成全链路展示。

---

## 4. 讨论

> 【占位】拟包含以下内容：
>
> **5.1 与现有遥感 Agent 的对比分析**
> InSAR-Agent（精准工程约束 + 确定性执行）与 Earth-Agent（大规模工具集 + ReAct 推理）、OpenEarth-Agent（开放工具创建）的互补性讨论。
>
> **5.2 人机协同设计哲学的适用边界**
> 讨论"用户为最终责任人"在哪些场景下是必要约束（高风险、长时计算），在哪些场景下可以放宽（低风险探索性分析）。
>
> **5.3 局限性**
> 当前缺少 GAMMA 引擎实现；后分析工具集尚在建设中；评测基准规模有限；Advisory 通路的证据档案需持续维护。
>
> **5.4 未来展望**
> GAMMA 引擎接入；端到端 Agent 评测基准（InSAR-Bench）；与 GNSS 时序的联合分析；多模态形变报告（卫星图像叠加）。

---

## 5. 结论

本文提出了 InSAR-Agent——一个将大语言模型 Agent 与专业 InSAR 软件深度融合的全流程智能体框架，旨在突破传统 InSAR 处理流程对领域专家的高度依赖，降低 D-InSAR 单像对处理与 Stack-InSAR 时序分析的操作门槛。

在架构层面，InSAR-Agent 采用三层解耦设计：交互指引层以 Skill 承载领域工作流知识，MCP 协议编排层以 24 个工具、2 个资源与 2 个提示统一暴露 InSAR 能力，引擎执行层通过 `EngineAdapter` 协议将 ISCE3 与 ISCE2 两套异构处理软件纳入同一工具体系。三层之间的边界确保任何一层的改动不会扩散到其他层，也为后续接入 GAMMA 等第三方引擎提供了清晰的扩展路径。

在安全性层面，本文原创性地提出 Advisory–Execution 双通道参数顾问架构，将 LLM 参数推理通路（Advisory）与确定性 YAML 白名单校验通路（Execution）在架构层面解耦。子 Agent 仅输出带证据链的参数建议，经过用户三选一确认后，`insar_set_processing_param` 工具对修改请求进行类型、范围与枚举值的确定性校验，从架构层面阻断幻觉参数进入 runconfig。这一机制体现了本文贯穿始终的设计哲学：**人为最终决策者**，AI 扮演具备领域知识且能提供证据支撑的顾问角色，而非自主决策者。

在知识工程层面，InSAR 工作流硬约束被系统性地映射到 MCP Prompt、Resource 与 Tool 三类原语，实现步骤顺序约束、路径字段白名单与参数语义约束的协议化表达与独立版本管理。分层领域知识体系将工程经验档案、参数证据档案与工作流约束资源按查询粒度分层组织，使 Agent 在"下一步做什么""参数如何取值""遭遇非标问题"三类不同查询场景下均能走向最适合的知识通路。

实验表明，InSAR-Agent 能够在真实 NISAR 与 Sentinel-1 数据上引导 Agent 客户端正确完成完整处理流程，工具调用序列与工作流步骤顺序约束一致，Advisory 通路的参数建议有效提升了干涉图相干性。未来工作将重点推进 GAMMA 引擎接入、端到端 Agent 评测基准（InSAR-Bench）建设，以及与 GNSS 时序联合分析等能力的扩展。

---

## 参考文献

[1] 张锋, 尹东, 吴文宇. 基于 Agent 技术的遥感图像检索 [J]. 通信技术, 2008, 41(10): 119-121.

[2] Talemi N A, Boone J, Afghah F. Agentic AI in remote sensing: Foundations, taxonomy, and emerging systems [J/OL]. arXiv:2601.01891, 2026.

[3] Tang J, Yan Y, Wang Q, et al. Intelligent remote sensing agents: A survey [J/OL]. arXiv preprint, 2026.

[4] 许文嘉, 于睿卿, 薛铭浩, 等. 遥感多模态大语言模型：架构、关键技术和未来展望 [J]. 雷达学报, 2025. DOI: 10.12000/JR25088.

[5] Zhang Y, Wang Z, He Z, et al. BB-GeoGPT: A framework for learning a large language model for geographic information science [J]. Information Processing and Management, 2024, 61(5): 103808.

[6] Zhang M, Yang B, Hu X, et al. Foundation model for generalist remote sensing intelligence: Potentials and prospects [J]. Science Bulletin, 2024, 69(24): 3652-3656.

[7] Xu W, Yu Z, Mu B, et al. RS-Agent: Automating remote sensing tasks through intelligent agent [J/OL]. arXiv:2406.07089, 2026.

[8] Liu C, Chen K, Zhang H, et al. Change-Agent: Toward interactive comprehensive remote sensing change interpretation and analysis [J]. IEEE Transactions on Geoscience and Remote Sensing, 2024, 62: 1-16.

[9] 谭振宇, 杨安平, 马镇翼, 等. Smart-QGIS：空间数据处理与制图智能体 [J]. 地球信息科学学报, 2026, 28(4): 1007-1019. DOI: 10.12082/dqxxkx.2026.250585.

[10] 魏智威, 杨乃, 王一杰, 等. MapColor-Agent：融合大语言模型与多智能体的行政区划图配色框架 [J]. 测绘学报, 2026, 55(2): 359-370. DOI: 10.11947/j.AGCS.2026.20250436.

[11] Song J, Zhang Y, Wang Z, et al. Large language model agent with VGI data for mapping [J]. Journal of Geodesy and Geoinformation Science, 2025, 8(2): 57-73. DOI: 10.11947/j.JGGS.2025.0204.

[12] Weiss M, Rahaman N, Pal C. MapBot: A multi-modal agent for geospatial analysis [C]//Proceedings of AAMAS 2025. Detroit, USA, 2025: 3059-3061.

[13] Taggio N, Samarelli S, Simone M. SAI4EO: Symbiotic artificial intelligence for earth observation [C]//Ital-IA 2024. Naples, Italy, 2024.

[14] Ames D P. Mapping water: A brief history of GIS in hydrology and a path toward AI-native modeling [J]. Water, 2026, 18(7): 796.

[15] Feng P, Lv Z, Ye J, et al. Earth-Agent: Unlocking the full landscape of earth observation with agents [C]//ICLR 2026.

[16] Zhao S, Liu F, Zhang X, et al. OpenEarth-Agent: From tool calling to tool creation for open-environment earth observation [J/OL]. arXiv:2603.22148, 2026.

[17] Yu Y, Li B, Li Y, et al. Retrospective analysis of glacial lake outburst flood (GLOF) using AI Earth InSAR and optical images [J]. Remote Sensing, 2024, 16(13): 2307.

[18] Pisetta J, Souza F A, Amorim J, et al. Mapping with words: Integrating large language models into geospatial practice [J]. ISPRS Annals, 2025, X-3/W4: 285-292.
