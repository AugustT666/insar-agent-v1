# InSAR 处理工作流：MCP 工具说明

本文档以处理流程为主线，说明每个 MCP 工具在 InSAR 数据处理中的具体作用，以及工具背后的逻辑来自哪些知识库脚本。

---

## 处理路径总览

insar-agent 支持两条主要处理路径：

```
路径 A（单对干涉）：
  数据准备 → 创建项目 → 填写参数 → 运行 ISCE3 → 导出产品

路径 B（多景批处理 → 时序分析）：
  数据准备 → 生成批处理配置 → 并行运行 → 生成干涉图网络 → 时序分析
```

两条路径共用数据准备和产品导出步骤。AI Agent 通过 MCP 工具完成全流程，不直接执行 conda/Python 命令。

---

## 数据准备（两条路径共用）

### `insar_download_rslc` — 按研究区范围裁剪下载 RSLC

用户提供 RSLC URL 列表，以及研究区 AOI 文件或显式 bbox。工具先解析 AOI/bbox，再用远程 HDF5 按研究区范围只下载所需像元，输出裁剪后的 RSLC 文件。

> 来源：wangshuai 的 `nisar-test-download_v2.py`

### `insar_download_dem` — 按研究区范围下载 Copernicus 30m DEM

用户提供 AOI 文件或显式 bbox，工具解析范围后为该区域下载 Copernicus 30m DEM，并输出可直接给后续流程使用的 GeoTIFF。

### `insar_describe_rslc` — 提取参数专家所需的本地元数据画像

对单景或一对 RSLC 文件做 metadata-first 摘要，优先从 HDF5 中提取信息，不足时退回文件名推断，并附带当前项目的 processing context。参数专家会先使用这个工具构建证据，再决定是否需要补充外部资料搜索。

---

## 路径 A：单对 D-InSAR 处理

### `insar_create_project` — 建立处理项目

新建一个处理工作区，加载指定工作流（`insar` 或 `gslc`）的默认 runconfig 模板，生成项目 ID 供后续工具引用。同时返回**必填字段列表**，告知 AI 下一步需要填写哪些参数（输入文件路径、DEM、输出目录等）。

### `insar_get_runconfig` — 查看当前配置

读取项目当前的 runconfig 内容，可以查看某个具体字段或整份配置，方便核查参数是否填写正确。

### `insar_set_runconfig_value` — 填写处理参数

按"字段路径"逐一填入 runconfig 中的参数。AI 对照必填字段列表，逐一调用此工具填入实际路径和数值。传入空值 (`null`) 则清除该字段。

### `insar_set_processing_param` — 调整处理算法参数

设置影响处理质量的算法参数，例如 multilook 比例、解缠算法（snaphu / icu）、电离层校正开关等。参数范围受白名单约束，避免误改关键配置字段。对 skill-aware 客户端，通常由 `param-advisor` 先调用 `insar_describe_rslc` 构造本地证据，再调用 `agents/param-advisor.md` 定义的项目级 subagent 生成带 provenance 的 advisory 建议；subagent 可参考 `agents/references/param-advisor-isce{engine}.md`，最后由主 agent 调用此工具应用。

### `insar_run_workflow` — 启动 ISCE3 处理

校验配置 → 导出 runconfig YAML → 在 conda 环境中后台启动 ISCE3，三步自动串联，无需分别操作。ISCE3 在后台运行，不阻塞对话。工具返回 `log_path`，用户可用 `tail -f <log_path>` 实时查看 ISCE3 的输出；AI 同时通过 `insar_get_job` 轮询完成状态。

### `insar_get_job` — 查询处理进度

查询任意正在运行的处理任务的当前状态（pending / running / done / failed），可选附带最新日志片段。适用于三类任务：单对 D-InSAR（通过 `project_id`）、批处理（通过 `batch_dir`）、MintPy 时序（通过 `work_dir`）。

### `insar_list_outputs` — 查看输出产品

扫描项目的输出目录，返回已生成的 GUNW/GSLC 等产品文件列表及文件大小。在 `insar_get_job` 返回 `done` 后调用，确认产品文件已生成。

### `insar_export_geotiff` — 导出为 GeoTIFF

从 GUNW 或 GSLC 的 HDF5 文件中提取指定数据集（如 `unwrappedPhase`、`coherence`），导出为 GeoTIFF 格式，同时生成 PNG 快视图便于查看。

> 来源：tianxiaolong 的 `save_geotiff_nisar.py`

---

## 路径 B：批处理 Stack + 干涉图网络

批处理路径不使用项目注册表，直接操作文件系统。每个步骤生成可并行执行的脚本，由 `insar_run_batch` 统一负责执行。

### `insar_prepare_stack` — 生成单参考景批处理配置

给定一批 RSLC 文件和一份基础 runconfig 模板，自动选定参考景（默认最早日期），为每对（参考景–次级景）生成独立的 runconfig，并写出并行执行脚本 `run_parallel.sh`。输出目录即 `batch_dir`，交由 `insar_run_batch` 执行。

> 来源：wangshuai 的 `prepare_isce3_stack.py`

### `insar_prepare_network` — 生成干涉图网络配置

在 stack 基础上，按选定的网络策略筛选干涉对，为每对生成 runconfig，写出并行执行脚本。同时返回 `gunw_pattern`（产品文件路径模式），供后续 MintPy 定位产品使用。

网络策略：
- `tbase`：保留时间基线 ≤ N 天的所有干涉对
- `conn`：每景与相邻 N 景各组合一对
- 自定义：从文件读取 `YYYYMMDD_YYYYMMDD` 对列表

> 来源：wangshuai 的 `prepare_isce3_network.py`

### `insar_run_batch` — 启动并行批处理

执行 `insar_prepare_stack` 或 `insar_prepare_network` 生成的并行脚本，在后台同时启动多个 ISCE3 进程并行处理。返回 `log_path`，用户可用 `tail -f <log_path>` 实时查看汇总输出；AI 同时通过 `insar_get_job(batch_dir=...)` 轮询完成状态。

"生成配置"（prepare）和"执行"（run_batch）分为两个独立工具，是因为用户可能需要在生成配置后检查或修改 runconfigs，或对失败的批次重新执行，而不需要重新生成配置。

---

## 时序分析（路径 B 续）

### `insar_run_mintpy` — 运行时序形变分析

调用 MintPy 对整个干涉图网络做时序处理：准备输入数据 → 应用相干掩膜 → 相位连接、网络解缠、大气校正、形变速率估算。产出时序形变图和速率图。

> 来源：wangshuai 的三个脚本合并：`run_mintpy_nisar_stack.sh`（主流程）、`prep_nisar_current_gunw.py`（输入准备）、`apply_common_ifgram_mask.py`（相干掩膜）。合并为一个工具是因为三者在实际处理中必然顺序执行，用户无需分别调用。

### `insar_plot_baseline` — 可视化基线网络

绘制所有干涉对的时空基线分布图（横轴：时间，纵轴：垂直基线），帮助评估网络连通性和冗余度。输出 PNG/PDF 和基线数据 CSV。建议在 `insar_prepare_network` 之后、正式运行之前调用，确认网络结构合理。

> 来源：wangshuai 的 `plot_isce3_baseline_network.py`

---

## 辅助工具

### `insar_discover` — 查询支持的引擎和工作流

返回当前服务支持的引擎（如 `isce3`）和可用工作流（如 `insar`、`gslc`）列表，供 AI 在对话开始时了解自身能力范围。

### `insar_get_project` — 查询项目信息

读取已注册项目的基本信息（引擎、工作流、workspace 路径）和当前 runconfig 内容，用于核查项目状态。

---

## 知识库脚本改造说明

知识库脚本（来自 tianxiaolong 和 wangshuai）原本均为命令行工具，改造时遵循以下原则：

1. **保留核心逻辑**：处理算法、文件读写、YAML 模板操作等核心代码保持原样，注明来源脚本和原作者
2. **移除命令行入口**：删除 `argparse` / `sys.argv` 部分，改为函数参数
3. **边界校验前移**：文件是否存在、路径是否合法等检查，统一移到 MCP 层处理，引擎函数只处理已验证的输入
4. **结构化返回**：原来打印到终端的信息，改为字典格式返回给 AI

---

## 文件索引

| 路径 | 内容 |
|-----|------|
| `docs/archive/knowledge-base/wangshuai/Scripts/` | wangshuai 提供的 Stack/MintPy 处理脚本 |
| `docs/archive/knowledge-base/tianxiaolong/original-skill/nisar-processing/scripts/` | tianxiaolong 提供的数据准备脚本 |
| `src/insar_agent/engines/isce3/` | 改造后的引擎层模块（保留知识库脚本核心逻辑） |
| `src/insar_agent/mcp/server.py` | 全部 MCP 工具定义 |
| `docs/mcp-tools.md` | 每个工具的完整参数和返回值规范 |
