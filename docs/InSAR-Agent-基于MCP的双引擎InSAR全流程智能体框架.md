# InSAR-Agent：基于模型上下文协议的双引擎 InSAR 全流程智能体框架

> **草稿状态**（2026-05-01）
> - [x] 引言（§1）— 含文献综述与贡献整理
> - [x] 系统设计与实现（§2）
> - [ ] 摘要（§0）— 占位，待 §3 完成后撰写
> - [x] 实验与分析（§3）— 已撰写（意大利南部 NISAR + Sentinel-1 四组对照实验，含 §3.7 实验讨论）
> - [x] 讨论（§4）
> - [x] 结论（§5）

---

## 摘要

> 【占位】双语摘要待第 3 节实验完成后再写。

**关键词：** InSAR；大语言模型；AI 智能体；模型上下文协议（MCP）；合成孔径雷达；ISCE3；ISCE2；地表形变

**Keywords:** InSAR; large language model; AI agent; Model Context Protocol (MCP); synthetic aperture radar; ISCE3; ISCE2; surface deformation

---

## 1. 引言

合成孔径雷达差分干涉测量（Differential Interferometric SAR, D-InSAR）与时序 InSAR（Time-Series InSAR）以毫米级精度监测地表形变，已成为地震同震位移、火山活动、城市地面沉降、冻土季节性隆沉以及矿区开采沉陷等灾害研究不可或缺的定量遥感手段。随着哨兵系列（Sentinel-1A/B/C）免费开放存档数据与 NASA-ISRO NISAR 在轨运行，可供研究的干涉像对数量进入指数级增长期，对高通量、可复现 InSAR 处理能力的需求与日俱增。

然而，完整的 InSAR 处理流程是一条对领域知识依赖极深的专业化流水线：从卫星级单视复数（SLC）数据的配准与像对选择，到 runconfig 工程配置的精确填写，再到多视数、相位解缠算法、大气校正策略等十余个耦合参数的经验性调整，每一步都需要研究人员具备多年积累的工程经验。一名缺乏专业软件背景的地质学研究者从零掌握 ISCE2/ISCE3 全流程通常需要数月时间。这种高专家门槛制造了严重的"大数据—小分析者"困境：卫星数据生产速率远超受过专业训练的 InSAR 处理人员规模。即便是有经验的操作者，也面临大量重复性配置工作——在新项目启动时反复填写路径字段、在多场景批处理中逐一调整参数、在任务失败后追溯日志定位问题——这些低创造性的工程劳动消耗了研究时间，却未能直接产生科学认识。

大语言模型（Large Language Model, LLM）与 Agent 技术的兴起为上述困境提供了新的解决思路。以 ReAct 为代表的"推理—行动"范式赋予 LLM 规划多步工作流、自主调用工具与动态纠错的能力 [1,2]。在工具调用与行为编排两个关键基础设施层面，Anthropic 提出的两套开放机制已被业界广泛采纳，逐步成为 AI Agent 领域的通用标准。**模型上下文协议（Model Context Protocol, MCP）** 于 2024 年 11 月开源 [3]，随后被 OpenAI、Google DeepMind、Microsoft 等主要厂商纳入各自 Agent 平台；任意符合规范的 Agent 客户端均可调用任意符合规范的工具服务端，专业软件由此能够以统一接口暴露给异构 Agent 宿主，垂直领域工具集成的工程门槛显著降低。**Skills 机制** 由 Anthropic 在 Claude Code 体系中提出 [23]，以声明式 `SKILL.md` 文件承载触发条件、工具调用顺序、中间校验点与失败回退策略，为复杂多步骤工作流提供了"工作流即配置"的组织范式，正被越来越多 Agent 框架借鉴用于结构化任务编排。本研究以上述两类机制为基础设施，构建面向 InSAR 全流程的领域化 Agent 框架。国内外研究者亦已将"LLM + Agent + 工具协议"范式引入遥感领域，从感知到行动取得了一系列进展。

智能 Agent 在遥感领域的探索可追溯至大语言模型兴起之前。早期 Agent 主要基于 BDI（信念—愿望—意图）框架，通过模块化与知识库匹配解决遥感图像检索、特征提取等具体任务，受限于规则系统的表达能力，缺乏自然语言理解与跨任务泛化能力 [4]。其后深度学习方法在场景分类、变化检测、目标识别等任务上的快速发展提升了遥感解译能力 [1,2]，但模型仍以"任务专用、被动前馈"的方式运行，缺少自主推理与工具调度能力。这一范式局限直接催化了"LLM + Agent + 工具调用"思路在遥感领域的兴起。

以 ChatGPT、LLaMA、Qwen、DeepSeek 等为代表的大语言模型应用于遥感领域后，催生了遥感多模态大语言模型（Remote Sensing Multimodal Large Language Model, RS-MLLM）研究方向。许文嘉等系统梳理了 RS-MLLM 的发展脉络，指出其通过视觉编码器与语言模型的桥接机制，在场景分类、视觉问答、图像描述等任务上从浅层语义匹配迈向了对世界知识的更深层理解 [5]；代表性工作包括 GeoChat、LHRS-Bot、RSGPT、SkyEyeGPT、EarthGPT 等基于视觉指令微调的 RS-MLLM。针对地理信息科学领域知识在通用 LLM 中的稀缺，研究者还构建了 BB-GeoGPT [6]、坤元、GeoGalactica、K2 等领域大模型 [6,7]。然而，RS-MLLM 普遍面临三方面瓶颈：缺乏对长时序、多步骤工作流的规划与记忆能力；静态参数中编码的知识无法及时更新；输入模态多以 RGB 影像为主，对 SAR、高光谱、热红外等专业模态以及大批量影像的处理能力有限 [1,2]。

为弥合 RS-MLLM 与真实遥感工作流之间的鸿沟，研究者提出了一系列以 LLM 为中央控制器、以专业模型与工具为执行单元的遥感 Agent 系统。Xu 等提出的 RS-Agent [8] 由 LLM 中央控制器、可扩展工具集、任务规划解决方案空间以及承载领域知识的知识空间四部分构成，并通过任务感知检索与 DualRAG 双路检索机制提升任务规划准确率，在 18 项遥感任务上取得超过 95% 的规划准确率。Liu 等的 Change-Agent [9] 面向遥感双时相变化解译，将多任务变化解译模型作为"眼睛"、LLM 作为"大脑"，支持以自然语言完成变化检测、变化描述、对象计数与因果推断等综合任务。在制图与地理信息处理方向，Smart-QGIS [10] 基于 MCP 将 LLM 与 QGIS 原生工具链桥接，构建了支持本地化部署的"数据加载—空间处理—专题制图"全流程智能体；MapColor-Agent [11] 通过多智能体协同将地图配色专业知识嵌入工具流；Song 等 [12] 利用 VGI 数据自动化完成端到端制图；Weiss 等的 MapBot [13] 在 REPL 循环中将 LLM 与 SAM、DINOv2 等视觉基础模型协同调度。Taggio 等的 SAI4EO [14] 提出"共生人工智能"（Symbiotic AI）理念，强调人机协同环境下的对地观测助手系统；Ames [15] 在水文领域综述中预言"AI-原生空间水文建模"——具备空间感知能力的 AI Agent 可直接对地理空间数据进行推理。齐析屿等 [16] 进一步提出大模型—智能体协同驱动的动态可扩展遥感目标解译系统，以有向无环图（DAG）建模子任务依赖、以"数据—工具自适应匹配"实现工具的动态扩展，验证了在港口区域目标解译场景下的适用性。

随着任务复杂度的上升，研究重心逐步从单 Agent 向多 Agent 协同与工具调用协议标准化演进。Feng 等提出的 Earth-Agent [17] 是首个将感知数据（RGB）与谱段数据（Spectrum、Products）统一在 MCP 架构下的对地观测 Agent 框架，将 104 个专业工具按 Index、Inversion、Perception、Analysis、Statistics 五大维度组织为结构化工具箱，并通过 ReAct 推理实现跨模态、多步骤的定量时空分析；Earth-Agent 同时强调，MCP 协议作为标准化的工具调用接口，是支撑 Agent 与异构科学软件互操作的关键基础设施。Zhao 等的 OpenEarth-Agent [18] 进一步将传统的"工具调用"范式扩展为"工具创建"——Agent 通过实时数据探查、自适应工作流规划与代码合成，动态生成贴合具体数据/任务的专用工具。在工业界，Google 团队提出的 Earth AI [19] 以 Gemini 智能体编排遥感影像、人口动态与环境（天气/洪涝）三类基础模型，演示了大规模跨模态地理空间推理的工程上限。Talemi 等 [1] 与 Tang 等 [2] 在系统综述中将上述工作进一步抽象为单智能体（如 RS-Agent、ChatGeoAI、EmbodiedCity）与多智能体（如 GeoLLM-Squad、RingMo-Agent、Earth-Agent）两大谱系，并归纳出感知—规划—行动—记忆的核心循环以及 RAG、知识图谱、工具协议等关键支撑技术。在 Agent 安全方面，Sebastian 等提出的 Superego [20] 同样以 MCP 为载体，由"超我"智能体在 MCP 协议层监督其他 Agent 的行为合规性；这一思路与本文 §2.4 所述 Advisory–Execution 双通道架构在哲学上互为镜像——前者通过外部监督防止异常行为，后者通过架构隔离防止幻觉参数落入工程流水线。

综合上述研究脉络，LLM Agent 在遥感领域的研究虽已快速展开，但在 InSAR 这类强物理建模、强工程约束的反演任务上仍存在四个关键缺口。**首先，任务覆盖偏向感知与制图，缺少对定量物理反演的深度支持。** 现有 Agent 大多聚焦场景分类、变化检测、视觉问答、地图生成等"感知/解译"任务 [1,2,8,9,13]，对需要严格物理建模与多步参数耦合的专业反演任务（如合成孔径雷达干涉测量、地表形变时间序列分析等）缺乏系统支持；即便涉及 InSAR 的工作 [21] 亦多停留在"AI 平台 + InSAR 流程"的云端集成层面，并未真正引入具备规划与决策能力的 LLM Agent。**其次，对专业 InSAR 软件的深度集成尚不成熟。** 现有遥感 Agent 普遍以 Python 库或 GIS 内置算子为工具节点 [10-13,17]，对 ISCE2、ISCE3、GAMMA 等需要复杂 runconfig 配置、conda 环境隔离、长时计算与文件级中间产物管理的专业 InSAR 软件，尚缺乏可复用、可验证的封装方案。**第三，工作流硬约束与领域知识难以以 Agent 原生形式表达。** Earth-Agent [17]、OpenEarth-Agent [18]、Smart-QGIS [10] 等工作虽已开始以 MCP 协议规范工具接口，但 InSAR 工作流中"严格的步骤顺序""工程参数白名单""runconfig 字段约束""先验基线/网络几何"等硬性约束，仍依赖人类专家在每次运行前手动校验，难以转化为 Agent 可直接消费的协议化资源与提示。**第四，参数推理与工程执行缺乏架构层面的安全隔离。** LLM 推理结论可直接触发工具执行，幻觉参数将无阻拦地写入工程配置并触发小时级的无效计算；现有遥感 Agent 文献尚未对这一问题给出工程化解法，相关的"超我"机制 [20] 主要面向通用安全，对 InSAR 参数空间的语义校验仍属空白。

针对上述缺口，本文提出 **InSAR-Agent**——一个以 MCP 为核心、以 Skills 机制承载领域知识与流程约束的 InSAR 工作流智能体框架。在设计哲学上，本研究明确以"人为最终决策者"为前提：Agent 负责工作流编排、参数推理与结果量化，但参数修改须经用户审批方可落盘，InSAR 产品的质量判断亦由领域专家把关。这一人机协同（Human-in-the-loop）立场区别于"全自动化黑盒"思路，更符合定量物理反演对可追溯性与可控性的严格要求。在此框架下，本研究的主要贡献体现在以下五个方面：

**贡献 1——双引擎全流程统一编排**：提出首个在同一 MCP 体系下同时支持 ISCE3/NISAR 与 ISCE2/Sentinel-1 两条数据流的 InSAR Agent 框架，将场景发现、数据下载、DEM 准备、runconfig 生成、参数调优、批处理执行、MintPy 时序解算、GeoTIFF 导出等步骤抽象为统一的 Job 与 Project 数据模型，覆盖 D-InSAR（单像对）与 Stack-InSAR（时序）两类典型工作流。

**贡献 2——Advisory–Execution 双通道参数顾问机制**：提出一种参数推理与工程执行解耦的双通道架构，以 Skill 为薄编排层，委派专用子 Agent（Param-Advisor Subagent）读取证据档案生成带引用的参数建议；用户确认后由 MCP 工具依据 YAML 白名单做确定性校验，方可将修改落盘。这一设计在架构层面阻断幻觉参数进入工程流水线，是目前 RS-Agent [8]、Earth-Agent [17]、OpenEarth-Agent [18] 等工作均未显式提出的机制，并与 Superego [20] 的 MCP 安全监督思路在哲学上呼应、在落地手段上互补。

**贡献 3——工作流硬约束的多机制分层表达**：将 InSAR 工作流约束按表达粒度分别映射到四类机制——**步骤顺序约束以 Claude Code Skills 机制为主、以 MCP Prompts 为辅**：Skills（如 `d-insar-isce3`、`stack-insar-isce2`、`param-advisor`）在 Agent 进入特定工作流时被加载，逐条强制工具调用顺序、中间校验点（如"必须在 Step 2 与 Step 3 之间进入参数顾问"）与失败回退策略；MCP Prompts（`process_insar_pair`、`process_insar_batch`）则面向不支持 Skills 的客户端提供等价的工作流模板。**路径字段白名单**通过 MCP Resources（`insar://allowed-fields/{workflow}`）按工作流动态下发；**参数语义约束**（类型、范围、枚举值、风险等级）通过 MCP Tool 内嵌 YAML Schema 在 `insar_set_processing_param` 中执行确定性校验；**工作流全局规则**则以 MCP Resource（`insar://workflow-guide`）支持 Agent 在任意对话轮次主动查询。这种分层表达使每类约束可独立版本管理，互不干扰，避免了 Earth-Agent [17] 等将约束隐式编码于工具 docstring 的做法在长对话中容易遗忘或混淆的问题。

**贡献 4——InSAR 专业知识资源化与 AI 辅助后分析体系**：构建分层领域知识档案——底层工程经验档案、中层参数证据档案、顶层工作流约束资源——使"下一步做什么""参数如何取值""遭遇非标问题"三类查询走向各自最适合的知识通路；并设计可扩展的模板化后分析机制，支持形变热点识别、剖面提取与量化报告生成，将 Agent 能力从"启动处理"延伸到"解读结果"。后分析机制遵循开放扩展原则，AI 可按需合成新的分析脚本，与 OpenEarth-Agent [18] 的工具创建理念在专业反演场景中形成互补。

**贡献 5——Protocol-based 引擎可扩展架构与可复现 Job 模型**：通过 `EngineAdapter` Protocol 将引擎实现与 MCP 编排彻底解耦，新引擎（如 GAMMA、SNAP）只需实现四个最小模块即可接入，无需修改任何工具签名或核心数据模型，为 InSAR 领域社区共建提供基础设施；同时以统一 Job 数据模型与 `jobs/{job_id}.json` 完整任务快照支撑工作流可复现性，配合 MCP-First 的客户端无关设计，使 InSAR-Agent 可无缝接入 Claude Code、Codex 及任意符合 MCP 标准的 Agent 宿主，区别于 Smart-QGIS [10] 等与单一 GIS 平台强绑定的方案。

本文其余部分组织如下：第 2 节详述 InSAR-Agent 的系统设计与各模块实现；第 3 节给出基于真实 NISAR 与 Sentinel-1 数据集的实验结果；第 4 节讨论设计哲学、与现有遥感 Agent 的对比、局限性与未来方向；第 5 节总结全文。

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
│  15 MCP Tools  │  2 MCP Resources  │  2 MCP Prompts           │
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

三层之间的边界确保任何一层的改动不会波及其他层：引擎执行层对外仅暴露 `EngineAdapter` 协议（详见 §2.8）；MCP 编排层持有全部协议绑定逻辑，不包含任何引擎特定代码；交互指引层以 Skill 与 Subagent 形式承载领域知识与用户交互流程，不直接调用引擎代码。这种分层带来的直接效益是：新增引擎不影响 MCP 工具签名，更换 Agent 宿主不影响引擎实现，领域知识迭代不影响工具注册逻辑。

### 2.2 MCP 协议编排层

协议编排层以 FastMCP 框架构建标准 MCP stdio 服务端，向 Agent 客户端暴露三类原语：MCP 工具（Tools）、MCP 资源（Resources）与 MCP 提示（Prompts）。

#### 2.2.1 MCP 工具

15 个工具按功能分为 8 组（表 1）。工具总数遵循"数量克制"原则：每个新能力首先问"能否扩展现有工具"，顺序必然执行的步骤合并为单一工具，所有类型的长时任务统一使用 `insar_get_job` 轮询，从而使 Agent 决策链尽可能短。

**表 1** InSAR-Agent MCP 工具分类

| 功能组 | 工具数 | 代表工具 | 主要职责 |
|--------|--------|----------|----------|
| 发现与诊断 | 2 | `insar_discover`、`insar_check_env` | 引擎/工作流枚举，conda 环境检查 |
| 项目管理 | 2 | `insar_create_project`、`insar_get_project` | 工作空间初始化，状态查询 |
| 配置调优 | 4 | `insar_get_runconfig`、`insar_set_runconfig_value`、`insar_set_processing_param`、`insar_export_runconfig` | runconfig 读写与参数白名单校验 |
| 工作流执行 | 3 | `insar_run_workflow`、`insar_get_job`、`insar_list_outputs` | 单对启动、长时任务轮询、产物枚举 |
| 批次/网络 | 3 | `insar_prepare_stack`、`insar_prepare_network`、`insar_run_batch` | Stack 与网络 runconfig 生成、批处理启动 |
| 时序分析 | 3 | `insar_run_mintpy`、`insar_run_mintpy_isce2`、`insar_plot_baseline` | MintPy 时序解算、基线网络可视化 |
| NISAR 数据 | 3 | `insar_describe_rslc`、`insar_download_rslc`、`insar_download_dem` | RSLC 元数据解析、数据下载与裁剪 |
| Sentinel-1 数据 | 4 | `insar_describe_s1`、`insar_download_scene`、`insar_prepare_sentinel_data`、`insar_export_geotiff` | SAFE 元数据、数据组织、GUNW 导出 |

> 注：上表"工具数"按功能组列出工具职责覆盖关系，部分工具（如 `insar_get_job`）同时服务多组任务，因此各组之和大于实际工具总数。

与 Earth-Agent [17] 的 104 个工具相比，本框架工具总数仅约其 14%，这并非功能裁减，而是针对 InSAR 步骤顺序严格、错误代价高的工程特点所作的主动设计。工具过多时，Agent 在每一步推理需要在更大动作空间中检索，增加误调用概率与任务链条长度。

#### 2.2.2 MCP 资源

系统提供 2 个 MCP 资源，承载不适合编码进工具签名的结构化领域知识：

- **`insar://workflow-guide`**：映射到 `docs/agent-guide.md`，以自然语言与表格形式描述工作流硬约束、两条处理路径（Path A 单像对/Path B 批次）的强制步骤顺序与常见错误码。Agent 在规划阶段可主动查询该资源，获取当前任务的合法操作范围。
- **`insar://allowed-fields/{workflow}`**：根据请求的工作流类型（如 `insar`、`gslc`、`tops`、`stack`）动态生成可修改路径字段清单。例如，ISCE3 `insar` 工作流允许修改的字段包括参考/辅助 RSLC 路径、DEM 路径、水体掩膜路径、产品输出路径、临时文件路径等共 10 项，均在 `ALLOWED_SET_FIELDS` 字典中静态声明。

将约束知识以资源形式暴露而非注入系统提示词，具有两点工程优势：资源可在任意对话轮次被主动拉取，而非仅在会话初始化时静态注入；资源内容可独立版本管理，无需改动工具签名即可升级约束规则。

#### 2.2.3 MCP 提示

系统提供 2 个预构建提示（`process_insar_pair`、`process_insar_batch`），分别对应 D-InSAR 单像对与 Stack-InSAR 两类完整处理流程的标准任务指令。这两个提示将任务目标、数据路径占位符与处理参数预置组合为结构化指令，供不支持 Skills 机制的客户端在流程入口处调用，降低用户自然语言输入的歧义性。在支持 Skills 的客户端（如 Claude Code）中，§2.5 所述 Skills 机制承担更主导的步骤顺序约束职责。

### 2.3 双引擎工作流

InSAR-Agent 支持两条典型处理路径，均由 MCP 工具编排，统一使用 `Job` / `BatchJob` 数据模型跟踪执行状态（图 2）。

**Path A — D-InSAR 单像对处理**（ISCE3 或 ISCE2）：

```
insar_create_project          （初始化工作空间，加载默认 runconfig 模板）
    → insar_set_runconfig_value × N    （填写输入/输出路径字段）
    → [param-advisor skill]            （可选，详见 §2.4）
    → insar_set_processing_param × N   （可选，应用调优参数）
    → insar_run_workflow               （校验 + 导出 YAML + 启动，返回 job_id）
    → insar_get_job                    （轮询，直到 done/failed）
    → insar_list_outputs               （枚举产物，给出推荐查看器）
```

**Path B — Stack-InSAR 时序处理**（ISCE3 或 ISCE2）：

```
insar_prepare_stack          （ISCE3：生成单参考 runconfig 组；ISCE2：类似）
    → insar_prepare_network            （ISCE3：生成干涉图网络 runconfig 组）
    → insar_run_batch                  （启动 run_parallel.sh，返回 job_id）
    → insar_get_job                    （轮询批次完成状态）
    → insar_plot_baseline              （生成基线网络图，人工复核质量门控）
    → insar_run_mintpy / insar_run_mintpy_isce2   （启动 MintPy 时序解算）
    → insar_get_job                    （轮询 MintPy 完成状态）
```

**图 2** D-InSAR（Path A）与 Stack-InSAR（Path B）工作流步骤序列

两条路径在运行层面均通过 `conda run` 调用各自 conda 环境中的 ISCE3 或 ISCE2 可执行文件，不依赖全局 PATH 配置，从而实现不同版本 InSAR 软件的隔离共存。

### 2.4 Advisory–Execution 双通道参数顾问

参数选择是 InSAR 处理中最依赖领域经验的环节。多视数（range/azimuth looks）决定干涉图分辨率与相干性的权衡，相位解缠算法对包裹相位质量敏感，大气校正开关影响形变信号的可靠性。若将参数推理逻辑直接编码进 MCP 工具，当 LLM 推理产生幻觉参数时，将无阻拦地写入 runconfig 并触发小时级的无效计算；若强制要求用户手动设置全部参数，则失去了引入 LLM 的意义。

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
│  模型：claude-sonnet-4-6（可替换）           │
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
│    ISCE3/insar：15 个受控参数                │
│    ISCE2/tops： 16 个受控参数                │
│    ISCE2/stack：17 个受控参数                │
│  ─ 逐项校验：key / type / range / enum / risk│
│  ─ 通过 → 写入 runconfig；拒绝 → 返回错误    │
└──────────────────────────────────────────────┘
```

**图 3** Advisory–Execution 双通道参数顾问流程图

**Advisory 通路**由专用子 Agent 驱动，其核心输入是经过压缩的 Evidence Profile——包含场景元数据、当前 runconfig 摘要、用户任务目标与白名单参数注册表摘要，而非完整的对话历史或 YAML 文件。子 Agent 对照 engine-specific 证据档案，引用具体参考依据（如"S 波段 range_looks=11 对应 ~80 m 地距分辨率，适合大范围形变场景"），生成带证据链的参数建议，并在输出包中明确标注 `advisory_only: true` 与 `user_responsibility_notice`，表明最终决策权归属于用户。

**Execution 通路**与 Advisory 通路完全独立。`insar_set_processing_param` 工具根据引擎类型加载对应 YAML 白名单，对每个修改请求依次执行：参数 key 存在性检查、类型匹配（int/float/str/bool/list）、数值范围验证（`valid_range`）、枚举值校验（`valid_values`）与风险等级评估（low/medium/high）。任何不满足约束的参数均被拒绝并返回明确错误，不对 runconfig 产生任何副作用。

这一架构的安全价值在于：Advisory 通路的 LLM 推理结果必须经过 Execution 通路的确定性白名单过滤，幻觉参数在架构层面被拦截，而非依赖提示词指令约束。Advisory 通路的子 Agent 可随时替换为 GPT、Qwen、Gemini 等不同 LLM 后端，而无需改动任何 MCP 工具签名。这一思路与 Sebastian 等 [20] 提出的 Superego（通过 MCP 协议层监督其他 Agent 的行为合规性）在设计哲学上呼应：双通道架构通过**架构隔离**防止幻觉参数落盘，Superego 通过**外部监督**防止越界行为，两者共同体现了 MCP 协议在构建可信 Agent 流水线中的潜力。

### 2.5 工作流硬约束的多机制分层表达

InSAR 工作流包含大量工程层面的硬性约束：步骤必须严格按顺序执行（如"必须先 `insar_create_project` 再设置路径字段，再可选地进入参数顾问，最后才能启动工作流"），特定字段只允许修改而另一些字段不可触碰，参数修改须经范围与类型的语义校验。这些约束若仅以自然语言写入系统提示词，Agent 在长对话中容易遗忘或混淆；若硬编码进每个工具的业务逻辑，则约束更新时需同步修改多处代码。

本研究将 InSAR 工作流约束按表达粒度系统性地映射到四类机制（表 2），形成**多机制分层表达**架构：

**表 2** 工作流约束到表达机制的多机制映射

| 约束类型 | 主要机制 | 备用机制 | 落地形式 |
|----------|---------|---------|---------|
| 步骤顺序与中间校验点 | **Skills（Claude Code）** | MCP Prompts | `skills/<name>/SKILL.md` 步骤 1–N + 强制中断点 |
| 路径字段白名单 | MCP Resources | — | `insar://allowed-fields/{workflow}` 动态生成 |
| 参数语义约束 | MCP Tool 内嵌 YAML Schema | — | `insar_set_processing_param` 校验逻辑 |
| 工作流全局规则 | MCP Resources | 工具 docstring | `insar://workflow-guide`（自然语言 + 表格） |

#### 2.5.1 步骤顺序约束：Skills 机制为主、MCP Prompts 为辅

**Skills 机制是本框架表达步骤顺序约束的首选载体。** 鉴于 Skills 与 MCP 同属当前 AI Agent 领域被广泛采纳的开放机制（§1），选择 Skills 作为编排载体也保留了向其他兼容 Agent 框架迁移的路径。每个 Skill 文件（如 `skills/d-insar-isce3/SKILL.md`、`skills/stack-insar-isce2/SKILL.md`、`skills/param-advisor/SKILL.md`）均以 YAML frontmatter 声明触发条件，并以编号步骤明确规定工具调用顺序、必填确认项、强制校验点与失败回退策略。例如 `d-insar-isce3` Skill 在 "Standard workflow (always follow this order)" 段落中强制规定 1–7 步的标准顺序：从 `insar_create_project` 到 `insar_set_runconfig_value`，到 Step 2.5 的"参数调优强制中断点"（在 interactive 模式下必须等待用户确认才能继续），再到 `insar_run_workflow`、`insar_get_job` 与 `insar_list_outputs`。Skill 同时设置硬约束声明，例如"All ISCE3 operations must go through `insar_*` MCP tools. Do not run conda/python commands directly."、"Core processing parameters cannot be changed through `insar_set_runconfig_value` ... must invoke `param-advisor` between Step 2 and Step 3" 等。

Skills 机制相对于纯文本提示词的优势在于：（1）声明式触发——客户端根据 frontmatter 的 `description` 与上下文自动加载相关 Skill，无需在系统提示词中静态预置；（2）可组合调用——`d-insar-isce3` 在 Step 2.5 显式委派到 `param-advisor` Skill，形成 Skill 之间的"工作流子图"；（3）独立版本管理——Skill 文件作为本地 plugin（`insar-agent-skills@insar-agent`）发布，更新流程约束无需改动 MCP 工具签名或服务端代码。

**MCP Prompts 作为备用机制**，面向不支持 Claude Code Skills 的客户端（如部分 IDE 内嵌 MCP 客户端）。`process_insar_pair` 与 `process_insar_batch` 提供等价的工作流模板，在客户端上下文中以预构建提示形式呈现，确保不同 Agent 宿主下都能获得至少一种步骤顺序约束。

#### 2.5.2 路径字段白名单与参数语义约束

**路径字段白名单**通过 MCP Resources（`insar://allowed-fields/{workflow}`）按工作流动态下发。`insar_set_runconfig_value` 在写入前校验目标 key 是否在该工作流允许集合内；不在则返回 `key_not_allowed` 错误并提示用户走 `insar_set_processing_param` 通路（详见 §2.4）。这种设计将"哪些字段可改"的问题与"如何修改"的问题完全分离。

**参数语义约束**通过 MCP Tool 内嵌 YAML Schema 在 `insar_set_processing_param` 中执行确定性校验（详见 §2.4）。参数白名单 YAML（`engines/isce3/assets/processing_params_insar.yaml` 等）声明每个参数的类型、范围、枚举值与风险等级，YAML 文件与代码独立维护，便于工程师/领域专家直接编辑。

#### 2.5.3 与现有方案的对比

与 Earth-Agent [17] 将全部约束隐式编码在工具 docstring 中相比，本方案对约束内容具有更强的显式性与可查询性。步骤约束在 Skills/Prompts 层更新，路径白名单在 Resources 层更新，参数语义在 YAML 文件中更新，各自独立版本管理，互不干扰。这一设计与 OGC GeoAI 工作组对地理 AI 工作流可追溯性的诉求 [22] 相契合。齐析屿等 [16] 的 DAG 任务依赖建模强调子任务之间的有向关系，而本研究的 Skills 机制更侧重单一工作流内步骤顺序与人机协同断点的强制——两者在不同粒度上互补。

### 2.6 InSAR 领域知识体系

InSAR 数据处理涉及大量隐性专家知识，如多视数对相干性与分辨率的权衡规律、Sentinel-1 精密轨道（Precise Orbit Ephemeris, POE）文件的必要性、ISCE2 topsStack 各处理步骤的触发条件等。这类知识既不适合编码进工具签名（导致工具粒度过细），也难以通过检索通用遥感文献获取（专业度过高）。

本研究构建分层 InSAR 领域知识体系（图 4），按粒度从粗到细组织为三层：

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

这一分层使不同粒度的查询走向各自最适合的通路："下一步该做什么"查询工作流约束资源；"为什么要设置这个参数"查询证据档案；工程实践中遇到的非标准问题查询工程经验档案。RS-Agent [8] 的 DualRAG 在通用遥感任务上展示了"全局 + 关键词"双路检索的有效性，本研究将这一思路在 InSAR 强物理建模领域以"参数原理 + 工程经验 + 工作流约束"三元组的形式具体化，将检索目标限定为可审计的 markdown 证据档案，避免黑盒训练数据可能引入的不一致性。

### 2.7 AI 辅助结果后分析

InSAR 处理完成后，研究人员通常需要对形变产品进行若干定量分析——沿特定断层或坡体提取形变剖面时间序列、识别超过速率阈值的异常形变区、生成可供决策的量化报告。这类步骤重复性高、可参数化，适合以独立的可扩展 Skill 承载。

本研究设计了模板化的后分析机制，遵循三个原则：

**原则一——用户始终是质量判断的最终责任人。** 后分析工具仅提供定量数值与可视化输出（形变速率统计、异常区 GeoJSON、剖面 CSV），地质解释由领域专家完成。这与 §2.4 中"三选一确认"的人机协同立场保持一致，亦与 Foundation Model for Generalist Remote Sensing Intelligence [7] 中提出的"human-in-the-loop integration as core challenge"一脉相承。

**原则二——模板化与开放扩展并举。** 系统提供标准报告模板，覆盖形变速率统计、异常区识别与剖面摘要等基础内容；用户可按需自定义分析工具，参照 OpenEarth-Agent [18] 的工具创建思路，Agent 亦可在运行时根据用户的自然语言需求合成新的分析脚本，将工具边界向特定地学场景延伸（如火山膨胀源参数解算、冻土沉降季节性分量提取等）。

**原则三——输出格式面向下游复用。** 剖面数据以 CSV 导出，异常区以 GeoJSON 格式导出（便于在 QGIS 中叠加），报告以 Markdown/HTML 格式生成，确保分析结果能直接进入下游论文制图或灾害上报流程，与 Smart-QGIS [10] 等本地化 GIS 平台形成自然衔接。

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

目前系统已完整实现 ISCE3 与 ISCE2 两个引擎，前者支持 `insar`（D-InSAR）与 `gslc`（地理编码单视复数图像）两类工作流，后者支持 `tops`（单像对 topsApp）与 `stack`（topsStack 时序）两类工作流。这一架构与 齐析屿等 [16] 的 "数据—工具自适应匹配 + 动态扩展工具集" 思想一致，但本研究将工程严肃的 InSAR 软件作为一等公民处理，而非视为可临时合成的轻量算子，更适合定量物理反演领域。该架构同时为 InSAR 领域开发者社区的后续共建提供基础设施。

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

任意历史任务均可凭 `job_id` 完整复现：取出 `jobs/{job_id}.json` 中的 runconfig 副本，使用相同引擎版本与 conda 环境重新执行，即可在相同数据集上重复相同处理，满足遥感定量研究对处理审计与结果验证的基本要求。这种"runconfig 快照 + 命令行快照 + 状态快照"的可追溯设计与 ISPRS 关于地理空间 LLM 工作流可复现性的讨论 [22] 相契合，也为多 backbone 比较实验（如 Claude vs. GPT vs. Gemini，类似 Earth AI [19] 在工业界以 Gemini 为后端的实践）提供了客观参考基础。

---

## 3. 实验与分析

四组对照实验考察 InSAR-Agent 在单像对差分干涉与时序 InSAR 两类典型任务下的端到端贯通性，并在 C 波段 Sentinel-1 与 L 波段 NISAR 两类数据源、ISCE2 与 ISCE3 两套工具链之间检验智能体编排的一致性。所有实验共享同一研究区与同一 DEM，使工作流形态与传感器代际成为唯一受控变量。

### 3.1 数据与研究区

研究区位于意大利南部沿海带，覆盖约 39.9°–41.0°N、12.3°–14.0°E，地形由近海低地过渡至中低山地，土地利用以农田、城镇与稀疏林冠为主。在该区域同时获取两类 SAR 数据。**Sentinel-1 C 波段 IW SLC** 来自三条独立轨道（S1A 升轨、S1A 降轨、S1C 升轨），共 24 景，时间窗 2026-01-05 至 2026-04-06，回访周期 12 天，VV 主极化 [26]。**NISAR L 波段 L1 PR RSLC**（双极化 DH+DH）取自轨道 172 升轨第 008 帧，共 7 景，时间窗 2025-10-29 至 2026-01-09，回访周期约 12 天 [28]。NISAR 影像在数据获取阶段已按研究区核心子窗口（约 0.30°×0.27°）裁剪以降低后续处理与存储负载，Sentinel-1 影像保留全 SAFE 包。

地形参考采用 Copernicus 30 m 全球数字高程模型 [29]，覆盖范围按 AOI 加 0.1° margin 获取，所有处理以 WGS84 为坐标输入。

**图 5** 研究区位图（待绘）：底图为 DEM 阴影叠加海岸线，叠加 Sentinel-1 升降轨与 NISAR Track 172 影像足迹、AOI 多边形与 NISAR 子窗口框。

### 3.2 实验设计

InSAR 智能体的设计目标覆盖从单对差分干涉到时序反演的完整任务谱系，并要求在两种代际差异显著的算法栈间保持一致的用户接口。基于此目标，本研究构造一组对照实验，沿数据源（C 波段 Sentinel-1 与 L 波段 NISAR）与工作流形态（单对与时序）两个正交维度展开，落在 ISCE2 与 ISCE3 这两条目前主流的开源工具链上，构成四个实验 E1–E4（表 3）。两个维度的组合并非穷举。C 波段与 ISCE2、L 波段与 ISCE3 的配对方式遵循各传感器的官方处理路径，跨配对（例如 NISAR 数据走 ISCE2 路径）在生产实践中并不常见，且会引入不可控的接口适配开销，掩盖本研究真正关注的智能体编排能力。

四个实验共享同一 AOI 与同一 Copernicus 30 m DEM。E1 与 E2 同在 ISCE2 工具链上处理 Sentinel-1 数据，分别对应单对差分与三景 small-baseline 时序两种工作流，用以揭示 D-InSAR 与时序处理在配置粒度与产物结构上的差异；E3 与 E4 在 ISCE3 工具链上对同一 NISAR 七景子栈分别构造单参考栈与短时基线网络，对比单参考与冗余网络两种典型时序前处理方案。E2 与 E4 均接入 MintPy [25]，用以验证同一时序框架对两种来源干涉栈的兼容性。除算法栈各自固有的结构外，几何参数（多视、滤波、解缠）沿用各工具链文档推荐的常用值，仅在需要适配研究区分辨率与子条带选择处做轻量调整，具体取值与依据在 §3.3–§3.6 各小节随处理流程展开。

**表 3** 四实验对照

| 编号 | 数据 | 算法栈 | 工作流 | 主要产物 |
|------|------|--------|--------|----------|
| E1 | Sentinel-1 IW SLC | ISCE2 topsApp [27] | 单对 D-InSAR | 滤波 wrap/unwrap 相位、相干、LOS（雷达坐标 + 地理编码） |
| E2 | Sentinel-1 IW SLC | ISCE2 topsStack + MintPy [25,27] | 三景单参考 Stack | 干涉对 + 平均 LOS 速度场 |
| E3 | NISAR L1 RSLC | ISCE3 `nisar.workflows.insar` [28] | 七景单参考 Stack | 6 个 GUNW（地理编码解缠干涉） |
| E4 | NISAR L1 RSLC | ISCE3 + MintPy [25] | 短时基线网络 + 时序 | 15 个 GUNW + 时序速度场 |

数据获取（DEM、精密轨道、SLC/RSLC）、配置生成、批处理调度与产物归档统一由智能体承担，对外仅暴露研究区、时间窗与算法选择三个参数。终端用户输入相对传统脚本驱动方式显著精简，这一接口约束本身亦构成本研究的评估对象之一。

### 3.3 E1：ISCE2 单对 D-InSAR

单对差分干涉构成实验链条的最简单情形。Sentinel-1A 升轨 2026-01-12 与 2026-01-24 两景相邻 SLC 组成干涉对，标称时基 12 天，对应 Sentinel-1 C 波段在中纬度农田与城镇混合下垫面下的有效相干窗口下限。更短的相对时基在该轨道不可得，更长的时基则使相干衰减进入快速段，工作流贯通性与频段去相干两类问题将难以区分。两景相位中心在垂直基线维度上的偏离远小于临界基线，几何去相干可忽略。

干涉对在 ISCE2 topsApp 框架下处理。研究区主要散射响应集中于 IW2 子条带，处理范围因此限定在该子条带，IW1 与 IW3 不参与 burst 合并，以避免在边界拼接阶段引入额外的相位不一致。地理编码窗口与 AOI 对齐于约 39.89°–41.02°N、12.32°–14.00°E，使 E1–E4 在空间上可直接叠加。距离向 20、方位向 4 的多视组合在 IW 几何下产生接近正方形的地距像元（约 50 m），对应每像元约 80 个独立样本，将相干估计偏差控制在标准时序处理可接受范围之内 [24]。Goldstein 自适应滤波强度设为 0.5，处于"保留地形相关相位条纹"与"压制斑点噪声"的折衷点，避免山地区域过强滤波抹平有效条纹。Burst overlap 模式开启以维持方位向连续性。ESD 精配准在 12 天短基对下被关闭，因该时基下 burst 间方位向残差已显著低于解缠步长，进一步精化反而引入由相邻 burst 信噪不均带来的二次扰动 [26]。SNAPHU 承担解缠，未额外施加掩膜，以保留小尺度高梯度区域的相位连通性 [24]。DEM 取 Copernicus 30 m，按 AOI 加 0.1° margin 裁剪后作为地理编码输入。

产物涵盖滤波 wrap 干涉相位、解缠相位、相干图、LOS 视线向位移与几何查找表，均经地理编码至 WGS84。研究区中部山地呈现与地形高度相关的相位模式；城镇与农田区域相干普遍高于 0.7，密植林冠下部分像元相干降至 0.3 以下，与 C 波段 12 天对在该类下垫面下的响应预期一致。

**图 6** E1 结果三联图（待绘）：(a) 地理编码后滤波 wrap 干涉相位；(b) 解缠相位（rad）；(c) 相干图。每子图叠加 AOI 边界。

### 3.4 E2：ISCE2 三景 Stack-InSAR

将同一工具链由单对扩展到时序场景，可检验在 §3.3 中确立的参数选择能否平移到多景栈式处理，同时考察 stack 路径相对单对处理新增的若干环节（参考几何提取、共参考精配准、burst 合并的多对一致性）在智能体编排下能否保持稳定。Sentinel-1A 降轨 2026-01-05、01-17、01-29 三景构成两对相邻 12 天 IW2 子条带干涉（20260105–20260117、20260117–20260129）。降轨数据的引入为后续与 E1 升轨之间的几何观测多样性预留接口，本身不在三景范围内执行 LOS 分解。三景对应 small-baseline 概念可落地的最小样本数，不足以支撑长时形变结论，但已能将 stack 工具链各阶段一次性贯通。

参考几何提取与多对 burst 合并干涉构造由 ISCE2 topsStack 在 IW2 子条带上完成。几何参数（多视 20×4、Goldstein 0.5、SNAPHU 解缠）沿用 §3.3 设置，使 E1 与 E2 之间的产物差异仅由工作流形态主导。时序反演接入 MintPy [25]，按经典 small-baseline subset 思路在相干阈值掩膜后的像元上构造观测方程，并在网络精修阶段以相干阈与最小生成树策略筛选有效干涉以维持连通。沿海低地的对流层延迟在 12 天窗口内可达毫米级，ECMWF ERA5 对流层校正因此纳入流程；即便样本量较小，该校正本身不向解算注入偏差，且能降低速度场的低频噪声，与跨实验对比的可比性目标一致。

产物包括两对的滤波 wrap/unwrap 相位与相干，以及 MintPy 时序输出（平均 LOS 速度场、位移时序、时间相干、空间平均相干与连通分量掩膜）。E2 速度场仅作为流程贯通性证据使用，不用于推断长期形变，这一约束在 §3.7 中作为局限性保留。

**图 7** E2 结果（待绘）：(a) 两对干涉解缠相位并列；(b) MintPy 平均 LOS 速度场（mm/yr）；图注明确说明样本量限制。

### 3.5 E3：ISCE3 单参考 NISAR Stack

L 波段子栈的引入服务两个目的：评估 ISCE3 工作流在单参考 stack 配置下的端到端贯通性，以及为 E4 的短基线网络提供基线产物。NISAR cropped RSLC 共 7 景，参考日期取 2025-10-29，副景依次为 2025-11-10、11-22、12-04、12-16、12-28 与 2026-01-09，构成 6 对参考–副景干涉，时基由 12 天递增至 73 天。该时基谱有意延伸至单参考栈的相干衰减边缘，目的不在于提供形变估计，而在于观察 L 波段在该研究区下垫面下的去相干上限，为 §3.6 的网络截断阈值提供经验依据。

干涉构造由 `nisar.workflows.insar` 直接产出 GUNW，省去 ISCE2 路径中"参考几何 → 配准 → 干涉 → 地理编码"的多步级联，每对干涉以单文件 HDF5 承载解缠相位、相干、连通分量、入射几何与像元坐标，便于下游统一读入。多视配置在相干估计阶段为 11×11，相位产物保持 1×1 原生分辨率。NISAR cropped RSLC 距离向像元约 7 m，11×11 平均后输出网格约 77 m，与 §3.3 的 ~50 m 量级相当，便于跨频空间叠加；保留原生分辨率的相位产物，将空间细节的取舍权交给下游分析，而非在工作流内部硬编码。中值滤波核取 9×9，反映 L 波段干涉相位低频成分相对 C 波段更突出的特点，稍大核可在压制斑点的同时不致抹平有效条纹。SNAPHU 解缠以相干区间 [0.1, 0.9] 加权：下界 0.1 避免在接近完全去相干的区域注入伪信号，上界 0.9 防止高相干像元因权重过重而过约束邻域，离群阈 0.5 用于剔除与邻域显著偏离的像元 [24]。地理编码使用工作流默认 EPSG（WGS84，约 0.005° 像元间隔）。电离层校正未纳入流程，原因在于基于双频 split-spectrum 的电离层估计需要完整 NISAR L 频段视频，而 cropped RSLC 不能稳定支持；对流层校正同样推迟至 MintPy 阶段以外接气象产品施加，使 E2 与 E4 之间维持一致的校正策略。SNAPHU 与几何重投影属于内存带宽密集步骤，由单 GPU 加速可获得大致一个量级的端到端提速，且不影响产物数值。

6 对干涉在单节点 8 路并发下完成处理，每对产出一个地理编码 GUNW 文件。研究区内最长时基对（参考日期与 2026-01-09，73 天）相干中位仍维持在约 0.5 量级，表明 L 波段在该研究区中等时基下的相干稳定性优于同区 C 波段对 [28]。

**图 8** E3 GUNW 三联图（待绘）：挑选 12 天最短时基对与 73 天最长时基对并排：(a) 解缠相位；(b) 相干；(c) 连通分量。展示时基增大下的相干衰减。

### 3.6 E4：ISCE3 网络 + MintPy 时序

在 §3.5 同一子栈上构造短时基线干涉网络，可评估时序反演在 NISAR cropped 数据上的可行性，并与 §3.4 形成"同一时序框架、不同来源干涉"的对照。网络选择采用 36 天最大时基阈值，对应标称 12 天回访周期的三倍。该阈值的依据来自 §3.5 的相干观察：L 波段在中纬度农田与城镇下垫面上，36 天时基仍处于相干高位区，而 73 天时基的相干中位已降至约 0.5，进一步增加冗余度带来的反演稳定性已不足以补偿相干衰减。在三倍回访周期阈值下筛选得 15 对干涉，垂直基线区间约 −72.1 至 +51.5 m，时基覆盖 12–36 天，构成在最小生成树意义下连通良好的网络（图 9），后续 MintPy 反演不出现孤立时段。每对干涉以与 §3.5 一致的几何参数批量生成 GUNW，使 E3 与 E4 之间的差异严格收缩到"干涉网络结构"这一变量。

时序反演由 MintPy [25] 完成，参考日期沿用 2025-10-29 与 §3.5 对齐。Copernicus 30 m DEM 在 L 波段干涉相位中的高程残差可能进入毫米级速度估计，DEM 误差估计与改正因此纳入流程，此为 SBAS 框架下的标准实践。为控制反演耗时，DEM 误差与位移联合估计采用全局几何而非逐像素几何，研究区在 cropped 子窗口范围内地形变化较缓，全局简化引入的偏差可忽略，而逐像素几何带来的精度增量与计算开销不成比例。对流层延迟校正未纳入流程，因短时基线窗口（≤36 天）内 L 波段对流层贡献在毫米尺度上低于本实验的目标分辨率；此项作为后续外接 ERA5 的接口预留，与 §3.4 中已启用的 ERA5 策略形成对照。网络精修阶段沿用相干阈与最小生成树保连通策略。

MintPy 输出包括平均 LOS 速度场、位移时序（含 DEM 误差去除版本）、时间相干、空间平均相干、有效干涉对数图、连通分量与时间相干掩膜，以及残差时序与斜面去除诊断量。

**图 9** 基线网络图（已具备，由网络解算阶段自动输出）：横轴日期、纵轴垂直基线（m）；节点为 7 期影像，连边为 15 对入选干涉。

**图 10** E4 时序解算结果四联图（已具备，由 MintPy 自动输出，待排版）：(a) 平均 LOS 速度场；(b) 时间相干；(c) 空间平均相干；(d) 有效干涉对数。

**图 11** 典型像元位移时序曲线（可选，待绘）：从 DEM 误差去除后的时序数据中抽取 1–2 个高相干像元，叠加线性拟合速度。

### 3.7 实验结果讨论

四个实验在共享研究区与 DEM 的前提下揭示出底层工具链在配置形态、产物原子性与并发能力上的稳定差异。ISCE2 路径以多文件 XML 与脚本承载配置，产物分散于多目录；ISCE3 路径以单文件 YAML 承载配置，每对干涉对应单一 GUNW HDF5 文件，并具备 GPU 加速能力。结构化 YAML 便于程序化生成与差量编辑，原子化产物便于并发与重入：E3 与 E4 共 21 对干涉在单节点 8 路并发下完成幂等批处理，而 ISCE2 路径中"参考几何 → 配准 → 干涉 → 时序"的级联依赖需要更细粒度的步级调度。该差异源自工具链的设计代际，与具体智能体实现无关。

频段差异在实验结果中同样清晰呈现。C 波段（E1 与 E2）对地表植被与含水量变化较为敏感，相干衰减相对快；L 波段（E3 与 E4）穿透性强，在 73 天时基下仍维持中等以上相干，更适合时序反演。两套实验的 LOS 速度场在裸地与城镇区域量级一致，可作为后续跨频交叉验证的基线。MintPy 在两条路径上均表现出一致的兼容性：ISCE2 topsStack 经常规 ifgramStack 构造提供输入，ISCE3 GUNW 则被直接读入，两套时序产品在结构上对齐（速度场、位移时序、时间相干、空间平均相干、有效干涉对数、连通分量与时间相干掩膜），可在统一框架下做跨数据与跨算法对比。

实验结果同时受到若干因素的限制。NISAR 数据为研究区子窗口的 cropped RSLC，相关结论不可外推至 Track 172 整景；时序样本量较小（E2 仅 2 对、E4 仅 15 对，时基跨度 73 天），不足以建立长时形变结论；两套数据的时间窗错开（NISAR 时间窗 2025-10 至 2026-01，Sentinel-1 时间窗 2026-01 至 2026-04），跨频比较仅在量级与空间分布层面进行，不构成同时段对比；对流层与电离层延迟修正在多数实验中未启用，对 L 波段大尺度形变估计可能引入低频偏差。此外，本研究对智能体编排能力的评估限于"端到端贯通性"层面，未对编排开销与参数搜索质量等进行定量基准，相关工作留待专项研究。

---

## 4. 讨论

### 4.1 与现有遥感 Agent 框架的对比

将 InSAR-Agent 与遥感 Agent 谱系中具有代表性的 6 个工作进行对比（表 4），可以从协议、规模、扩展性与安全性四个维度看出本研究的定位。

**表 4** InSAR-Agent 与代表性遥感 Agent 的对比

| 工作 | 协议层 | 工具规模 | 工作流约束载体 | 参数安全机制 | 引擎扩展模式 |
|------|--------|----------|----------------|--------------|--------------|
| RS-Agent [8] | LangChain | 18 | 内嵌 docstring + DualRAG | — | 工具集预定义 |
| Change-Agent [9] | 自定义 | N/A | LLM 提示词 | — | 单一任务 |
| Smart-QGIS [10] | MCP | QGIS 工具链 | LLM 提示词 + QGIS 内置 | — | 与 QGIS 强绑定 |
| Earth-Agent [17] | MCP | 104 | 工具 docstring | — | 五大工具箱预定义 |
| OpenEarth-Agent [18] | 多代理 + 代码合成 | 6 base + ∞ 合成 | 子 Agent 内化 | 代码合成校验 | 工具创建（动态合成） |
| 齐析屿等 [16] | 自定义 + DAG | 可扩展 | DAG 依赖图 | — | 数据—工具自适应匹配 |
| **InSAR-Agent** | MCP + Skills | 15 + 4 类受控参数 YAML | **Skills + Prompts + Resources + Tool YAML 多机制分层** | **Advisory–Execution 双通道架构隔离** | Protocol-based（4 模块即可接入） |

InSAR-Agent 的差异化定位在于：（1）以**最小工具集 + 最大约束机制**应对 InSAR 步骤顺序严格、错误代价高的工程特点；（2）以 Skills 机制为核心载体表达步骤顺序约束，而非依赖 LLM 提示词或 docstring；（3）以 Advisory–Execution 双通道架构在参数推理与工程执行之间引入显式隔离，与 Superego [20] 的 MCP 安全监督思路构成"内置隔离 + 外部监督"的互补关系。Earth AI [19] 代表的工业界路线以 Gemini 一体化推理统合多模态地理空间任务，而本研究路径正相反：以 MCP 协议化与模板化方式，让人类专家以低成本贡献新引擎、新参数、新工作流，更适合学术机构与开源社区的协作场景。

### 4.2 人机协同设计哲学的适用边界

InSAR-Agent 采用"用户为最终决策者"的强人机协同立场。这一立场在三类场景下是必要约束：（1）**长时计算场景**——单像对 D-InSAR 通常需要 20 分钟以上，Stack-InSAR 时序处理可能耗时数小时至数天，幻觉参数将导致严重的算力浪费；（2）**高风险参数场景**——多视数、相位解缠算法、大气校正策略等核心参数错误会污染整条形变时间序列；（3）**学术发表场景**——审稿人需要对处理流程进行可追溯的复盘，全自动黑盒难以满足同行评议要求。

在以下场景中可以适度放宽：（1）**低风险探索性分析**——例如形变热点初步识别、剖面提取等可重复执行的轻量分析，可允许 `auto` 模式直接由 Agent 完成；（2）**参数空间已收敛后的批量复用**——当 `param_tuned_config` 文件存在时，Skill 可在 `auto` 模式下直接复用，无需再次进入 Advisory 通路。

### 4.3 局限性

本研究存在以下局限：

1. **引擎覆盖**：当前仅实现 ISCE3 与 ISCE2 两个引擎，GAMMA、SNAP 等主流商业/开源 InSAR 软件尚未接入，跨机构协作场景下的通用性仍需进一步验证。
2. **后分析工具集**：剖面提取、热点识别、报告生成等工具尚处规划与原型阶段，与真实 GUNW/MintPy 输出的端到端测试覆盖有限。
3. **评测基准**：Agent 端到端评测（InSAR-Bench）目前仅有原型，规模与 Earth-Bench [17]、OpenEarth-Bench [18] 等公开基准相比仍有差距，且 InSAR ground truth（如 GNSS 形变时间序列）的获取受地理与时间制约。
4. **证据档案维护成本**：Advisory 通路依赖的 `param-advisor-isce{2,3}.md` 证据档案需要随 ISCE3/ISCE2 版本更新而维护；当前由领域专家手动编写，未来可探索半自动化的证据沉淀机制。
5. **多模态后分析的开放性**：当前后分析以数值与文本输出为主，是否引入多模态 LLM（将 GUNW 缩略图喂给视觉模型）尚需权衡处理质量与外部 API 依赖。

### 4.4 未来展望

未来工作将围绕四个方向推进：

1. **GAMMA / SNAP 引擎接入**，验证 Protocol-based 引擎扩展架构在异构 InSAR 软件上的通用性；
2. **InSAR-Bench 端到端评测扩展**，参考 Earth-Bench [17] 的双层评估与 OpenEarth-Bench [18] 的全流程要求，构建包含 5–8 个真实任务的多 backbone 对照基准；
3. **GNSS 时序联合分析**，将 GNSS 站点形变作为 ground truth 注入后分析工具，提升量化报告的科学价值；
4. **多模态形变报告**，结合 Earth AI [19] 所示工业级跨模态推理思路，将 GUNW 缩略图、光学影像、行政区划等多源信息融合为决策支持文档。

---

## 5. 结论

本文提出 InSAR-Agent——一个将大语言模型 Agent 与专业 InSAR 软件深度融合的全流程智能体框架，旨在突破传统 InSAR 处理流程对领域专家的高度依赖，降低 D-InSAR 单像对处理与 Stack-InSAR 时序分析的操作门槛。

在架构层面，InSAR-Agent 采用三层解耦设计：交互指引层以 Skill 与 Subagent 承载领域工作流知识，MCP 协议编排层以 15 个工具、2 个资源与 2 个提示统一暴露 InSAR 能力，引擎执行层通过 `EngineAdapter` 协议将 ISCE3 与 ISCE2 两套异构处理软件纳入同一工具体系。三层之间的边界确保任何一层的改动不会扩散到其他层，也为后续接入 GAMMA、SNAP 等第三方引擎提供了清晰的扩展路径。

在安全性层面，本文提出 Advisory–Execution 双通道参数顾问架构，将 LLM 参数推理通路（Advisory）与确定性 YAML 白名单校验通路（Execution）在架构层面解耦。子 Agent 仅输出带证据链的参数建议，经过用户三选一确认后，`insar_set_processing_param` 工具对修改请求进行类型、范围与枚举值的确定性校验，从而阻断幻觉参数进入 runconfig。这一机制与现有遥感 Agent 工作 [8,17,18] 中将参数推理与执行融为一体的做法形成对照，并与 Superego [20] 的 MCP 安全监督思路在哲学上互补，共同体现 MCP 协议在构建可信 Agent 流水线中的潜力。

在知识工程层面，InSAR 工作流硬约束被系统性映射到 Skills、MCP Prompts、MCP Resources 与 MCP Tool 内嵌 YAML Schema 四类机制——其中 **Claude Code Skills 机制是步骤顺序约束的首选载体**，以编号步骤、强制中断点与失败回退策略明确规定 Agent 的可执行轨迹；MCP Prompts 作为不支持 Skills 的客户端的备用机制；路径字段白名单与参数语义约束则通过 MCP Resources 与 Tool 内嵌 YAML 表达。分层领域知识体系将工程经验档案、参数证据档案与工作流约束资源按查询粒度分层组织，使 Agent 在"下一步做什么""参数如何取值""遭遇非标问题"三类不同查询场景下均能走向最适合的知识通路。

在可扩展性与可复现性层面，Protocol-based 引擎接入仅需四个最小模块；统一 Job 数据模型与 `jobs/{job_id}.json` 完整快照支持任意历史任务的一键复现；MCP-First 的客户端无关设计使 InSAR-Agent 可无缝接入 Claude Code、Codex 及任意符合 MCP 标准的 Agent 宿主，区别于 Smart-QGIS [10] 等与单一 GIS 平台强绑定的方案。

未来工作将重点推进 GAMMA 引擎接入、InSAR-Bench 端到端 Agent 评测建设，以及与 GNSS 时序联合分析、多模态形变报告等扩展能力，进一步将"AI Agent + 专业 InSAR 软件 + 协议化领域知识"统一在 MCP-First 工程框架下，为定量遥感反演领域提供 Agent-原生的处理基础设施。

---

## 参考文献

[1] Talemi N A, Boone J, Afghah F. Agentic AI in remote sensing: Foundations, taxonomy, and emerging systems [J/OL]. arXiv preprint arXiv:2601.01891, 2026.

[2] Tang J, Yan Y, Wang Q, et al. Intelligent remote sensing agents: A survey [J/OL]. arXiv preprint, 2026.

[3] Anthropic. Model Context Protocol specification [EB/OL]. https://modelcontextprotocol.io, 2024.

[4] 张锋, 尹东, 吴文宇. 基于 Agent 技术的遥感图像检索 [J]. 通信技术, 2008, 41(10): 119-121.

[5] 许文嘉, 于睿卿, 薛铭浩, 等. 遥感多模态大语言模型：架构、关键技术和未来展望 [J]. 雷达学报, 2025. DOI: 10.12000/JR25088.

[6] Zhang Y, Wang Z, He Z, et al. BB-GeoGPT: A framework for learning a large language model for geographic information science [J]. Information Processing and Management, 2024, 61(5): 103808.

[7] Zhang M, Yang B, Hu X, et al. Foundation model for generalist remote sensing intelligence: Potentials and prospects [J]. Science Bulletin, 2024, 69(24): 3652-3656.

[8] Xu W, Yu Z, Mu B, et al. RS-Agent: Automating remote sensing tasks through intelligent agent [J/OL]. arXiv preprint arXiv:2406.07089, 2026.

[9] Liu C, Chen K, Zhang H, et al. Change-Agent: Toward interactive comprehensive remote sensing change interpretation and analysis [J]. IEEE Transactions on Geoscience and Remote Sensing, 2024, 62: 1-16.

[10] 谭振宇, 杨安平, 马镇翼, 等. Smart-QGIS：空间数据处理与制图智能体 [J]. 地球信息科学学报, 2026, 28(4): 1007-1019. DOI: 10.12082/dqxxkx.2026.250585.

[11] 魏智威, 杨乃, 王一杰, 等. MapColor-Agent：融合大语言模型与多智能体的行政区划图配色框架 [J]. 测绘学报, 2026, 55(2): 359-370. DOI: 10.11947/j.AGCS.2026.20250436.

[12] Song J, Zhang Y, Wang Z, et al. Large language model agent with VGI data for mapping [J]. Journal of Geodesy and Geoinformation Science, 2025, 8(2): 57-73. DOI: 10.11947/j.JGGS.2025.0204.

[13] Weiss M, Rahaman N, Pal C. MapBot: A multi-modal agent for geospatial analysis [C]//Proceedings of the 24th International Conference on Autonomous Agents and Multiagent Systems (AAMAS 2025). Detroit, USA, 2025: 3059-3061.

[14] Taggio N, Samarelli S, Simone M. SAI4EO: Symbiotic artificial intelligence for earth observation [C]//Ital-IA 2024: 4th National Conference on Artificial Intelligence. Naples, Italy, 2024.

[15] Ames D P. Mapping water: A brief history of GIS in hydrology and a path toward AI-native modeling [J]. Water, 2026, 18(7): 796.

[16] 齐析屿, 等. 大模型-智能体协同驱动的动态可扩展遥感目标智能解译系统研究 [J]. 空间工程大学学报, 2026.

[17] Feng P, Lv Z, Ye J, et al. Earth-Agent: Unlocking the full landscape of earth observation with agents [C]//International Conference on Learning Representations (ICLR), 2026.

[18] Zhao S, Liu F, Zhang X, et al. OpenEarth-Agent: From tool calling to tool creation for open-environment earth observation [J/OL]. arXiv preprint arXiv:2603.22148, 2026.

[19] Google Research. Earth AI: Unlocking geospatial insights with foundation models and cross-modal reasoning [J/OL]. arXiv preprint arXiv:2510.18318v4, 2026.

[20] Sebastian, et al. Personalized constitutionally-aligned agentic superego: Secure AI behavior aligned to diverse human values [J]. Information (MDPI), 2025.

[21] Yu Y, Li B, Li Y, Jiang W. Retrospective analysis of glacial lake outburst flood (GLOF) using AI Earth InSAR and optical images: A case study of South Lhonak Lake, Sikkim [J]. Remote Sensing, 2024, 16(13): 2307.

[22] Pisetta J, Souza F A, Amorim J, et al. Mapping with words: Integrating large language models into geospatial practice [J]. ISPRS Annals of the Photogrammetry, Remote Sensing and Spatial Information Sciences, 2025, X-3/W4: 285-292.

[23] Anthropic. Claude Code Skills: Declarative agent workflow specification [EB/OL]. https://docs.claude.com/en/docs/claude-code/skills, 2025.

[24] Chen C W, Zebker H A. Phase unwrapping for large SAR interferograms: Statistical segmentation and generalized network models [J]. IEEE Transactions on Geoscience and Remote Sensing, 2002, 40(8): 1709-1719. [SNAPHU；终稿期 DOI 待补]

[25] Yunjun Z, Fattahi H, Amelung F. Small baseline InSAR time series analysis: Unwrapping error correction and noise reduction [J]. Computers & Geosciences, 2019, 133: 104331. [MintPy；终稿期 DOI 待补]

[26] Yague-Martinez N, Prats-Iraola P, Rodriguez Gonzalez F, et al. Interferometric processing of Sentinel-1 TOPS data [J]. IEEE Transactions on Geoscience and Remote Sensing, 2016, 54(4): 2220-2234. [可与 Prats-Iraola P, et al. TOPS interferometry with TerraSAR-X. IEEE TGRS, 2012 合并引用；终稿期 DOI 待补]

[27] Rosen P A, Gurrola E, Sacco G F, et al. The InSAR Scientific Computing Environment [C]//IEEE International Geoscience and Remote Sensing Symposium (IGARSS). 2012: 730-733. [ISCE/ISCE2；可与 Rosen et al. (2018) 软件文档合并引用；终稿期 DOI 待补]

[28] NISAR Mission Science Team. NISAR L1 RSLC data product specification and `nisar.workflows.insar` workflow documentation [EB/OL]. NASA-ISRO SAR Mission, JPL. [终稿期补 URL 与发布年份]

[29] European Space Agency. Copernicus Digital Elevation Model: Global 30 m product specification [EB/OL]. ESA Copernicus Programme. [终稿期补 URL 与发布年份]
