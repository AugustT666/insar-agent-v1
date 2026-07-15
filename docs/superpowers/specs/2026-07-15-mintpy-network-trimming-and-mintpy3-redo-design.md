# MintPy 网络提质（剔除低相干干涉对）+ mintpy3 数据重做 — 设计

- **日期**: 2026-07-15
- **状态**: 已批准，待落实施计划（writing-plans）
- **增量**: A（本次执行）。配套后续增量见 [`2026-07-15-full-native-templates-and-advisor-whole-review-design.md`](./2026-07-15-full-native-templates-and-advisor-whole-review-design.md)（增量 B，deferred）
- **相关仓库**: 插件 `insar-agent`（本仓库）；数据工作区 `/mnt/HDD2T/August/IntegrationTest2/workspace/stack-insar-isce2_20260621T181630Z/insar_product/`

## 1. 背景与问题

用户此前在 `insar_product/mintpy2` 跑了一次 Sentinel-1 时序（31 景 / 87 干涉对，2020 全年），结果不理想。诊断确认根因是**组网时没有剔除低质量（低相干）干涉对**：

- `mintpy.network.coherenceBased = auto`（解析为 `no`），`dropIfgram` **全为 True，0 对被排除**，87 个对原样进入反演。
- 逐对平均空间相干中位仅 **0.539**；**40% 的对 < 0.5、61% < 0.6**，低相干对集中在 2020 夏季（植被/湿季失相干）。
- 唯一的剔除是残差 RMS 自动剔的 2 个采集日（20200528、20200901），属反演层剔坏影像，**不是干涉对级别的相干裁剪**。

这不仅是本次数据的问题，也是插件缺陷：**插件的 MintPy 受管模板 `_default_template_text`（`src/insar_agent/engines/isce2/mintpy.py`）一行 `mintpy.network.*` 都没写**，`modify_network` 沿用 MintPy 默认（不裁剪）。等于把"要不要做网络提质"这个决定整个漏掉了。

### 连通性证据（决定阈值）

全连通需 ≥ 30 条边（31 景）。各 `minCoherence` 阈值下（本数据）：

| minCoherence | 保留对 | 剔除 | 连通分量 | 备注 |
|---|---|---|---|---|
| 0.40 | 85 | 2 | 1（连通） | 几乎没裁 |
| **0.406** | **82** | **5** | **1（连通，每景≥3边）** | **本次采用：只剔最差 5 对夏季对** |
| 0.45 | 73 | 14 | 1（连通） | 偏强 |
| 0.50 | 52 | 35 | 7（需 MST 回补） | 剔掉整个夏季差对 |

被剔的 5 对（均为 2020 夏季失相干）：`20200528_20200703`(0.388)、`20200727_20200820`(0.392)、`20200621_20200727`(0.402)、`20200703_20200727`(0.404)、`20200820_20200925`(0.405)。

**阈值非硬标准**——目标是剔掉少量最差对（~5 对）。`0.406` 落在第 5、6 差对之间（0.4054 / 0.4078）。`keepMinSpanTree = yes` 作兜底保连通（本力度下网络本已连通，无需 MST 回补）。

## 2. 目标 / 非目标

**目标**
1. 让"剔除低相干干涉对"成为插件 MintPy 侧的一等能力：受管模板改为**官方完整 119 参数模板**，network 组默认开启相干裁剪（保守地板），并把**可编辑模板路径回报给用户**。
2. 用网络提质后的配置**重跑时序到 `mintpy3`**，与 `mintpy2` 对比验证效果。

**非目标（留给增量 B）**
- ISCE2 topsStack / ISCE3 完整模板的暴露与编辑面放宽。
- 参数顾问从"白名单子集"改为"通篇逐步骤只读审阅"。
- NISAR MintPy 的模板/顾问覆盖。

## 3. 设计

### Part 1 — 插件：官方完整模板 + network 默认

**3.1 受管模板改为官方全量模板（真源）**

`isce2_stack.txt` 当前是稀疏覆盖（~20 行），靠 `smallbaselineApp.py -g` 与官方模板合并。改为：

- 新增 `_load_official_mintpy_template(conda_env)`：从**解析出的 MintPy conda env** 定位官方模板
  `.../envs/<env>/lib/python*/site-packages/mintpy/defaults/smallbaselineApp.cfg`（119 参数、全 `auto`、带注释）。
  定位失败时回退到插件内一份**版本标注的 assets 副本** `engines/isce2/assets/smallbaselineApp_full.cfg`（附单测校验其键集与安装版一致，防漂移）。
- `_default_template_text` 改为：以官方全量模板文本为基底，用现有 `set_mintpy_cfg_value` 的同一套"逐行 upsert、其余字节保留"逻辑，叠加插件 override：
  - **数据加载路径**（原有 `mintpy.load.*` 14 行，保持不变）；
  - **处理开关**（`plot=no`、`unwrapError.method=bridging+phase_closure`、`solidEarthTides=yes`、`deramp=quadratic`、`ionosphericDelay.method=no`、tropo 段、`topographicResidual=yes`，保持不变）；
  - **network 默认（新增）**：`coherenceBased=yes`、`minCoherence=0.2`、`keepMinSpanTree=yes`。
- 结果：`isce2_stack.txt` 成为**带注释的官方完整模板 + 插件 override**，专业用户可就地编辑任意参数。`-g` 合并对已是全量的模板幂等，行为不变。

**3.2 默认 network 行为**

- 默认 `coherenceBased=yes` + `minCoherence=0.2` + `keepMinSpanTree=yes`。
- `0.2` 是**安全地板**：本数据 0 对 < 0.3，故默认几乎不误伤；作用是"机制默认开着、阈值保守，是否收紧交给参数顾问审后建议"。符合既有原则「模板默认值不写死激进值」（见记忆 feedback_insar_template_defaults_not_hardcoded）。
- 不加"锁比例/锁阈值"的不变量测试。

**3.3 参数注册表补键**

`engines/isce2/assets/processing_params_mintpy.yaml` 已有 `network.coherenceBased/minCoherence/tempBaseMax/perpBaseMax/excludeDate`。新增：
- `network.keepMinSpanTree`（bool，保连通开关）
- `network.excludeIfgIndex`（str，显式剔除指定干涉对索引）

**3.4 SKILL 指导**

`skills/mintpy/SKILL.md` 增加"网络提质 / 剔除低相干对"小节：
- 说明 `coherenceBased` / `minCoherence` / `keepMinSpanTree` 的作用与联动（阈值裁剪 + MST 保连通）。
- 说明运行后**受管模板 `<mintpy_work_dir>/isce2_stack.txt` 即完整可编辑模板**，专业用户可就地改任意 MintPy 参数；工具应把该路径回报给用户。
- 提示 agent：跑 MintPy 前应审查网络相干性，必要时经参数顾问 `stage=mintpy` 收紧 `minCoherence`。

**3.5 测试**

- 种子模板包含全部官方参数组（按 network/networkInversion/timeFunc 等关键组的代表键断言存在）。
- 种子模板 network 默认为 `coherenceBased=yes`、`minCoherence=0.2`、`keepMinSpanTree=yes`。
- 注册表含新键 `network.keepMinSpanTree`、`network.excludeIfgIndex` 且取值域合法。
- `set_mintpy_cfg_value` 对全量模板 upsert 后：目标键被替换、其余行（含注释）逐字保留。
- assets 副本键集与安装版 MintPy 模板一致（防漂移）。

### Part 2 — mintpy3 数据重做

**3.6 输入与数据安全**

- **独立 inputs**：`mintpy2/inputs -> ../mintpy/inputs` 与 `mintpy` 共用同一 `ifgramStack.h5`。相干裁剪会翻转其中 `dropIfgram`，若共享会**污染 mintpy/mintpy2 原始网络**。故 `mintpy3` 必须从 stack 重跑 `load_data` 生成**自己独立的 `inputs/`**，绝不复用软链。
- **复用 ERA5**：mintpy2 已下好 ERA5 天气文件；`mintpy3` 的 `weather_dir` 指向同一目录，免重下、规避 CDS 限流。

**3.7 配置**

- 与 mintpy2 **仅改一个变量**（网络提质），其余对齐以便干净对比：
  - network：`coherenceBased=yes`、`minCoherence=0.406`（本次力度，只剔最差 ~5 对，覆盖默认 0.2；阈值非硬标准）、`keepMinSpanTree=yes`。
  - 校正链沿用 mintpy2：SET + ERA5 tropo + quadratic deramp + topographicResidual(demErr)；`unwrapError.method=bridging+phase_closure`。
- 通过新版插件 seed 完整模板 → 将 `minCoherence` 覆盖为 0.45 → 以 `mintpy_config=<mintpy3>/isce2_stack.txt` 显式重跑（dogfood 新模板）。

**3.8 执行方式**

- 由主会话**直接后台运行** `smallbaselineApp` 全链（经插件 `insar_run_mintpy_isce2` 启动的后台作业；用户已确认此执行方式，覆盖"dev 不直接跑数据"的既有边界）。
- 监控用统一机制：Monitor 优先（有限 timeout + 进度 grep）+ 后台单次 sleep 兜底；`insar_get_job` 为状态权威源；每次醒来按 CST 播报下次重检。

**3.9 完成后对比（mintpy2 ↔ mintpy3）**

- 网络：保留对数（预期 87 → 82，剔最差 5 对）、被剔对清单。
- 质量：`temporalCoherence.h5` 通过率 / `maskTempCoh.h5` 有效像元覆盖率、`rms_timeseriesResidual_ramp.txt` 残差、自动剔除日期变化。
- 结果：`velocity.h5` 形变速率的空间一致性与噪声水平对比（同参考点、同色标）。
- 产出简短对比小结报告给用户。

## 4. 风险与缓解

- **官方模板定位失败**（MCP server 环境无 mintpy）→ 从解析出的 conda env site-packages 定位；再回退 assets 版本标注副本 + 防漂移单测。
- **全量模板改动影响既有 ISCE2 MintPy 跑法** → `-g` 合并对全量模板幂等；override 行集合不变；以既有 ISCE2 MintPy 单测回归护栏。
- **mintpy3 误改共享 ifgramStack.h5** → 强制独立 inputs（3.6），跑前校验 `mintpy3/inputs` 不是指向 `../mintpy` 的软链。
- **过度裁剪导致网络断裂** → `keepMinSpanTree=yes` 保连通；0.45 本数据自然连通（1 连通分量）。

## 5. 交付物

1. 插件改动：`engines/isce2/mintpy.py`（模板生成）、`engines/isce2/assets/processing_params_mintpy.yaml`（补键）、可能的 `engines/isce2/assets/smallbaselineApp_full.cfg`（回退副本）、`skills/mintpy/SKILL.md`（指导）、对应单测。
2. 数据产物：`insar_product/mintpy3/`（含 `velocity.h5`、`timeseries*.h5` 等）。
3. mintpy2 ↔ mintpy3 对比小结。
