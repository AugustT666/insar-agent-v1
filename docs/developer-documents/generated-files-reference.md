# 生成文件参考手册

本文档描述使用 insar-agent 进行数据处理时产生的所有文件，按层次和路径组织。

涵盖两条处理路径：
- **Path A**：D-InSAR 单对处理（`d-insar-isce3` 技能，`insar_create_project` + `insar_run_workflow`）
- **Path B**：Stack-InSAR 批量处理（`stack-insar-isce3` 技能，`insar_prepare_stack` + `insar_prepare_network` + `insar_run_batch`）

---

## 文件层次总览

```
┌─────────────────────────────────────────────────┐
│  AI 层（Claude Code 插件）                        │
│  技能指令、hooks、subagent 合约                    │
│  /home/august/insar-agent/                        │
└─────────────────────────────────────────────────┘
         ↓ 调用 MCP 工具
┌─────────────────────────────────────────────────┐
│  MCP 层（insar-agent server）                    │
│  项目注册表、project.json、job.json、             │
│  runconfig.yaml、执行脚本、日志                   │
└─────────────────────────────────────────────────┘
         ↓ 启动 ISCE3 处理
┌─────────────────────────────────────────────────┐
│  ISCE3 层（ISCE3 引擎输出）                       │
│  GUNW 产品（.h5）、中间过程文件（scratch/）        │
└─────────────────────────────────────────────────┘
```

---

## 一、AI 层文件（插件自身，不随处理变动）

这些文件位于 insar-agent 插件目录下，是 Claude 行为的指令来源，不会因用户数据而产生新文件，但参数调优时会向数据目录写入一个例外文件（见第三节）。

```
/home/august/insar-agent/
  skills/
    d-insar-isce3/SKILL.md          ← Path A 技能指令：单对工作流步骤、交互/自动模式、param-advisor 调用链
    stack-insar-isce3/SKILL.md      ← Path B 技能指令：批量工作流步骤、Step 0 参数调优、handoff 处理
    d-insar-isce2/SKILL.md          ← Sentinel-1 / ISCE2 单对 TOPS D-InSAR 工作流
    stack-insar-isce2/SKILL.md      ← Sentinel-1 / ISCE2 stackSentinel 工作流
    mintpy/SKILL.md                 ← ISCE3 / ISCE2 MintPy 时序分析入口
    param-advisor/SKILL.md    ← 参数调优统一入口：AUTO-TRIGGER、三选一确认、落盘规则
    data-prep/SKILL.md              ← 数据准备路由：NISAR / Sentinel
    data-prep-nisar/SKILL.md        ← NISAR RSLC 下载和 DEM 准备
    data-prep-sentinel/SKILL.md     ← Sentinel SAFE/ZIP、orbit、DEM 准备
    env-setup/SKILL.md              ← ISCE3 / ISCE2 / MintPy + MCP 安装指南
    insar-agent/SKILL.md            ← 会话路由入口

  .claude/
    settings.json                   ← PreToolUse hooks（在 insar_run_workflow /
                                      insar_prepare_stack / insar_prepare_network
                                      调用前注入 PARAM_ADVISOR_PROMPT，触发参数调优询问）
    agents/
      param-advisor.md        ← 参数专家 subagent 合约（不与用户对话，只输出
                                      结构化 recommendation package）
      behavior-tester.md            ← 行为测试 agent（模拟首次用户观察工作流合规性）
      references/
        param-advisor.md      ← 参数经验规则知识库（multilook/filter/unwrap 等
                                      启发式规则，subagent 读取后生成建议）
```

---

## 二、MCP 层文件

### 2.1 全局项目注册表（Path A 专有）

Path A 使用项目注册表将 `project_id` 映射到 `workspace_root`，Path B 不使用注册表。

| 文件 | 路径 | 写入时机 |
|------|------|----------|
| `registry.json` | `~/.local/share/insar_agent/registry.json` | `insar_create_project` 创建项目时写入；每次 `project.save()` 时更新 |

内容示例：
```json
{
  "projects": {
    "8182598e-23ee-4651-8699-7388cf8dead4": "/path/to/workspace"
  }
}
```

---

### 2.2 Path A 工作区文件结构

`insar_create_project(workspace_root=<path>)` 后，所有 MCP 管理文件写入 `<workspace_root>/`：

```
<workspace_root>/
  .insar_agent/
    project.json            ← 项目元数据 + 完整 runconfig（实时更新）
    jobs/
      <uuid>.json           ← 每次 insar_run_workflow 产生一个 Job 元数据文件
  configs/
    runconfig.yaml          ← 导出的 ISCE3 runconfig（由 insar_export_runconfig 或
                              insar_run_workflow 在执行前自动写入）
  logs/
    <uuid>.log              ← ISCE3 执行日志（实时写入，可 tail -f 监控）
    <uuid>.exitcode         ← 进程退出码（0=成功）
  outputs/                  ← 保留目录，当前未使用
  param_tuned/              ← 参数调优后落盘（可选，由 insar_export_runconfig 创建）
    runconfig.yaml          ← 调优后的完整 runconfig 快照
```

**`project.json` 字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `project_id` | string (UUID) | 唯一项目标识符 |
| `name` | string | 项目名称（默认 `isce3-insar-workspace`） |
| `engine` | string | 处理引擎（当前固定为 `isce3`） |
| `workflow` | string | 工作流类型（当前固定为 `insar`） |
| `workspace_root` | string | 工作区根目录绝对路径 |
| `conda_env` | string\|null | ISCE3 conda 环境名称 |
| `runconfig` | dict | 当前运行配置（含所有 `insar_set_runconfig_value` 修改） |
| `runconfig_template` | dict | 原始模板（只读参考） |
| `runconfig_exported_path` | string\|null | 最近一次 export 的路径 |
| `created_at` | string (ISO8601) | 项目创建时间 |
| `updated_at` | string (ISO8601) | 最近修改时间 |

**`jobs/<uuid>.json` 字段说明（Path A）：**

| 字段 | 说明 |
|------|------|
| `job_id` | Job UUID |
| `project_id` | 所属项目 ID |
| `status` | `pending` / `running` / `done` / `failed` |
| `submitted_at` / `started_at` / `finished_at` | 各阶段时间戳 |
| `pid` | ISCE3 进程 ID |
| `exit_code` | 退出码（0=成功，非0=失败） |
| `log_path` | 执行日志文件路径 |
| `command` | 实际执行的命令列表 |

---

### 2.3 Path B 工作区文件结构

Path B 分两步，每步产生一个独立的输出目录，结构相似但内容不同。

#### Step 1：`insar_prepare_stack` → `<stack_output_dir>/`

```
<stack_output_dir>/
  .insar_agent/
    jobs/
      <uuid>.json           ← insar_run_batch 提交后写入的 Job 元数据
  logs/
    <uuid>.log              ← run_batch 执行日志
    manual_run.log          ← 手动执行时产生的日志
  runconfigs/
    20251029_20251110.yaml  ← 每一对干涉对各一个 runconfig（共 N 个）
    20251029_20251122.yaml
    ...
  runs/
    20251029_20251110/      ← 每对的运行目录（由 ISCE3 填充）
      products/             ← GUNW 产品（见 ISCE3 层）
      scratch/              ← 中间文件（见 ISCE3 层）
      logs/                 ← ISCE3 单对运行日志
      qa/                   ← QA 报告（若启用）
    ...
  run_all.sh                ← 串行执行脚本（所有对依次运行）
  run_parallel.sh           ← 并行执行脚本（接受 batch_dir 和 N 参数）
  stack_manifest.csv        ← 对目录（reference_date, secondary_date, RSLC 路径, runconfig 路径, run_dir）
  reference_date.txt        ← 选定的参考景日期（YYYYMMDD）
  mplconfig/                ← matplotlib 临时配置目录（MCP 内部使用）
```

**`stack_manifest.csv` 列说明：**

| 列 | 内容 |
|----|------|
| `reference_date` | 参考景日期 YYYYMMDD |
| `secondary_date` | 辅助景日期 YYYYMMDD |
| `reference_rslc` | 参考景 RSLC 文件绝对路径 |
| `secondary_rslc` | 辅助景 RSLC 文件绝对路径 |
| `runconfig` | 该对 runconfig YAML 绝对路径 |
| `run_dir` | 该对运行目录绝对路径 |

**配对策略（Step 1 固定参考）：**  
`insar_prepare_stack` 使用单一参考景（默认最早景），所有其余景各与参考景配对，生成 N-1 对，每对共享同一参考景。

**`jobs/<uuid>.json` 字段说明（Path B，与 Path A 相比多了批量字段）：**

| 字段 | 说明 |
|------|------|
| `batch_dir` | 批量目录路径 |
| `batch_type` | `stack` 或 `network` |
| `num_pairs` | 总对数 |
| `run_parallel_sh` | 执行脚本路径 |
| `max_jobs` | 最大并行数 |
| 其余字段 | 同 Path A Job |

---

#### Step 2：`insar_prepare_network` → `<network_output_dir>/`

结构与 Step 1 相同，但以下不同：

```
<network_output_dir>/
  runconfigs/               ← 按网络策略生成的对（非固定参考）
  runs/                     ← 网络对运行目录
  pair_lists/               ← Step 2 专有，Step 1 没有
    pairs_tbase36d.txt      ← tbase 策略下所有 Δt ≤ 36 天的候选对（每行 YYYYMMDD_YYYYMMDD）
    pairs_selected.txt      ← 最终进入 runconfigs 的对列表
    pairs_selected.csv      ← 含 reference_rslc / secondary_rslc 路径的完整清单
    pair_baselines.csv      ← 每对的时间基线(天)、垂直基线(米)、GUNW 产品路径
    baseline_network.svg    ← 时间-基线网络可视化图（可在浏览器查看）
  stack_manifest.csv        ← 与 Step 1 同名，但内容是网络对的配置清单
  run_all.sh
  run_parallel.sh
```

**`pair_baselines.csv` 列说明：**

| 列 | 内容 |
|----|------|
| `date1` / `date2` | 干涉对两景日期 |
| `date12` | 对标识符（`date1_date2`） |
| `temporal_baseline_days` | 时间基线（天） |
| `mean_perpendicular_baseline_m` | 平均垂直基线（米） |
| `product` | GUNW 产品文件绝对路径 |

**配对策略（Step 2 网络）：**  
`insar_prepare_network` 支持三种模式，通过 `network_mode` 参数选择：

| 模式 | 参数 | 说明 |
|------|------|------|
| `tbase` | `max_temporal_baseline_days=36` | 时间基线 ≤ 阈值的所有对 |
| `conn` | `connection_span=3` | 每景向后连接 N 个邻近景 |
| 自定义 | `pair_list=<文件路径>` | 文件中每行一个 `YYYYMMDD_YYYYMMDD` |

---

### 2.4 参数调优落盘文件

参数调优（`param-advisor`）完成后会在特定路径写入快照文件，用于后续会话跳过重复调优。

| 路径 | 适用路径 | 创建方式 | 作用 |
|------|----------|----------|------|
| `<workspace_root>/param_tuned/runconfig.yaml` | Path A | `insar_export_runconfig(project_id, output_dir="<workspace_root>/param_tuned")` | 快照；`insar_run_workflow(dry_run=True)` 返回 `param_tuned_found: true` |
| `<data_dir>/base_runconfig_param_tuned.yaml` | Path B | param-advisor subagent 将调优 YAML 直接写入此路径 | 快照；`insar_prepare_stack`/`insar_prepare_network` 返回 `param_tuned_found: true` |

---

## 三、ISCE3 层文件

每个干涉对在 `runs/<date1>_<date2>/` 下产生以下文件：

### 3.1 最终产品（`products/`）

```
products/
  20251029_20251110.h5     ← GUNW（Geocoded Unwrapped Interferogram）产品
```

**GUNW `.h5` 内部结构（HDF5 格式）：**

| 数据组 | 内容 |
|--------|------|
| `science/LSAR/GUNW/grids/frequencyA/` | 主频段干涉图层 |
| `.../interferogram/HH/wrappedInterferogram` | 包裹相位（弧度） |
| `.../interferogram/HH/coherenceMagnitude` | 相干系数（0-1） |
| `.../interferogram/HH/unwrappedPhase` | 解缠相位（弧度） |
| `.../interferogram/HH/connectedComponents` | 连通分量标签 |
| `science/LSAR/GUNW/metadata/` | 轨道、时间、频率等元数据 |

---

### 3.2 中间过程文件（`scratch/`）

ISCE3 处理流水线中每个步骤写入 scratch 目录，处理完成后可安全删除：

```
scratch/
  rdr2geo/freqA/
    x.rdr / y.rdr / z.rdr      ← 地距坐标映射（经纬高）
    x.hdr / y.hdr / z.hdr      ← 对应头文件（ENVI 格式）
    topo.vrt                    ← GDAL VRT 虚拟合成文件
    RIFG_ifgram_dem.rdr/.hdr    ← RIFG 产品对应 DEM（雷达坐标系）
    RUNW_ifgram_dem.rdr/.hdr    ← RUNW 产品对应 DEM（雷达坐标系）

  geo2rdr/freqA/
    azimuth.off / azimuth.off.xml   ← 辅助景方位向像素偏移量
    range.off / range.off.xml       ← 辅助景距离向像素偏移量

  baseline/
    ref_geo2rdr_0/ ref_geo2rdr_1/   ← 参考景多视角 geo2rdr 结果
    sec_geo2rdr_0/ sec_geo2rdr_1/   ← 辅助景多视角 geo2rdr 结果
    x.rdr / y.rdr / z.rdr           ← 基线计算用坐标
    topo.vrt

  coarse_resample_slc/freqA/HH/
    coregistered_secondary.slc      ← 粗配准后辅助景 SLC（复数浮点）
    coregistered_secondary.hdr      ← 对应头文件

  dense_offsets/freqA/HH/
    dense_offsets                   ← 密集像素偏移量（方位+距离，二通道）
    dense_offsets.hdr
    snr                             ← 信噪比
    snr.hdr
    correlation_peak                ← 相关峰值
    correlation_peak.hdr
    covariance                      ← 偏移量协方差
    covariance.hdr
    gross_offset / gross_offsets    ← 粗偏移量（初始估计）
    gross_offsets.hdr
    reference.slc / reference.hdr   ← 配准用参考 SLC 片段

  fine_resample_slc/freqA/HH/
    coregistered_secondary.slc      ← 精配准后辅助景 SLC
    coregistered_secondary.hdr

  crossmul/freqA/HH/
    reference.slc / reference.hdr   ← 交叉相乘用参考 SLC

  rubbersheet_offsets/freqA/HH/
    azimuth.off / range.off         ← Rubbersheeting 校正后偏移量
    azimuth.hdr / range.hdr
    culled_az_offsets / culled_rg_offsets     ← 剔除异常后的方位/距离偏移
    culled_az_offsets.hdr / culled_rg_offsets.hdr
    resampled_az_offsets / resampled_rg_offsets  ← 重采样后的偏移量场
    resampled_az_offsets.hdr / resampled_rg_offsets.hdr
    groundTrackVelocity.tif         ← 地轨速度（用于偏移量归一化）

  RIFG.h5                          ← 雷达坐标系复干涉图（Radar-coord IFG）
  RUNW.h5                          ← 雷达坐标系解缠相位（Radar-coord UNWrapped）

  geocode_corrections/
    x.rdr / y.rdr / z.rdr          ← 地理编码坐标校正量

  unwrap/freqA/HH/
    snaphu.igram.<random>.c8       ← SNAPHU 输入：复干涉图（C8 格式）
    snaphu.corr.<random>.f4        ← SNAPHU 输入：相干系数（F4 格式）
    snaphu.unw.<random>.f4         ← SNAPHU 输出：解缠相位
    snaphu.conncomp.<random>.u4    ← SNAPHU 输出：连通分量
    snaphu.config.<random>.txt     ← SNAPHU 配置参数
```

---

## 四、数字汇总（以 7 景 NISAR RSLC 为例）

| | Path A（单对） | Path B Step 1（固定参考 stack） | Path B Step 2（tbase≤36d network） |
|---|---|---|---|
| 注册表条目 | 1 | 0 | 0 |
| project.json | 1 | 0 | 0 |
| runconfig YAML（per pair） | 1 | 6 | 15 |
| Job JSON | 1 | 1（batch） | 1（batch） |
| GUNW .h5 产品 | 1 | 6 | 15 |
| scratch 中间文件/对 | ~40 | ~40×6 | ~40×15 |
| pair_lists 文件 | 0 | 0 | 4 |
| stack_manifest.csv | 0 | 1 | 1 |
| param_tuned YAML | 0 或 1 | 0 或 1 | 0 或 1 |

---

## 五、处理流程与文件生成时序

### Path A（D-InSAR）

```
insar_create_project()
  → 写入 .insar_agent/project.json
  → 写入 ~/.local/share/insar_agent/registry.json

insar_set_runconfig_value() × 6
  → 更新 .insar_agent/project.json (runconfig 字段)

[PreToolUse hook 触发] → PARAM_ADVISOR_PROMPT
  → (可选) param-advisor 技能
    → insar_describe_rslc()      ← 读取 RSLC metadata，不写文件
    → 调用 .claude/agents/param-advisor.md subagent
    → insar_set_processing_param() × N
      → 更新 .insar_agent/project.json
    → insar_export_runconfig(output_dir="<workspace>/param_tuned")
      → 写入 param_tuned/runconfig.yaml

insar_run_workflow()
  → 写入 configs/runconfig.yaml（ISCE3 消费）
  → 写入 logs/<uuid>.log（实时）
  → 写入 logs/<uuid>.exitcode
  → 写入 .insar_agent/jobs/<uuid>.json
  → 启动 ISCE3 进程
    → 写入 runs/<date1>_<date2>/products/GUNW_*.h5
    → 写入 runs/<date1>_<date2>/scratch/（大量中间文件）
```

### Path B（Stack-InSAR）

```
[Step 0] [PreToolUse hook 触发] → PARAM_ADVISOR_PROMPT
  → (可选) param-advisor 技能（Path B 模式）
    → insar_describe_rslc()
    → .claude/agents/param-advisor.md subagent
    → insar_set_processing_param()（临时 project）
    → 写入 <data_dir>/base_runconfig_param_tuned.yaml

[Step 1] insar_prepare_stack()
  → 读取 base_runconfig（或 param_tuned YAML）
  → 检测 <data_dir>/base_runconfig_param_tuned.yaml
  → 写入 runconfigs/YYYYMMDD_YYYYMMDD.yaml × (N-1)
  → 写入 run_all.sh / run_parallel.sh
  → 写入 stack_manifest.csv
  → 写入 reference_date.txt

insar_run_batch(batch_dir=<stack_output_dir>)
  → 写入 .insar_agent/jobs/<uuid>.json
  → 写入 logs/<uuid>.log（实时）
  → 启动 bash run_parallel.sh → ISCE3 × (N-1)
    → 每对写入 runs/<date1>_<date2>/products/*.h5
    → 每对写入 runs/<date1>_<date2>/scratch/

[Step 2] insar_prepare_network()
  → [PreToolUse hook 触发] → PARAM_ADVISOR_PROMPT（若有）
  → 计算所有对的时间/垂直基线
  → 写入 pair_lists/pairs_tbase36d.txt（或按模式生成）
  → 写入 pair_lists/pairs_selected.txt / .csv
  → 写入 pair_lists/pair_baselines.csv
  → 写入 pair_lists/baseline_network.svg
  → 写入 runconfigs/YYYYMMDD_YYYYMMDD.yaml × M
  → 写入 run_all.sh / run_parallel.sh
  → 写入 stack_manifest.csv（网络对版）

insar_run_batch(batch_dir=<network_output_dir>)
  → 同 Step 1，产生 M 个 GUNW 产品
```

---

## 六、可以安全删除的文件

| 文件/目录 | 可删除时机 | 说明 |
|-----------|-----------|------|
| `scratch/` | 每对运行成功后 | 中间文件，GUNW 产品已含最终结果 |
| `logs/<uuid>.log` | 处理完成且不再调试时 | 可保留供排错参考 |
| `mplconfig/` | 任意时刻 | matplotlib 临时配置，可自动重建 |
| `RIFG.h5` / `RUNW.h5` | GUNW 产品已生成后 | 雷达坐标系中间产品 |

**不应删除：**
- `runconfigs/*.yaml`：用于复现和调试
- `stack_manifest.csv` / `pair_lists/`：MintPy 等后续工具需要读取
- `.insar_agent/` 目录：MCP 状态依赖
- `param_tuned/runconfig.yaml` / `base_runconfig_param_tuned.yaml`：避免重复调优
