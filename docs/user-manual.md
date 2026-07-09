# InSAR-Agent 用户使用手册

> 本文档基于 `insar-agent` 项目源码、架构文档与技能文件整理而成，未对源文档做任何修改。

---

## 目录

1. [功能概述](#1-功能概述)
2. [系统架构简述](#2-系统架构简述)
3. [安装指南](#3-安装指南)
4. [详细操作指南](#4-详细操作指南)
   - [4.1 入口：启动 InSAR-Agent](#41-入口启动-insar-agent)
   - [4.2 功能一：单对 D-InSAR（ISCE3 / NISAR 数据）⭐](#42-功能一单对-d-insar-isece3--nisar-数据)
   - [4.3 功能二：单对 D-InSAR（ISCE2 / Sentinel-1 数据）⭐](#43-功能二单对-d-insar-isce2--sentinel-1-数据)
   - [4.4 功能三：多景 Stack/Network 批处理（ISCE3 / NISAR 数据）⭐](#44-功能三多景-stacknetwork-批处理-isece3--nisar-数据)
   - [4.5 功能四：多景 Stack 时序处理（ISCE2 / Sentinel-1 数据）⭐](#45-功能四多景-stack-时序处理-isce2--sentinel-1-数据)
   - [4.6 功能五：数据准备（NISAR RSLC）🔧](#46-功能五数据准备nisar-rslc)
   - [4.7 功能六：数据准备（Sentinel-1 SAFE + DEM + 轨道）🔧](#47-功能六数据准备sentinel-1-safe--dem--轨道)
   - [4.8 功能七：DEM 下载 🔧](#48-功能七dem-下载)
   - [4.9 功能八：MintPy 时序分析 🔧](#49-功能八mintpy-时序分析)
   - [4.10 功能九：ERA5 对流层改正（ISCE2）🔧](#410-功能九era5-对流层改正-isce2)
   - [4.11 功能十：结果导出与可视化 🔧](#411-功能十结果导出与可视化)
   - [4.12 功能十一：场景搜索与编目发现 🔧](#412-功能十一场景搜索与编目发现)
   - [4.13 功能十二：环境检查与安装 🔧](#413-功能十二环境检查与安装)
   - [4.14 功能十三：YODO 复盘与经验沉淀 🔧](#414-功能十三yodo-复盘与经验沉淀)
5. [附录：完整 MCP 工具速查表](#5-附录完整-mcp-工具速查表)

---

## 1. 功能概述

**InSAR-Agent** 是一个面向 AI Agent 的 InSAR（合成孔径雷达干涉测量）处理编排系统。它将专业 InSAR 处理软件（ISCE3/ISCE2/MintPy）封装为 28 个标准化的 MCP 工具，使 AI 助手（如 Claude Code）能够像人类专家一样执行完整的 InSAR 数据处理流程——从数据下载、参数调优、干涉图生成，到时序分析、结果可视化的全链路自动化。

**一句话总结：** InSAR-Agent 让用户通过与 AI 对话的方式完成专业的 InSAR 数据处理，无需记忆复杂的命令行参数和配置文件格式。AI 负责编排工具调用序列、优化处理参数、监控任务进度和处理异常，用户只需提供数据和目标。

**核心能力：**

- **双引擎支持**：同时覆盖 NISAR（ISCE3 / L 波段）和 Sentinel-1（ISCE2 / C 波段）两条数据处理流
- **完整处理链路**：Path A（单对 D-InSAR → 形变干涉图）和 Path B（多景时序 Stack → MintPy 形变速率）
- **AI 参数调优**：内置参数顾问（param-advisor）子系统，基于场景元数据、硬件资源和领域知识自动推荐最优处理参数
- **后台任务管理**：长时任务（数小时到数天）自动后台化，内置三层状态检测和断点续跑机制
- **统一输出规范**：所有产物遵循固定目录布局，两层日志体系（进度日志 + 引擎原始日志）便于监控和调试
- **可扩展架构**：基于 `EngineAdapter` 协议，新引擎（如 GAMMA、GMTSAR）可按规范接入，自动继承项目管理、Job 跟踪等基础能力

**用户使用方式：** 用户在 Claude Code 中输入 `/insar-agent` 启动 InSAR 会话，然后以自然语言描述需求（例如"帮我处理这两景 NISAR RSLC 数据，生成干涉图"），AI 会自动调用对应的 MCP 工具链完成处理。

---

## 2. 系统架构简述

```
┌─────────────────────────────────────────────────┐
│  第 1 层：Agent 交互层                           │
│  Claude Code + Skills + param-advisor subagent  │
│  用户通过 /insar-agent 入口，以自然语言交互       │
├─────────────────────────────────────────────────┤
│  第 2 层：MCP 编排层（28 个标准化工具）           │
│  项目管理 / Job 跟踪 / 参数白名单 / 输出布局      │
│  用户不可见的中间层，AI 自动调用                   │
├─────────────────────────────────────────────────┤
│  第 3 层：引擎执行层                             │
│  conda run -n isce3gpu / isce2 / mintpy ...     │
│  ISCE3/ISCE2/MintPy 在各自 conda 环境中运行      │
└─────────────────────────────────────────────────┘
```

所有产物统一落在：`<output_root>/<task>_<timestamp>/insar_product/<subdir>/`

共享输入（DEM、轨道、SAFE）落在：`<output_root>/prepare/<kind>/`（跨 run 复用）

---

## 3. 安装指南

### 3.1 前提条件

| 条件 | 说明 |
|------|------|
| 操作系统 | Linux（推荐 Ubuntu 20.04+） |
| Python | ≥ 3.10 |
| conda | Miniconda 或 Anaconda |
| Claude Code | 已安装并可正常使用 |
| 磁盘空间 | 建议 ≥ 500 GB（InSAR 数据量较大） |
| 内存 | 建议 ≥ 32 GB（处理全分辨率 S1 需 40-80 GB） |

### 3.2 安装步骤

#### 第一步：安装 insar-agent 包

```bash
# 进入项目目录
cd /home/august/insar-agent

# 以开发模式安装（会自动安装 mcp、pyyaml、matplotlib、h5py、numpy 等核心依赖）
pip install -e ".[dev]"

# 验证安装
insar-agent describe     # 应输出 JSON 摘要，显示 28 个工具
insar-agent doctor       # 应输出运行时环境信息
```

#### 第二步：根据数据类型安装处理引擎

**如果你处理 NISAR 数据（L 波段）：**

```bash
# GPU 版（推荐——速度快数倍）
conda create -n isce3gpu -c conda-forge \
    python=3.11 isce3-cuda snaphu h5py gdal numpy scipy matplotlib pysolid ruamel.yaml -y

# 如果只有 CPU
conda create -n isce3 -c conda-forge \
    python=3.11 isce3 snaphu h5py gdal numpy scipy matplotlib pysolid ruamel.yaml -y
```

**如果你处理 Sentinel-1 数据（C 波段）：**

```bash
conda create -n isce2 -c conda-forge isce2 -y

# 验证
conda run -n isce2 bash -c 'python $ISCE_HOME/applications/topsApp.py --help 2>&1 | head -3'
```

**如果你需要时序分析（MintPy）：**

```bash
# NISAR 路径（注意：必须 numpy<2，与 isce3gpu 环境隔离）
conda create -n mintpy -c conda-forge python=3.11 mintpy "numpy<2" -y

# Sentinel-1 路径（MintPy 直接装在 isce2 环境里）
conda install -n isce2 -c conda-forge mintpy -y
```

#### 第三步：安装 Claude Code 插件

```bash
# 注册本地插件
claude plugin marketplace add /home/august/insar-agent --scope project

# 安装插件
claude plugin install insar-agent-plugin@insar-agent
```

#### 第四步：验证全部安装

在 Claude Code 中输入：

```
/insar-agent
```

AI 会自动调用 `insar_check_env()` 工具，返回所有环境状态。如果一切正常，你会看到：

```
✅ isce3gpu: ok (version: ...)
✅ isce2: ok (version: ...)
✅ mintpy: ok (version: ...)
✅ MCP server: registered (plugin:insar-agent-plugin:insar-mcp-server)
✅ Skills: all installed
```

### 3.3 可选：配置外部数据源

**ASF Earthdata（下载 NISAR RSLC）：**

```bash
# 编辑 ~/.netrc，添加：
machine urs.earthdata.nasa.gov
    login <你的Earthdata用户名>
    password <你的Earthdata密码>
```

**CDS API（ERA5 气象数据，用于对流层改正）：**

```bash
# 编辑 ~/.cdsapirc：
url: https://cds.climate.copernicus.eu/api
key: <uid>:<api-key>
```

（在 https://cds.climate.copernicus.eu/how-to-api 注册获取 key）

---

## 4. 详细操作指南

### 4.1 入口：启动 InSAR-Agent

**你在 Claude Code 中输入：**

```
/insar-agent
```

**发生了什么：**

1. AI 调用 `insar_check_env()` 检查 conda 环境、MCP 服务器、技能插件是否就绪
2. AI 读取 `insar://workflow-guide` 资源，加载工作流硬约束
3. AI 根据你的需求，路由到对应的工作流技能（如 `d-insar-isce3`、`stack-insar-isce2` 等）

**交互模式说明：** 系统支持两种模式——

| 模式 | 行为 | 适用场景 |
|------|------|---------|
| **interactive**（默认） | 每步需要用户确认后才继续 | 首次使用、不确定参数时 |
| **auto** | 自动推进，最少打断 | 熟悉流程、信任 AI 判断时 |

你可以随时告诉 AI"切换到 auto 模式"或"切换到 interactive 模式"。

---

### 4.2 功能一：单对 D-InSAR（ISCE3 / NISAR 数据）⭐

> **处理目标：** 输入两景 NISAR RSLC 文件 → 输出 GUNW 干涉图产品（含相干图、解缠相位）
>
> **典型耗时：** 10–60 分钟

#### 操作步骤详解

**场景：** 你有两景 NISAR RSLC 文件（参考景和辅景），想生成一张干涉图。

**你在 Claude Code 中输入：**

```
/insar-agent

我想处理一对 NISAR RSLC 数据，参考景在 /data/rslc/ref.h5，辅景在 /data/rslc/sec.h5，输出到 /data/output，用 isce3gpu 环境。
```

**AI 的执行流程（你只需确认关键步骤）：**

```
步骤 1/8：创建项目
  AI 调用: insar_create_project(engine="isce3", workflow="insar",
           output_root="/data/output", conda_env="isce3gpu")
  → 返回 project_id: "a1b2c3d4-..."
  → 提示: 项目已创建，输出目录 /data/output/d-insar-isce3_20260705T120000Z/

步骤 2/8：设置数据路径并获取元数据
  AI 调用: insar_set_runconfig_value(project_id, key="...reference_rslc_file",
           value="/data/rslc/ref.h5")
  AI 调用: insar_set_runconfig_value(project_id, key="...secondary_rslc_file",
           value="/data/rslc/sec.h5")
  AI 调用: insar_describe_rslc(reference_rslc="/data/rslc/ref.h5",
           secondary_rslc="/data/rslc/sec.h5", project_id="...")
  → 显示: 时间基线 12 天，覆盖范围 [116.2, 39.8, 116.5, 40.1]

步骤 3/8：准备 DEM
  AI 自动发现 DEM 缺失 → 调用 insar_download_dem(bbox=[116.2,39.8,116.5,40.1])
  → DEM 下载中（后台）...
  → DEM 下载完成，路径: /data/output/prepare/dem/copernicus_30.tif

步骤 4/8：参数调优（⚠️ 强制步骤）
  AI: "正在进行参数顾问分析..."
  AI 委派 param-advisor subagent 分析:
    - RSL 元数据: L 波段, 城市区域, 时间基线 12 天
    - 硬件: 16 核 CPU, 64 GB 内存, 1×GPU
  AI 展示推荐参数:
    ┌────────────────────────────────────────────┐
    │ 参数         │ 默认  │ 推荐  │ 原因         │
    │ range_looks  │ 11    │ 5     │ 城市高相干   │
    │ azimuth_looks│ 5     │ 3     │ 保留分辨率   │
    │ filter_strength│0.5 │ 0.3   │ L 波段信噪比高│
    │ unwrap_method│snaphu│ snaphu│ 推荐默认     │
    └────────────────────────────────────────────┘
  
  ⚠️ 此时你需要选择:
    1. 使用默认参数直接运行
    2. 采用以上建议参数
    3. 自行指定参数
  
  你回复 "2" → AI 调用 insar_set_processing_param 逐项应用

步骤 5/8：启动工作流
  AI 调用: insar_run_workflow(project_id="a1b2c3d4-...")
  → 返回: job_id="j-abc123", status="running", pid=12345
  → 提示你可以在终端监控进度:
    tail -f /data/output/d-insar-isce3_20260705T120000Z/.insar_agent/progress.log

步骤 6/8：轮询等待完成
  AI 每分钟自动检查一次: insar_get_job(job_id="j-abc123", project_id="...")
  进度日志显示:
    [2026-07-05 12:05:32] HDF5 → RIFG
    [2026-07-05 12:12:18] RIFG → RUNW
    [2026-07-05 12:28:45] RUNW → GUNW
    [2026-07-05 12:28:47] GUNW product written
  → status 变为 "done"

步骤 7/8：检查输出
  AI 调用: insar_list_outputs(job_id="j-abc123", project_id="...")
  → 产品列表:
    /data/output/d-insar-isce3_20260705T120000Z/insar_product/products/GUNW_...h5

步骤 8/8：导出 GeoTIFF（可选）
  AI: "是否导出为 QGIS 可用的 GeoTIFF？"
  你回复 "是"
  AI 调用: insar_export_geotiff(h5_path=".../GUNW_...h5",
           output_dir=".../exports/")
  → 导出完成: browse/ 目录下包含振幅、相干、解缠相位等 GeoTIFF + PNG
```

**处理完成后的报告格式：**

```
✅ D-InSAR 处理完成
  - 引擎: isce3 / insar
  - 参考景: /data/rslc/ref.h5
  - 辅景:   /data/rslc/sec.h5
  - DEM:    /data/output/prepare/dem/copernicus_30.tif
  - 产品:   .../insar_product/products/GUNW_...h5
  - 状态:   done (耗时 28 分钟)
```

---

### 4.3 功能二：单对 D-InSAR（ISCE2 / Sentinel-1 数据）⭐

> **处理目标：** 输入两景 Sentinel-1 IW SLC 场景 → 输出干涉图、相干图、解缠位移图
>
> **典型耗时：** 30–120 分钟（取决于 swath 数和分辨率）

#### 操作步骤详解

**场景：** 你有 Sentinel-1 升轨数据，想对 2025 年两次过境做差分干涉。

**你在 Claude Code 中输入：**

```
/insar-agent

我想处理一对 Sentinel-1 数据，路径在 /data/s1/ 下：
- S1A_IW_SLC__1SDV_20250101_...SAFE
- S1A_IW_SLC__1SDV_20250113_...SAFE
输出到 /data/output
```

**AI 的执行流程（关键区别标注）：**

```
步骤 0/7：环境检查（ISCE2 特有）
  AI 调用: insar_check_env()
  → 读取 capable.isce2 → 发现真实环境名是 "s1_isce"（不是 "isce2"！）
  ⚠️ ISCE2 环境名不是固定的，由 insar_check_env 动态发现

步骤 1/7：场景元数据检查（ISCE2 特有）
  AI 调用: insar_describe_s1(zip_path="/data/s1/S1A_...20250101...SAFE")
  AI 调用: insar_describe_s1(zip_path="/data/s1/S1A_...20250113...SAFE")
  
  检查结果:
    ✅ 相对轨道: 两者都是 14 (一致)
    ✅ 模式: 两者都是 IW (一致)
    ✅ 极化: 两者都有 VV (一致)
    ✅ 方向: 两者都是 ASCENDING (一致)
    ⚠️ 时间基线: 12 天 (合理范围 6-48 天)
  
  全部通过 → 继续

步骤 2/7：数据准备（如果需要）
  AI 检查 DEM 和轨道文件是否存在
  → 如果缺失，进入 data-prep 流程自动准备

步骤 3/7：创建项目
  AI 调用: insar_create_project(engine="isce2", workflow="tops",
           output_root="/data/output", conda_env="s1_isce")
  → 注意 conda_env 用的是 insar_check_env 发现的真实环境名

步骤 4/7：设置必填参数
  AI 调用 insar_set_processing_param 设置:
    reference_safe  = "/data/s1/S1A_...20250101...SAFE"
    secondary_safe  = "/data/s1/S1A_...20250113...SAFE"
    orbit_dir       = "/data/output/prepare/orbits/"
    dem_file        = "/data/output/prepare/dem/isce2.dem.wgs84"
  
  可选参数（AI 会询问是否需要调整）:
    bbox              = None (全幅处理)
    swaths            = [1,2,3]
    range_looks       = 20
    azimuth_looks     = 4
    filter_strength   = 0.5
    do_esd            = True
    unwrap_method     = AI 通过 insar_probe_host() 动态发现本地可用方法

步骤 4.5/7：参数调优（⚠️ 强制，同 ISCE3 流程）
  AI 进入 param-advisor (engine=isce2)，展示推荐参数，你三选一确认

步骤 5/7：启动处理
  AI 调用: insar_run_workflow(project_id="...")
  → ISCE2 内部自动:
    1. 生成 topsApp.xml
    2. 启动 topsApp.py（可选 dostep esd）
  → 返回 job_id，你可 tail -f progress.log 监控

步骤 6/7：轮询等待
  典型 ISCE2 处理阶段:
    Running coarse_interferogram  →  5-10 分钟
    Running filt_topophase        →  10-20 分钟
    Running geocode               →  5-10 分钟

步骤 7/7：检查输出
  关键产品:
    merged/filt_topophase.unw.geo      ← 解缠干涉图（可用 QGIS 直接打开）
    merged/filt_topophase.unw.geo.vrt  ← GIS 可视化
    merged/phsig.cor.geo               ← 相干图
    merged/filt_topophase.flat.geo     ← 平地改正后的缠绕相位
```

#### ISCE2 常见故障排除

| 症状 | 原因 | 解决方法（AI 会自动尝试） |
|------|------|---------------------------|
| 轨道下载超时 (Connection timeout) | ESA Dataspace 网络不稳 | MCP 工具自动重试 3 次（指数退避）；或预下载轨道到 orbit_dir |
| ESD 失败 (低相干区) | 森林/水体/陡峭地形相干性 < 0.3 | AI 建议设 `do_esd=False`，或增加 `filter_strength=0.8` |
| SNAPHU 解缠崩溃 | 缠绕相位不连续 | AI 建议改用 `unwrap_method="icu"`（更快但欠稳健），或减少 looks |
| 内存不足 OOM | 全分辨率 3 swath 需要 40-80 GB | AI 建议：增加 looks（`azimuth_looks=8`），限制 swaths 到 `[2]`，或用 bbox 裁剪 |
| 输出目录为空 | topsApp.py 早期失败 | AI 读取 Layer-2 日志排查具体错误 |

---

### 4.4 功能三：多景 Stack/Network 批处理（ISCE3 / NISAR 数据）⭐

> **处理目标：** 输入多景 NISAR RSLC 文件 → 生成干涉图网络 → MintPy 时序分析
>
> **典型耗时：** 数小时到数天（取决于场景数和并行度）

#### 操作步骤详解

**场景：** 你有 30 景 NISAR RSLC 数据在 `/data/rslc/` 目录下，想做时序分析。

**你在 Claude Code 中输入：**

```
/insar-agent

/data/rslc/ 下有 30 景 RSLC，我想做时序分析。DEM 在 /data/dem.tif，用 isce3gpu 环境。
```

**AI 的执行流程：**

```
步骤 0/7：参数调优（Path B 必须先做！）
  AI 进入 param-advisor (engine=isce3):
    - 分析代表场景的元数据
    - subagent 生成推荐参数
    - 调优后的 YAML 保存为:
      /data/rslc/base_runconfig_param_tuned.yaml
    → 这个文件会作为所有 pair 的基础配置

步骤 1/7：准备 Stack（可选，独立于 Network）
  你选择: 只做 Network，不做 Stack
  （或者两个都做——以下以 Network 为例）

步骤 2/7：准备 Network（干涉图网络）
  AI 调用: insar_prepare_network(
    data_dir="/data/rslc/",
    base_runconfig="/data/rslc/base_runconfig_param_tuned.yaml",
    dem="/data/dem.tif",
    output_dir="/data/output/insar_product/network/",
    network_mode="tbase",              # 按时间基线连接
    max_temporal_baseline_days=36,     # 最长 36 天
    interaction_mode="interactive"
  )
  
  → 返回:
    网络模式: tbase (时间基线 ≤36 天)
    配对数量: 127 对
    pair_list: /data/output/.../pair_lists/pairs_selected.txt
    handoff_required: true
  
  ⚠️ AI 暂停，让你检查配对列表:
    "共生成 127 个干涉对，是否继续？输入 yes 继续，或 no 调整参数。"
  你回复 "yes"

步骤 3/7：执行 Network 批处理
  AI 调用: insar_run_batch(
    batch_dir="/data/output/.../network/",
    max_jobs=4,                    # 同时跑 4 个 pair
    execution_mode="parallel"
  )
  
  → 每对生成独立的 runconfig
  → 并行执行，天然支持断点续跑（已完成的 pair 自动跳过）
  
  进度显示:
    [Pair  12/127] RUN  20250315_20250327
    [Pair  13/127] RUN  20250315_20250408
    [Pair  14/127] SKIP 20250327_20250408  ← 已完成，自动跳过
    ...

步骤 4/7：轮询批处理状态
  AI 调用: insar_get_job(job_id="...", batch_dir="...")（分钟级间隔）
  → 批处理数小时，AI 会在每次醒来时报告进度

步骤 5/7：基线可视化
  批处理完成后:
  AI 调用: insar_plot_baseline(network_dir=".../network/")
  → 生成:
    baseline_network.png  ← 时空基线图
    baseline_network.pdf
    pairs.csv             ← 每对的基线统计
    scenes.csv            ← 每景的采集信息

步骤 6/7：MintPy 时序分析
  AI 进入 mintpy (engine=isce3) 流程（见 4.9 节）

步骤 7/7：结果检查
  产品位于:
    .../network/runs/20250315_20250327/products/GUNW_...h5
    .../network/runs/20250315_20250408/products/GUNW_...h5
    ...（共 127 个 GUNW 产品）
```

#### 断点续跑说明

ISCE3 批处理的断点续跑是**天然支持**的——`run_parallel.sh` 对每个 pair 先检查其 `sas_output_file` 是否存在，已完成的自动跳过：

```
如果处理到一半中断（如机器重启），直接重跑同一个命令：
  AI 调用: insar_run_batch(batch_dir=".../network/", max_jobs=4)
  → 已完成: SKIP（秒级跳过）
  → 未完成: RUN（只补跑这部分）
```

---

### 4.5 功能四：多景 Stack 时序处理（ISCE2 / Sentinel-1 数据）⭐

> **处理目标：** 输入多景 Sentinel-1 SLC（同轨道）→ stackSentinel → MintPy 形变时间序列 + 速度场
>
> **典型耗时：** 数小时到数天（取决于场景数）

#### 操作步骤详解

**场景：** 你有 50 景 Sentinel-1 升轨场景，想做形变时序分析。

**重要原则：先创建项目，再做数据准备！** `insar_create_project` 必须第一步执行以固定 `run_id`。

**你在 Claude Code 中输入：**

```
/insar-agent

我有 50 景 Sentinel-1 ascending 数据在 /data/s1_raw/，输出到 /data/output。

[附：或者你只给 SAFE 目录路径，AI 会自动发现和组织]
```

**AI 的执行流程：**

```
步骤 0/7：环境检查
  AI 调用: insar_check_env()
  → 发现 ISCE2 环境名: "s1_isce"

步骤 1/7：创建项目（⚠️ 必须第一步！）
  AI 调用: insar_create_project(
    engine="isce2",
    workflow="stack",
    output_root="/data/output",
    conda_env="s1_isce"
  )
  → project_id: "x1y2z3-..."
  → run_id 已固定，后续所有步骤共享此 run

步骤 2/7：数据准备
  AI 进入 data-prep (engine=sentinel)，传入 project_id
  自动完成:
    ✅ 整理 SAFE 分组      → /data/output/prepare/safe/s1a_asc_rel014/
    ✅ 下载 DEM            → /data/output/prepare/dem/isce2.dem.wgs84
    ✅ 下载精密轨道        → /data/output/prepare/orbits/
  
  多景数据准备自动后台运行 → AI 分钟级轮询直到完成

步骤 3/7：场景元数据检查
  AI 调用: insar_describe_s1 检查 2-3 个代表场景
  → 确认 50 景都是 rel_orbit=14, ASCENDING, IW, VV+VH ✓

步骤 4/7：设置 Stack 参数
  AI 调用 insar_set_processing_param 设置:
    slc_dir      = "/data/output/prepare/safe/s1a_asc_rel014/"
    orbit_dir    = "/data/output/prepare/orbits/"
    dem_file     = "/data/output/prepare/dem/isce2.dem.wgs84"
    num_connections = 3
    coregistration  = "NESD"
    range_looks     = 9
    azimuth_looks   = 3

步骤 4.5/7：参数调优（⚠️ 强制）
  param-advisor (engine=isce2) 分析:
    - 50 景, 时间跨度 2 年, 城市区域
    - 硬件: 32 核, 128 GB 内存
    - 推荐: num_connections=3, 并行度适中
  AI 展示推荐 → 你确认 → AI 逐项应用

步骤 5/7：启动 stackSentinel
  AI 调用: insar_run_workflow(project_id="x1y2z3-...")
  
  stackSentinel 内部有 16 个 run step:
    run_01: 创建目录结构
    run_02: 解压 SLC
    run_03: 计算基线
    ...
    run_16: 解缠
  
  → 返回 job_id，后台运行（数小时到数天）

步骤 5+/7：断点续跑（如果中途失败）
  场景: run_12 时因网络中断导致轨道下载失败
  AI 检查日志发现最后一步是 run_11 ✓
  AI 调用: insar_run_workflow(project_id="x1y2z3-...",
           resume_from_run=12)
  → 跳过 run_01~11，从 run_12 继续
  → 复用已有 run_files 和产物

步骤 6/7：ERA5 对流层改正（可选）
  AI 询问: "是否启用 ERA5 对流层改正？"
  你选择 "是" → AI 进入 ERA5 流程（见 4.10 节）

步骤 7/7：MintPy 时序分析
  AI 进入 mintpy (engine=isce2) 流程（见 4.9 节）
  → 最终产出 velocity.h5, timeseries.h5 等

步骤 8/7：结果导出
  AI 调用: insar_export_geotiff(h5_path=".../velocity.h5", ...)
  → QGIS 可用的 GeoTIFF 速度图
```

#### stackSentinel 断点续跑机制

```
正常执行:
  run_01 → run_02 → ... → run_16 → 完成
                            ↑ 此处失败

续跑（resume_from_run=12）:
  [跳过 run_01~11] → run_12 → run_13 → ... → run_16
                       ↑ 复用已有产物，从断点继续

调参后续跑:
  先 insar_set_processing_param 改参数
  再 resume_from_run=N → 新参数从第 N 步生效
```

---

### 4.6 功能五：数据准备（NISAR RSLC）🔧

> **功能说明：** 从 ASF 按 AOI/bbox 裁剪下载 NISAR RSLC 文件

**你在 Claude Code 中输入：**

```
/insar-agent

我需要下载 NISAR RSLC 数据。URL 列表在 /data/urls.txt，AOI 范围是 [116.0, 39.5, 117.0, 40.5]，下载到 /data/rslc/。我的 Earthdata 账号在 ~/.netrc 里。
```

**AI 执行流程：**

1. 检查 `~/.netrc` 是否配置 → 确认 `urs.earthdata.nasa.gov` 凭证存在
2. 检查服务器资源：`nproc`、`free -h`、`df -h` → 推荐 `n_workers=8`
3. 调用 `insar_download_rslc(urls=[...], output_dir="/data/rslc/", bbox=[116.0,39.5,117.0,40.5], freq="A", n_workers=8)`
4. 下载自动后台化 → 返回 `job_id`
5. AI 分钟级轮询 `insar_get_job` 直到完成
6. 确认文件存在于磁盘

---

### 4.7 功能六：数据准备（Sentinel-1 SAFE + DEM + 轨道）🔧

> **功能说明：** 整理 Sentinel-1 原始数据为 ISCE2 可用的目录结构，一并准备 DEM 和轨道

**你在 Claude Code 中输入：**

```
/insar-agent

帮我准备 Sentinel-1 数据。SAFE 文件在 /data/s1_raw/ 下有 50 个 ZIP，AOI 是 /data/study_area.shp，输出到 /data/output。
```

**AI 执行流程：**

1. **场景搜索**（如果没有 URL）：调用 `insar_search(platform="sentinel1", aoi_path=..., start=..., end=...)` 发现可用场景
2. **场景下载**（如果需要）：调用 `insar_download_scene(urls=[...], output_dir=..., n_workers=2)`
3. **数据整理**：调用 `insar_prepare_sentinel_data(project_root="/data/output", source_paths=[...], download_dem=True, download_orbits=True, background=True)`
4. **场景检查**：调用 `insar_describe_s1` 检查代表场景
5. 整理后的目录结构：

```
/data/output/prepare/
  safe/s1a_asc_rel014/    ← 50 个 SAFE 都在这
  dem/isce2.dem.wgs84     ← DEM + .xml/.vrt 边车文件
  orbits/                 ← 精密轨道 .EOF 文件
```

---

### 4.8 功能七：DEM 下载 🔧

> **功能说明：** 单独下载 Copernicus 30m DEM（不依赖其他流程）

**你在 Claude Code 中输入：**

```
/insar-agent

帮我下载研究区的 DEM。范围 [116.0, 39.5, 117.0, 40.5]，存到 /data/dem/cop30.tif。
```

**AI 执行：**

```python
insar_download_dem(
    output_path="/data/dem/cop30.tif",
    bbox=[116.0, 39.5, 117.0, 40.5],
    source="copernicus_30"
)
```

如果系统代理导致下载失败：

```python
# AI 会自动重试：绕过代理直连
insar_download_dem(
    output_path="/data/dem/cop30.tif",
    bbox=[116.0, 39.5, 117.0, 40.5],
    source="srtm_c",    # 换备用源
    proxy=""            # 直连，不继承系统代理
)
```

---

### 4.9 功能八：MintPy 时序分析 🔧

> **功能说明：** 对已完成的干涉图网络运行 MintPy 小基线集时序分析

**支持两种引擎的 MintPy 分析：**

#### 4.9.1 ISCE3 MintPy（NISAR GUNW 网络）

**你在 Claude Code 中输入：**

```
/insar-agent

network 批处理已完成，在 /data/output/stack-insar-isce3_.../insar_product/network/，帮我运行 MintPy。DEM 在 /data/dem.tif，用独立的 mintpy 环境。
```

**AI 执行流程：**

```
步骤 1：基线网络可视化（ISCE3 必做）
  AI 调用: insar_plot_baseline(network_dir="...")
  → 生成基线图，展示给用户确认:
    - 时间基线范围: 12-36 天
    - 垂直基线范围: 50-200m
    - 共 127 对
  ⚠️ interactive 模式暂停让用户检查；auto 模式自动继续

步骤 2：启动 MintPy
  AI 调用: insar_run_mintpy(
    mintpy_work_dir="/data/output/.../insar_product/mintpy/",
    gunw_glob="/data/output/.../network/runs/*/products/*.h5",
    mintpy_config="",                # 留空 = 自动生成 NISAR 默认配置
    dem_path="/data/dem.tif",
    conda_env="mintpy"              # ⚠️ 专用 MintPy 环境（numpy<2）
  )
  → 返回 job_id，后台运行

步骤 3：轮询
  AI 调用: insar_get_job(job_id=..., work_dir=".../mintpy/")
  MintPy 进度:
    smallbaselineApp.py --dostep load_data
    smallbaselineApp.py --dostep modify_network
    ...
    smallbaselineApp.py --dostep velocity

步骤 4：检查产出
  mintpy/velocity.h5        ← LOS 速度 (m/yr)
  mintpy/timeseries.h5      ← 位移时间序列
  mintpy/temporalCoherence.h5 ← 时间相干性
  mintpy/geometryGeo.h5     ← 几何参数
```

#### 4.9.2 ISCE2 MintPy（Sentinel-1 topsStack）

**你在 Claude Code 中输入：**

```
/insar-agent

stackSentinel 已完成在 /data/output/.../insar_product/stack/，帮我跑 MintPy。
```

**AI 执行流程：**

```
步骤 1：启动 MintPy
  AI 调用: insar_run_mintpy_isce2(
    mintpy_work_dir="/data/output/.../insar_product/mintpy/",
    stack_work_dir="/data/output/.../insar_product/stack/",
    conda_env="s1_isce"             # ⚠️ ISCE2 MintPy 复用 isce2 环境
  )
  
  ISCE2 MintPy 内部:
    1. prep_isce.py → 准备元数据
    2. smallbaselineApp.py --end velocity（默认到 velocity 步骤）

步骤 2：轮询
  AI 调用: insar_get_job(job_id=..., work_dir=".../mintpy/")

步骤 3：检查产出
  同 ISCE3 MintPy
```

---

### 4.10 功能九：ERA5 对流层改正（ISCE2）🔧

> **功能说明：** 使用 ERA5 气象再分析数据对 ISCE2 时序结果进行大气延迟改正

**前提：** 已配置 `~/.cdsapirc`（CDS API 凭证）

**你在 Claude Code 中输入：**

```
/insar-agent

我想给这个 stack 结果加 ERA5 对流层改正。stack 在 output/.../insar_product/stack/。
```

**AI 执行流程：**

```
步骤 1：预览下载计划（dry run）
  AI 调用: insar_download_era5(
    project_id="...",
    dates=["20250101", "20250113", "20250125", ...],  # 50 个 YYYYMMDD
    bbox=[116.0, 39.5, 117.0, 40.5],
    hour="10",                        # Sentinel-1 过境 UTC 时间 ±1h
    dry_run=True
  )
  → 展示: 共 50 个日期，预期下载 N 个 GRIB 文件到
    /data/output/prepare/weather/ERA5/
  
  ⚠️ 等待用户确认

步骤 2：实际下载
  你回复 "确认"
  AI 调用: insar_download_era5(dry_run=False, ...)
  → 后台下载

步骤 3：以 ERA5 模式运行 MintPy
  AI 调用: insar_run_mintpy_isce2(
    mintpy_work_dir=".../mintpy/",
    stack_work_dir=".../stack/",
    conda_env="s1_isce",
    weather_dir="/data/output/prepare/weather/",
    weather_model="ERA5"
  )
  → MintPy 自动读取 GRIB，应用 pyAPS ERA5 改正

步骤 4：结果对比
  产出:
    velocity.h5          ← 未改正的 LOS 速度
    velocity_ERA5.h5     ← ERA5 改正后的 LOS 速度
    timeseries_ERA5.h5   ← ERA5 改正后的时间序列
  
  AI 调用: insar_export_geotiff(h5_path=".../mintpy/")
  → 自动生成改正前后 + 残差的对比图
```

**如果 `~/.cdsapirc` 缺失，AI 会提示：**

```
错误: missing_credentials
请访问 https://cds.climate.copernicus.eu/how-to-api 注册，同意 ERA5 许可协议，
获取 API key 后写入 ~/.cdsapirc
```

---

### 4.11 功能十：结果导出与可视化 🔧

> **功能说明：** 将 HDF5/二进制产物导出为 QGIS/GIS 软件可用的 GeoTIFF

#### 4.11.1 GeoTIFF 导出

**你在 Claude Code 中输入：**

```
/insar-agent

把 GUNW 产品导出为 GeoTIFF: /data/output/.../products/GUNW_...h5
```

**AI 执行：**

```python
insar_export_geotiff(
    h5_path="/data/output/.../products/GUNW_...h5",
    output_dir="/data/output/.../insar_product/exports/"
)
```

**导出的内容（按格式自动分派）：**

| 输入类型 | 导出内容 |
|----------|----------|
| NISAR GUNW `.h5` | 逐数据集 GeoTIFF + 彩色 PNG (`browse/` 子目录) |
| MintPy `.h5` 或目录 | velocity, temporalCoherence, avgSpatialCoh, maskTempCoh, velocity_masked |
| ISCE2 `.geo` / `.geo.vrt` | 已地理编码图层直接转出（`.unw` 取 band 2 相位） |
| ISCE2 MintPy（雷达坐标） | 先 ISCE2 geocode.py 地理编码再导出 |
| 不支持的格式（如 GAMMA） | 记入 `notes`，不中断其他文件 |

#### 4.11.2 基线网络可视化

**你在 Claude Code 中输入：**

```
/insar-agent

帮我画这个 network 的时空基线图: /data/output/.../insar_product/network/
```

**AI 执行：**

```python
insar_plot_baseline(
    network_dir="/data/output/.../insar_product/network/",
    title="时空基线网络",
    interaction_mode="interactive"
)
```

**产出：** PNG 图、PDF 图、pair CSV（每对基线统计）、scene CSV（每景信息）

#### 4.11.3 RUNW 恢复地理编码

当 GUNW 产品的 geocode 步骤退化时，可以通过 radar-geometry 的 RUNW + rdr2geo 栅格恢复地理编码的 GeoTIFF：

```python
insar_geocode_runw(runw_path="...", rdr2geo_path="...", output_dir="...")
```

---

### 4.12 功能十一：场景搜索与编目发现 🔧

> **功能说明：** 按 AOI 和时间窗口搜索可用的 Sentinel-1 场景

**你在 Claude Code 中输入：**

```
/insar-agent

帮我查一下研究区 [116.0, 39.5, 117.0, 40.5] 在 2025 年 10 月到 2026 年 1 月之间有哪些升轨 Sentinel-1 场景，轨道号 14。
```

**AI 执行：**

```python
insar_search(
    platform="sentinel1",
    bbox=[116.0, 39.5, 117.0, 40.5],
    start="2025-10-01",
    end="2026-01-06",
    flight_direction="ASCENDING",
    relative_orbit=14,
    polarizations=["VV", "VH"]
)
```

**返回：** 场景列表、按相对轨道分组、可用下载 URL、缺失场景等信息。

---

### 4.13 功能十二：环境检查与安装 🔧

> **功能说明：** 检查或安装 insar-agent 所需的 conda 环境和插件

**你在 Claude Code 中输入：**

```
/insar-agent  医生模式
# 或
/insar-agent  帮我检查环境
```

**AI 执行：**

```python
insar_check_env()
```

**返回：**

```json
{
  "discovered_envs": {
    "isce3gpu": {"isce3": "0.16", "mintpy": null, "isce2": null},
    "s1_isce": {"isce2": "2.6.1", "mintpy": "1.6.1", "isce3": null}
  },
  "capable": {
    "isce3": ["isce3gpu"],
    "isce2": ["s1_isce"],
    "mintpy": ["s1_isce"]
  },
  "mcp": {"registered": true},
  "skills": {"installed": ["insar-agent", "d-insar-isce3", ...], "missing": []},
  "install_hints": {}
}
```

**如果环境缺失，AI 会给出安装建议：**

```
❌ ISCE3 环境未找到。需要安装吗？
  conda create -n isce3gpu -c conda-forge python=3.11 isce3-cuda snaphu ...
```

**如果首次安装，输入：**

```
/insar-agent  帮我设置环境
# 或
/env-setup
```

AI 会引导你完成：
1. 询问处理 NISAR 还是 Sentinel-1 数据
2. 给出对应的 conda 安装命令
3. 引导安装 insar-agent 包和 Claude Code 插件
4. 安装完成后执行 `insar_check_env()` 验证

---

### 4.14 功能十三：YODO 复盘与经验沉淀 🔧

> **功能说明：** 在 InSAR 处理任务完成后，将本次协作中获得的有用经验自动分析、分类，并生成插件资产开发建议。

**你在 Claude Code 中输入：**

```
/yodo
# 或
帮我复盘这次处理
```

**AI 执行流程：**

1. **证据收集**：整理当前会话的用户目标、工作流路径、决策记录、失败和恢复记录、最终结果
2. **分类**：判定为以下三类之一——
   - `existing_engine_extension`：属于已有引擎的扩展优化
   - `new_engine_onboarding`：涉及新引擎（如 GAMMA/GMTSAR）接入需求
   - `common_plugin_capability`：跨引擎通用能力改进
3. **资产映射**：将可复用的教训映射为具体插件资产类型（skills / MCP tool / param-advisor / hook / template）
4. **输出结构化复盘报告**

**报告结构：**

```markdown
## YODO 复盘包

### 1. 结论
- Classification: existing_engine_extension
- Confidence: high
- 某参数在特定场景下应设置不同默认值

### 2. 证据摘要
- 用户目标: 城市区域 Sentinel-1 D-InSAR
- 使用的决策: filter_strength 从 0.5 降到 0.3（城市高相干）
- 失败与恢复: ESD 在低相干区域失败 → 设为 False 解决

### 3. 可沉淀过程知识
- 城市区域 S1 C 波段宜用较低 filter_strength (0.2-0.4)
- 森林/水体覆盖 >30% 时优先关闭 ESD
- ...

### 4. 推荐插件资产
- param-advisor 规则: 城市区域 filter_strength 建议调低
- Skill 指令: d-insar-isce2 故障排除补充 ESD 处理流程

### 5. 开发交接
- 推荐开发 skill: plugin-dev:skill-development
- 涉及文件: skills/d-insar-isce2/SKILL.md
```

---

## 5. 附录：完整 MCP 工具速查表

### 按功能分组（共 28 个工具）

#### G1：发现（2 个）

| 工具 | 功能 | 关键参数 |
|------|------|----------|
| `insar_discover` | 列出可用引擎/工作流 | `engine`（可选） |
| `insar_get_project` | 查询项目元数据和作业状态 | `project_id` |

#### G2：配置管理（6 个）

| 工具 | 功能 | 关键参数 |
|------|------|----------|
| `insar_create_project` | 创建新项目（返回 project_id） | `engine`, `workflow`, `output_root`, `conda_env` |
| `insar_get_runconfig` | 读取当前 runconfig | `project_id`, `format`（json/yaml） |
| `insar_set_runconfig_value` | 设置路径类字段 | `project_id`, `key`, `value` |
| `insar_set_processing_param` | 设置白名单处理参数 | `project_id`, `key`, `value`, `justification` |
| `insar_record_param_advice` | 持久化参数建议 | `project_id`, `recommendation_package` |
| `insar_export_runconfig` | 导出 runconfig YAML | `project_id`, `output_dir` |

#### G3：执行（3 个）

| 工具 | 功能 | 关键参数 |
|------|------|----------|
| `insar_run_workflow` | 校验+导出+启动工作流 | `project_id`, `dry_run` |
| `insar_get_job` | 查询任意类型作业状态 | `job_id`, `project_id`/`work_dir`/`batch_dir` |
| `insar_list_outputs` | 列出作业输出文件 | `job_id`, `project_id` |

#### G4：Stack/Network（4 个）

| 工具 | 功能 | 关键参数 |
|------|------|----------|
| `insar_prepare_stack` | 准备单参考景 RSLC stack | `data_dir`, `base_runconfig`, `dem`, `output_dir` |
| `insar_prepare_network` | 生成干涉图网络 | `data_dir`, `network_mode`, `max_temporal_baseline_days` |
| `insar_run_batch` | 执行批处理 | `batch_dir`, `max_jobs`, `execution_mode` |
| `insar_plot_baseline` | 绘制基线网络图 | `network_dir`, `title` |

#### G5：元数据与下载（4 个）

| 工具 | 功能 | 关键参数 |
|------|------|----------|
| `insar_describe_rslc` | RSLC 元数据摘要 | `reference_rslc`, `secondary_rslc` |
| `insar_download_rslc` | 按 AOI 裁剪下载 RSLC | `urls`, `output_dir`, `bbox`/`aoi_path` |
| `insar_download_dem` | 下载 DEM | `output_path`, `bbox`/`aoi_path` |
| `insar_search` | 场景编目搜索 | `platform`, `aoi_path`/`bbox`, `start`, `end` |

#### G6：MintPy（2 个）

| 工具 | 功能 | 关键参数 |
|------|------|----------|
| `insar_run_mintpy` | ISCE3 MintPy 时序 | `mintpy_work_dir`, `gunw_glob`, `dem_path`, `conda_env` |
| `insar_run_mintpy_isce2` | ISCE2 MintPy 时序 | `mintpy_work_dir`, `stack_work_dir`, `conda_env` |

#### G7：Sentinel-1 / ISCE2（4 个）

| 工具 | 功能 | 关键参数 |
|------|------|----------|
| `insar_download_scene` | 下载 Sentinel-1 场景 | `urls`, `output_dir` |
| `insar_describe_s1` | SAFE/ZIP 元数据 | `zip_path` |
| `insar_prepare_sentinel_data` | 整理 ISCE2 输入 | `project_root`, `source_paths` |
| `insar_download_era5` | 下载 ERA5 气象数据 | `project_id`, `dates`, `bbox`, `hour` |

#### G8：分析与导出（2 个）

| 工具 | 功能 | 关键参数 |
|------|------|----------|
| `insar_export_geotiff` | 栅格→GeoTIFF 导出 | `h5_path`, `output_dir`, `tag` |
| `insar_geocode_runw` | RUNW 恢复地理编码 | `runw_path`, `rdr2geo_path` |

#### G9：环境（2 个）

| 工具 | 功能 | 关键参数 |
|------|------|----------|
| `insar_check_env` | 环境全面检查 | 无 |
| `insar_probe_host` | 主机资源探查 | 无 |

### 常用错误码

| 错误码 | 含义 | 典型原因 |
|--------|------|----------|
| `project_not_found` | project_id 无效 | 项目未创建或 ID 写错 |
| `job_not_found` | job_id 无效 | Job 未启动 |
| `key_not_allowed` | 字段不在白名单中 | 试图用 `set_runconfig_value` 改处理参数（应用 `set_processing_param`） |
| `runconfig_invalid` | 必填路径字段缺失 | RSLC/DEM 路径未设置 |
| `path_not_found` | 文件路径不存在 | 输入数据路径写错或文件已移动 |
| `justification_required` | 理由为空或模糊 | `justification` 不能是空字符串或 "better performance" |
| `launch_failed` | 子进程启动失败 | conda 环境不存在或命令不可执行 |
| `dependency_missing` | 缺少所需库 | GDAL/h5py/matplotlib 未安装 |

### 技能速查表（12 个）

| 技能名 | 触发方式 | 功能 |
|--------|----------|------|
| `insar-agent` | `/insar-agent` | 主入口路由 |
| `d-insar-isce3` | 通过主路由 | Path A：NISAR 单对 D-InSAR |
| `d-insar-isce2` | 通过主路由 | Path A：Sentinel-1 单对 D-InSAR |
| `stack-insar-isce3` | 通过主路由 | Path B：NISAR Stack/Network 批处理 |
| `stack-insar-isce2` | 通过主路由 | Path B：Sentinel-1 Stack 时序 |
| `param-advisor` | 由工作流 skill 触发 | 参数调优（双引擎） |
| `data-prep` | 通过主路由 | 数据准备统一入口 |
| `data-prep-nisar` | 通过 data-prep 路由 | NISAR RSLC + DEM |
| `data-prep-sentinel` | 通过 data-prep 路由 | Sentinel SAFE + DEM + 轨道 |
| `mintpy` | 通过主路由 | MintPy 时序分析 |
| `env-setup` | `/env-setup` | 环境安装与检查 |
| `yodo` | `/yodo` | 经验沉淀与资产化建议 |

### 命令行工具

```bash
insar-agent describe              # JSON 摘要：工具/资源/Prompts/环境
insar-agent doctor                # 运行时环境检查
insar-mcp-server --describe       # 打印所有工具签名
insar-mcp-server --stdio          # 启动 MCP stdio 服务器（供 agent 客户端连接）
pytest                            # 运行单元测试（不含 real_data）
pytest -m real_data tests/integration  # 运行真实数据集成测试（需手动选择）
```

---

> 📖 **相关文档索引（均位于项目 `docs/` 目录下）：**
> - `architecture.md` — 系统架构、数据模型、工作区布局、参数白名单机制
> - `developer-documents/MCP-tools.md` — 28 个工具完整的 API 参考（参数、返回值、错误码）
> - `developer-documents/MCP-architechture.md` — MCP 层设计、引擎调用流程、Job 状态机
> - `engine-onboarding.md` — 如何接入新引擎（GAMMA/GMTSAR 等）
> - `developer-documents/dev-plan.md` — 开发计划与进度
