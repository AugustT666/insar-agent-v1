# 基于大语言模型的 Agent 技术在遥感领域的研究现状

## 1. 智能 Agent 在遥感领域的早期探索

智能 Agent 作为一种具有自治性、反应性、能动性、学习性、通用性和移动性的计算实体，在大语言模型（Large Language Models, LLM）兴起之前便已被引入到遥感图像处理领域 [1]。这一时期的 Agent 主要基于传统的 BDI（信念—需求—意图）框架，通过模块化与知识库匹配的方式解决遥感图像检索、特征提取等具体任务 [1]。然而，受限于规则系统与浅层机器学习方法的表达能力，早期 Agent 缺乏对自然语言意图的理解能力与跨任务的泛化能力，仅能完成预定义的、相对单一的处理流程，难以胜任复杂的多源遥感分析与决策任务。

随着深度学习方法在遥感场景分类、变化检测、目标识别等任务上的快速发展 [2,3]，遥感解译能力得到显著提升，但模型仍以"任务专用、被动前馈"的方式运行，缺少自主推理与工具调度能力 [3]。这种范式的内在局限催生了将 LLM 与 Agent 思想引入遥感领域的研究热潮。

## 2. 多模态大语言模型驱动的遥感解译

近年来，以 ChatGPT、LLaMA、Qwen、DeepSeek 等为代表的大语言模型在自然语言理解和复杂语义推理方面展现出惊人能力，并迅速被引入遥感领域，催生了遥感多模态大语言模型（Remote Sensing Multimodal Large Language Model, RS-MLLM）这一研究方向 [4]。许文嘉等系统梳理了 RS-MLLM 的发展脉络，指出其通过视觉编码器与语言模型的桥接机制和联合训练策略，在遥感场景分类、视觉问答（VQA）、图像描述（Image Captioning）等任务上推动了从浅层语义匹配到高层世界知识理解的跃迁 [4]。代表性工作包括 GeoChat、LHRS-Bot、RSGPT、SkyEyeGPT、EarthGPT、RS-LLaVA 等基于视觉指令调优的 RS-MLLM [2,4]。

针对地理信息科学（GIS）领域专业知识在通用 LLM 中的稀缺问题，研究者还构建了一系列领域大模型，如 BB-GeoGPT [5] 通过收集 GIS 文献预训练语料与指令微调数据，对 LLaMA-2-7B 进行轻量化领域适配，在地理术语理解与空间任务求解上显著优于通用 LLM；类似工作还包括 GeoGPT、坤元、GeoGalactica、K2 等 [5,6]。

然而，正如 Talemi 等 [2] 与 Tang 等 [3] 指出，单纯的 RS-MLLM 仍面临三方面瓶颈：（1）缺乏对长时序、多步骤工作流的规划与记忆能力；（2）静态参数中编码的知识无法及时更新，难以整合外部领域知识与专家模型；（3）输入模态多以 RGB 影像为主，对 SAR、高光谱、热红外等专业模态以及大批量影像的处理能力有限。这些局限直接催化了"LLM + Agent + 工具调用"范式在遥感领域的兴起。

## 3. LLM 驱动的遥感单智能体系统

为弥合 RS-MLLM 与真实遥感工作流之间的鸿沟，研究者提出了一系列以 LLM 为中央控制器、以专业模型与工具为执行单元的遥感 Agent 系统。

Xu 等提出的 **RS-Agent** 是该范式的代表性工作 [7]。RS-Agent 由四部分构成：基于 LLM 的中央控制器、动态可扩展的工具集（Toolkit）、用于任务规划的解决方案空间（Solution Space）以及承载领域知识的知识空间（Knowledge Space）；并通过任务感知检索（Task-Aware Retrieval）与 DualRAG 双路检索机制提升任务规划准确率与领域知识利用效率，在 18 项遥感任务上的任务规划准确率超过 95% [7]。

Liu 等的 **Change-Agent** 则面向遥感双时相变化解译，将多级变化解译模型（MCI）作为"眼睛"、LLM 作为"大脑"，支持用户通过自然语言指令完成变化检测、变化描述、对象计数、原因估计与未来预测等综合任务 [8]。

在制图与地理信息处理方向，**Smart-QGIS** [9] 基于模型上下文协议（Model Context Protocol, MCP）将 LLM 与 QGIS 原生工具链桥接，构建了支持本地化部署的"数据加载—空间处理—专题制图"全流程智能体；**MapColor-Agent** [10] 则通过多智能体协同将地图配色专业知识嵌入工具流，实现自然语言驱动的行政区划图配色；Song 等 [11] 利用提示工程将 LLM Agent 接入志愿者地理信息（VGI）数据，自动化完成从数据获取到地图生成的端到端制图流程；Weiss 等的 **MapBot** [12] 则在 REPL 循环中将 LLM 与 SAM、DINOv2 等视觉基础模型协同调度，为非专业用户提供交互式地理空间分析。

此外，**SAI4EO** [13] 提出"共生人工智能"（Symbiotic AI）理念，强调人机协同环境下的对地观测助手系统；Ames [14] 在水文领域综述中亦预言了"AI-原生空间水文建模"——具备空间感知能力的 AI Agent 可直接对地理空间数据进行推理，进而模糊乃至消除传统 GIS 与水文模型之间的软件界面。

## 4. 多智能体协同与工具协议化

随着任务复杂度的上升，研究重心逐步从单 Agent 向多 Agent 协同、以及工具调用协议的标准化演进。

Feng 等提出的 **Earth-Agent** [15] 是首个将感知数据（RGB）与谱段数据（Spectrum、Products）统一在 MCP 架构下的对地观测 Agent 框架。其将 104 个专业工具按 Index、Inversion、Perception、Analysis、Statistics 五大维度组织成结构化工具箱，并通过 ReAct 推理实现跨模态、多步骤的定量时空分析，在配套的 Earth-Bench 基准上显著超越通用 Agent 与遥感 MLLM。Feng 等同时强调，MCP 协议作为标准化的工具调用接口，是支撑 Agent 与异构科学软件互操作的关键基础设施 [15]。

针对"封闭工具集难以泛化到未见数据与任务"的根本性难题，Zhao 等进一步提出 **OpenEarth-Agent** [16]，将传统的"工具调用"范式扩展为"工具创建"——Agent 通过实时数据探查、自适应工作流规划与代码合成，动态生成贴合具体数据/任务的专用工具，从而在开放环境下完成端到端 EO 流程，并在 OpenEarth-Bench 等基准上验证了其跨域泛化能力。

Talemi 等 [2] 与 Tang 等 [3] 在系统综述中将上述工作进一步抽象为：单智能体（如 RS-Agent、ChatGeoAI、EmbodiedCity）与多智能体（如 GeoLLM-Squad、RingMo-Agent、MineAgent、Earth-Agent）两大谱系，并归纳出感知—规划—行动—记忆的核心循环以及 RAG、知识图谱、工具协议等关键支撑技术。

## 5. 现有研究的局限与本研究的切入点

综合上述文献可以看到，LLM Agent 在遥感领域的研究虽已快速展开，但仍存在若干尚未解决的关键缺口：

**（1）任务覆盖偏向感知与制图，缺少对定量物理反演的深度支持。** 现有 Agent 大多聚焦于场景分类、变化检测、视觉问答、地图生成等"感知/解译"任务 [2,3,7,8,12]，对需要严格物理建模与多步参数耦合的专业反演任务（如合成孔径雷达干涉测量 InSAR、地表形变时间序列分析等）缺乏系统支持。即便涉及 InSAR 的工作 [17]，亦多停留在"AI 平台 + InSAR 流程"的云端集成层面，并未真正引入具备规划与决策能力的 LLM Agent。

**（2）专业软件深度集成不足。** 现有遥感 Agent 普遍以 Python 库或 GIS 内置算子为工具节点 [9-12,15]，对 ISCE2、ISCE3、GAMMA 等需要复杂 runconfig 配置、conda 环境隔离、长时计算与文件级中间产物管理的专业 InSAR 软件，尚缺乏可复用、可验证的封装方案。

**（3）工作流约束与领域知识难以以 Agent-原生形式表达。** Earth-Agent [15]、OpenEarth-Agent [16]、Smart-QGIS [9] 等已开始以 MCP 协议规范工具接口，但 InSAR 工作流中"严格的步骤顺序""工程参数白名单""runconfig 字段约束""先验基线/网络几何"等硬性约束，仍依赖人类专家在每次运行前手动校验，难以转化为 Agent 可直接消费的协议化资源（Resources）与提示（Prompts）。

**（4）双引擎与多任务路径下的统一编排缺位。** 真实 InSAR 业务往往同时涉及单像对 D-InSAR 与时序 Stack-InSAR、ISCE3/NISAR 与 ISCE2/Sentinel-1 双引擎、以及与 MintPy 等下游时序分析软件的衔接，而现有 Agent 框架普遍未对这种多路径、多后端、多长时任务的统一编排提供原生支持。

**针对上述缺口，本研究提出 InSAR-Agent——一个以 MCP 为核心、以 Skills 机制承载领域知识的 InSAR 工作流智能体框架。** 在设计哲学上，本研究明确以"人为最终决策者"为前提：Agent 负责工作流编排、参数推理与结果量化，但参数修改须经用户审批方可落盘，InSAR 产品的质量判断亦由领域专家把关。这一人机协同（Human-in-the-loop）立场区别于"全自动化黑盒"思路，更符合定量物理反演对可追溯性与可控性的严格要求。在此框架下，本研究的主要贡献体现在以下五个方面：

第一，**面向 InSAR 全流程的双引擎统一编排**。InSAR-Agent 同时支持 NISAR/ISCE3 与 Sentinel-1/ISCE2 两条数据流，将场景发现、数据下载、DEM 准备、runconfig 生成、参数调优、批处理执行、MintPy 时序解算、GeoTIFF 导出等步骤抽象为统一的 Job 与 Project 数据模型，覆盖 D-InSAR（单像对）与 Stack-InSAR（时序）两类典型工作流，并为后续引入 GAMMA、SNAP 等第三方引擎预留了标准化扩展接口，为 InSAR 领域开发者社区的协同共建提供了基础设施。

第二，**Advisory–Execution 双通道参数顾问设计**。本研究提出一种原创性的参数推理架构：以 Skill 为薄编排层，委派专用子 Agent（Param-Advisor Subagent）读取元数据与证据档案（Evidence Profile），生成带引用的参数建议；用户确认后，由 MCP 工具依据 YAML 白名单（含类型、范围、风险等级约束）做确定性校验，方可将修改落盘至 runconfig。这一设计将 LLM 推理（advisory）与工程执行（execution）解耦到两条独立通路，既保留了子 Agent 推理引擎可替换的灵活性，又通过白名单机制从架构层面杜绝幻觉参数进入工程流水线——这是目前 RS-Agent [7]、Earth-Agent [15]、OpenEarth-Agent [16] 等工作均未显式提出的机制。

第三，**工作流硬约束的协议化表达**。区别于现有 Agent 系统依赖提示词隐式约束操作顺序的做法，本研究将 InSAR 工作流约束系统性地拆解并映射到 MCP 三类原语：步骤顺序约束通过 MCP Prompts（`process_insar_pair`、`process_insar_batch`）表达；路径字段白名单通过 MCP Resources（`insar://allowed-fields/{workflow}`）动态下发；参数语义约束（类型、范围、枚举值、风险等级）通过 MCP Tool 的 YAML Schema 执行验证。这种"约束协议化"设计使 Agent 客户端能够在任何时刻主动查询工作流规则，而非被动依赖提示词中的文字描述。

第四，**InSAR 专业知识资源化与 AI 辅助结果后分析**。系统将 ISCE3/ISCE2 工程经验、运行参数原理、工作流约束等领域知识以"参数原理 + 工程经验 + 工作流约束"三元组形式组织为 MCP 可消费资源，支持自然语言驱动的 InSAR 专业问答。在处理结果层面，系统通过可扩展的后分析 Skill 与模板化脚本工具，提供形变剖面提取、异常形变区检测与量化报告生成等 AI 辅助分析能力；该机制遵循开放扩展原则——用户可根据具体需求自定义分析工具，AI 亦可按需合成新的分析脚本，与 OpenEarth-Agent [16] 的工具创建理念在专业反演场景中形成互补。

第五，**多 Agent 客户端兼容性与工作流可复现性**。基于 MCP 协议的客户端无关设计使 InSAR-Agent 可无缝接入 Claude Code、Codex 及任意符合 MCP 标准的 Agent 宿主，区别于 Smart-QGIS [9] 等与单一 GIS 平台强绑定的方案。每次处理任务的完整 runconfig 快照、执行命令与状态均持久化至 `jobs/{job_id}.json`，支持任意历史任务的一键复现，满足遥感定量研究对处理流程可追溯性的基本要求。

综上，InSAR-Agent 将"AI Agent + 专业 InSAR 软件 + 协议化领域知识"统一在 MCP-First 的工程框架下，以人机协同为设计原则，旨在为 InSAR 时序形变监测、地震/火山/滑坡灾害响应等场景提供可复现、可验证、可扩展的 Agent 原生处理能力，并对当前遥感 Agent 研究中"重感知、轻反演"的格局形成有益补充。

---

## 参考文献

[1] 张锋, 尹东, 吴文宇. 基于 Agent 技术的遥感图像检索 [J]. 通信技术, 2008, 41(10): 119-121.

[2] Talemi N A, Boone J, Afghah F. Agentic AI in remote sensing: Foundations, taxonomy, and emerging systems [J/OL]. arXiv preprint arXiv:2601.01891, 2026.

[3] Tang J, Yan Y, Wang Q, et al. Intelligent remote sensing agents: A survey [J/OL]. arXiv preprint, 2026.

[4] 许文嘉, 于睿卿, 薛铭浩, 等. 遥感多模态大语言模型：架构、关键技术和未来展望 [J]. 雷达学报, 2025. DOI: 10.12000/JR25088.

[5] Zhang Y, Wang Z, He Z, et al. BB-GeoGPT: A framework for learning a large language model for geographic information science [J]. Information Processing and Management, 2024, 61(5): 103808.

[6] Zhang M, Yang B, Hu X, et al. Foundation model for generalist remote sensing intelligence: Potentials and prospects [J]. Science Bulletin, 2024, 69(24): 3652-3656.

[7] Xu W, Yu Z, Mu B, et al. RS-Agent: Automating remote sensing tasks through intelligent agent [J/OL]. arXiv preprint arXiv:2406.07089, 2026.

[8] Liu C, Chen K, Zhang H, et al. Change-Agent: Toward interactive comprehensive remote sensing change interpretation and analysis [J]. IEEE Transactions on Geoscience and Remote Sensing, 2024, 62: 1-16.

[9] 谭振宇, 杨安平, 马镇翼, 等. Smart-QGIS：空间数据处理与制图智能体 [J]. 地球信息科学学报, 2026, 28(4): 1007-1019. DOI: 10.12082/dqxxkx.2026.250585.

[10] 魏智威, 杨乃, 王一杰, 等. MapColor-Agent：融合大语言模型与多智能体的行政区划图配色框架 [J]. 测绘学报, 2026, 55(2): 359-370. DOI: 10.11947/j.AGCS.2026.20250436.

[11] Song J, Zhang Y, Wang Z, et al. Large language model agent with VGI data for mapping [J]. Journal of Geodesy and Geoinformation Science, 2025, 8(2): 57-73. DOI: 10.11947/j.JGGS.2025.0204.

[12] Weiss M, Rahaman N, Pal C. MapBot: A multi-modal agent for geospatial analysis [C]//Proceedings of the 24th International Conference on Autonomous Agents and Multiagent Systems (AAMAS 2025). Detroit, USA, 2025: 3059-3061.

[13] Taggio N, Samarelli S, Simone M. SAI4EO: Symbiotic artificial intelligence for earth observation [C]//Ital-IA 2024: 4th National Conference on Artificial Intelligence. Naples, Italy, 2024.

[14] Ames D P. Mapping water: A brief history of GIS in hydrology and a path toward AI-native modeling [J]. Water, 2026, 18(7): 796.

[15] Feng P, Lv Z, Ye J, et al. Earth-Agent: Unlocking the full landscape of earth observation with agents [C]//International Conference on Learning Representations (ICLR), 2026.

[16] Zhao S, Liu F, Zhang X, et al. OpenEarth-Agent: From tool calling to tool creation for open-environment earth observation [J/OL]. arXiv preprint arXiv:2603.22148, 2026.

[17] Yu Y, Li B, Li Y, Jiang W. Retrospective analysis of glacial lake outburst flood (GLOF) using AI Earth InSAR and optical images: A case study of South Lhonak Lake, Sikkim [J]. Remote Sensing, 2024, 16(13): 2307.

[18] Pisetta J, Souza F A, Amorim J, et al. Mapping with words: Integrating large language models into geospatial practice [J]. ISPRS Annals of the Photogrammetry, Remote Sensing and Spatial Information Sciences, 2025, X-3/W4: 285-292.
