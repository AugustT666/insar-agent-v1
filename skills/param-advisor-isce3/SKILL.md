---
name: param-advisor-isce3
description: >
  Use when the user wants parameter tuning recommendations for ISCE3 InSAR processing.
  Invoke when the user asks about processing parameters, multilook factors, phase
  unwrapping settings, ionosphere correction, troposphere correction, or says
  "tune parameters", "optimize parameters", "what parameters should I use", or
  "参数调优". Also invoke after d-insar-isce3 or stack-insar-isce3 skills if the
  user mentions they have a specific study area or data characteristics. Requires
  a project to have been created first (project_id needed for applying changes).
---

# 参数专家：ISCE3 InSAR 处理参数调优

## 角色定位

本 skill 是参数调优的**主 agent 编排器**，不直接在主对话中生成参数建议。
主 agent 只负责收集最小上下文、读取 project/runconfig、构造 evidence profile，
然后必须把“参数建议生成”委派给 `param-advisor-worker-isce3` subagent。

参数修改建议由 subagent 返回，主 agent 负责向用户展示、执行三选一确认、
在用户确认后调用 `insar_set_processing_param` 应用并继续后续流程。

参数建议来自本文档内的专家推理规则和 `assets/param_advisor_rules_insar.yaml`
中的结构化证据要求，由 AI 基于 evidence profile 执行推理逻辑。

---

## Hard Constraints（必须遵守，不得绕过）

- **强制 subagent**：参数建议阶段必须调用 `param-advisor-worker-isce3` subagent；
  主 agent 不得直接根据规则输出建议
- **模型下限**：参数专家 subagent 不得使用明显偏弱的小模型。优先使用
  `gpt-5.3-codex`（GPT-5.3-Codex）或 `claude-sonnet-4-6`（Claude Sonnet 4.6）
  或同等级模型；
  若客户端允许显式选模，禁止使用 mini/haiku 级模型做参数建议
- **三选一确认**：必须向用户呈现三个明确选项（见 Phase 3），不得代替用户做决定
- **风险提示**：每次输出建议时必须附带免责声明（见 Phase 3）
- **justification 非空**：调用 `insar_set_processing_param` 时，justification 必须具体
  说明原因（不接受"better performance"此类模糊理由）
- **展示完整 runconfig**：应用参数后必须调用 `insar_get_runconfig(format='yaml')` 展示
  完整 YAML，等待用户明确确认后，才能继续 export + run
- **白名单限制**：仅修改 `PROCESSING_PARAM_FIELDS` 注册表内的参数。其他字段用
  `insar_set_runconfig_value`（路径）或告知用户手动编辑
- **纯咨询模式**：若用户无 project_id（只想了解参数建议），跳过 MCP 工具调用，
  仅输出建议表和三选一说明

---

## 执行分工

### 主 agent 负责

- 收集或推断证据
- 构造 evidence profile
- 调用 `param-advisor-worker-isce3` subagent
- 接收并核查结构化建议
- 向用户展示三选一
- 在确认后调用 MCP 工具应用参数

### subagent 负责

- 读取 evidence profile、runconfig 摘要、参数 registry 摘要
- 输出结构化建议：默认值、建议值、证据、风险、置信度、保持默认理由、缺失信息
- 使用足够强的模型生成建议：推荐 `gpt-5.3-codex`（GPT-5.3-Codex）或
  `claude-sonnet-4-6`（Claude Sonnet 4.6）

如果 subagent 失败，主 agent 不得直接补做建议；只能停在证据收集阶段，或退回默认参数路径。

---

## 输入收集清单（Phase 1）

收集以下信息，逐项询问缺失部分。必须先尝试从 runconfig、RSLC 文件名、DEM/工作区
上下文中自动推断，再只询问高影响缺失项。

每条证据都要标注来源：`user_provided` / `runconfig_inferred` / `metadata_inferred` /
`external_lookup`。如果只是推断，必须明确说明。

### 遥感数据特征（对参数影响最大）

| 信息 | 典型取值 |
|---|---|
| 传感器/卫星 | NISAR / Sentinel-1 / ALOS-2 / TerraSAR-X |
| 波段 | L (NISAR/ALOS-2) / C (Sentinel-1) / X (TerraSAR-X) |
| 极化方式 | HH / VV / HV / VH |
| 轨道方向 | 升轨 / 降轨 |
| 重访周期（天） | 如 12 天 (Sentinel-1)、26 天 (NISAR) |
| **时间基线**（本次影像对，天） | 直接影响多视数和解缠难度 |
| 垂直基线（m，可选） | 影响地形相位强度 |
| 空间分辨率（m） | 影响多视后目标分辨率估计 |

### 研究区特征

| 信息 | 典型取值 |
|---|---|
| 地物类型 | 城市 / 农业 / 沿海 / 山地 / 荒漠 / 冻土 |
| 地形起伏 | 平坦 (<100m) / 中等 (100–500m) / 显著 (>500m) |
| 气候条件 | 干旱 / 湿润 / 季风区 / 沿海 |
| 纬度范围 | 用于判断电离层影响（高纬度 >50° 需注意）|

### 科学目标

| 信息 | 典型取值 |
|---|---|
| 任务类型 | 单次形变监测 / 时序分析 / 相干制图 |
| 形变量级 | 毫米级 (<5mm) / 厘米级 (5–50mm) / 大形变 (>50mm) |
| 形变空间尺度 | 局部 (<10km) / 区域 (10–100km) / 大范围 (>100km) |

---

## 专家推理规则（Phase 2）

对照以下规则逐一检查每个可调参数。需要改动的参数进入建议 diff 表，
无需改动的简要说明"保持默认，理由是…"。**如不确定，明确告知，请用户判断。**

### 多视数（crossmul.range_looks / azimuth_looks）

**默认值：** range_looks=11, azimuth_looks=11（NISAR L波段标准多视）

推理逻辑：

- **城市区域 + L波段 + 短时间基线（<30天）**
  → 城市 L波段相干性通常较高，可适当减小多视数以保留分辨率
  → 建议：range_looks=5, azimuth_looks=5（若研究对象为建筑物形变，精细分辨率更有意义）

- **农业区 / 植被区 + 长时间基线（>60天）**
  → 植被区时间去相干显著，增大多视数可提升相干性，代价是分辨率降低
  → 建议：range_looks=15~20, azimuth_looks=15~20

- **荒漠 / 干旱区 + 任意时间基线**
  → 相干性通常很好，默认值一般适用；若需高精度分辨率可减小多视数

- **C波段 vs L波段：** L波段穿透能力强、相干性更高，相同场景下多视数可略小于C波段

- **时序分析（MintPy）目标**
  → 保持默认或略增大多视数，优先保证相干性，利于后续时序处理

### 干涉图滤波（filter_interferogram.filter_type）

**默认值：** no_filter

推理逻辑：

- **高相干场景（城市、荒漠）**
  → 维持 no_filter；滤波会损失分辨率，高相干时不必要

- **低相干场景（农业、植被、长时间基线）**
  → 可考虑启用 boxcar 或 gauss 滤波以降低噪声，但 SKILL 目前未提供具体参数规则
  → 建议告知用户手动评估滤波参数

### 解缠算法（phase_unwrap.algorithm）

**默认值：** snaphu

推理逻辑：

- snaphu 是最通用选择，适合大多数场景，建议保持默认
- icu / phass 速度较快，但精度相对较低，适合快速浏览或高相干场景
- **一般建议保持 snaphu**

### Snaphu 代价函数（phase_unwrap.snaphu.cost_mode）

**默认值：** smooth

推理逻辑：

- **缓慢形变 / 地面沉降 / 大气延迟**
  → smooth（默认）：平滑先验，适合连续、渐变的相位场

- **同震形变 / 滑坡 / 火山隆升（形变梯度大、局部化）**
  → defo：专为形变设计，允许较大的相位梯度，防止解缠时将真实形变当做噪声丢弃

- **地形相位为主（垂直基线大、DEM误差）**
  → topo：地形感知代价函数，针对地形相位优化

### Snaphu 等效视数（phase_unwrap.snaphu.nlooks）

**默认值：** null（Snaphu 自动估计）

推理逻辑：

- 大多数情况保持 null（自动）即可
- 若解缠质量较差（噪声区域出现大块错误），可尝试手动设定（通常 range_looks × azimuth_looks 的乘积附近）
- **通常建议保持 null**

### Snaphu 分块数（phase_unwrap.snaphu.ntiles）

**默认值：** null（单片解缠）

推理逻辑：

- **大形变（>50mm / >1/4 个波长）+ 空间覆盖 >50km**
  → 分块解缠可防止误差跨区域传播，建议 ntiles=[4, 4] 或 [8, 8]

- **形变较小 / 覆盖范围有限**
  → 保持 null，单片解缠更稳定

### 解缠前额外多视数（phase_unwrap.range_looks / azimuth_looks）

**默认值：** 1（不额外多视）

推理逻辑：

- 通常保持默认（1），crossmul 阶段已完成主要多视
- 若解缠效果差且相位非常噪，可适当调大（如 2~3），但代价是分辨率进一步降低
- **通常建议保持默认 1**

### 电离层相位校正（ionosphere_phase_correction.enabled）

**默认值：** false

推理逻辑：

- **L波段 + 高纬度（>50°N/S）+ 太阳活动高峰期（太阳黑子极大期）**
  → 电离层影响显著，建议 enabled=true
  → ⚠️ 高风险：开启后处理时间增加，且需要辅助数据；如不确定，可先用 false 跑一次评估

- **L波段 + 低纬度热带区域**
  → 赤道附近电离层闪烁（scintillation）较严重，也应考虑开启

- **L波段 + 中纬度（30°–50°）+ 太阳活动平静期**
  → 通常影响较小，可保持 false；如发现低频相位条纹，再开启

- **C波段**
  → 电离层影响通常可忽略，保持 false

### 对流层延迟校正（troposphere_delay.enabled）

**默认值：** false

推理逻辑：

- **地形起伏 >500m + 覆盖范围 >100km**
  → 地形对流层相关性显著，建议 enabled=true
  → ⚠️ 高风险：需要外部气象/再分析数据，处理时间增加

- **湿润气候 / 季风区 / 沿海区域 + 大范围覆盖（>100km）**
  → 对流层延迟变化较大，开启可改善干涉图质量

- **干旱区 / 荒漠 + 短基线 + 小范围覆盖（<50km）**
  → 对流层延迟通常较小且空间一致性高，保持 false

---

## Phase 3 — 三选一确认（核心交互，不得省略）

输出建议 diff 表格后，**必须**向用户明确提出以下三个选项：

```
根据你的数据和研究区特征，我建议进行以下参数调整：

| 参数 | 默认值 | 建议值 | 改动理由 |
|------|--------|--------|----------|
| ... | ... | ... | ... |

请选择参数方案：

① 使用默认参数（模板值）直接运行，不做任何修改
② 采用以上建议参数（AI 推荐，详见上方理由）
③ 自行指定参数（你来告诉我每个字段填什么）

⚠️  重要提示：以上建议基于通用 InSAR 处理规律，对你的具体数据可能不完全适用。
   你是本次数据处理的第一责任人，建议结合自身 InSAR 经验判断后再决定。
   如有条件，也可以用①和②各创建一个项目，对比处理结果。
```

**选择①**（默认参数）：
- 不调用 `insar_set_processing_param`
- 直接进入 `insar_validate_runconfig` → `insar_export_runconfig` → `insar_run_workflow`

**选择②**（采纳建议）：
1. 逐个调用 `insar_set_processing_param(justification=<具体理由>)`
2. 调用 `insar_get_runconfig(format='yaml')` 展示**完整 runconfig YAML**
3. 再次提示用户核对，等用户明确说"确认"或"继续"后再进行 export + run

**选择③**（用户自填）：
1. 对每个可调参数展示当前值和参数说明，询问用户想改成什么
2. 用户提供值 → 调用 `insar_set_processing_param`（justification 填写用户提供的理由）
3. 展示完整 YAML → 用户确认 → export + run

**对比运行（可选，用户提出时）**：
- 建议创建两个 project（相同路径字段，不同参数），并行处理
- 完成后用 `insar_list_outputs` 对比两个 project 的输出

---

## 可调参数速查

以下参数来自 `assets/processing_params_insar.yaml`，是本 skill 唯一允许调用
`insar_set_processing_param` 修改的字段：

| 参数 key（简写） | 默认值 | 风险 |
|---|---|---|
| `crossmul.range_looks` | 11 | medium |
| `crossmul.azimuth_looks` | 11 | medium |
| `filter_interferogram.filter_type` | no_filter | low |
| `phase_unwrap.algorithm` | snaphu | medium |
| `phase_unwrap.snaphu.cost_mode` | smooth | medium |
| `phase_unwrap.snaphu.nlooks` | null | low |
| `phase_unwrap.snaphu.ntiles` | null | medium |
| `phase_unwrap.range_looks` | 1 | medium |
| `phase_unwrap.azimuth_looks` | 1 | medium |
| `ionosphere_phase_correction.enabled` | false | high |
| `troposphere_delay.enabled` | false | high |

完整 key 格式：`runconfig.groups.processing.<上表简写>`
