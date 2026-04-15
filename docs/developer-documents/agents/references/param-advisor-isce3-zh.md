# Param Advisor ISCE3 参考资产

本文档存放 `.claude/agents/param-advisor.md` 使用的参数建议 heuristics 与证据模式。
它是参考资产，不是 subagent contract。

## Evidence Profile 指引

证据优先级按以下顺序使用：

1. `insar_describe_rslc` 提供的本地元数据
2. 当前 runconfig / project 上下文
3. 用户明确提供的场景事实
4. 在 web search 后真正采用的外部参考

每个推断事实都应标注为以下之一：

- `user_provided`
- `runconfig_inferred`
- `metadata_inferred`
- `external_lookup`

如果本地元数据与用户上下文仍然不足，允许 web search，但本地可观测事实仍应是主依据。

## 最关键的场景因素

- 传感器 / 卫星
- 波段（`L`、`C`、`X`）
- 极化
- 轨道方向
- 时间基线
- 垂直基线（若可得）
- 地形起伏
- 地表覆盖类型
- 气候 / 湿度环境
- 形变目标与空间尺度

## 参数启发式

### Multilook：`crossmul.range_looks` / `crossmul.azimuth_looks`

默认值：`11 / 11`

- 城市 + L 波段 + 短时间基线：可考虑较小 looks，例如 `5 / 5`，以保留分辨率
- 农业 / 植被 + 长时间基线：可考虑较大 looks，例如 `15-20 / 15-20`，提升 coherence
- 沙漠 / 干燥裸地：默认值通常仍可接受
- 时序 / MintPy 任务：优先选择更能保持 coherence 的默认值，或略大的 looks

## 时序 / Path B 指引

当一份调优后的 `base_runconfig` 会传播到许多 stack 或 network pairs 时：

- 优先保守调整，而不是激进地优化单对
- 更重视整个 stack 的稳定 coherence 与 unwrap 健壮性
- 如果证据较弱，应倾向保留默认值
- 如果 pair/network 设计仍可能改变，应提醒主 agent 保持用户控制权
- 只有证据很强时，才建议更锐利、looks 更小的设定

### 干涉图滤波：`filter_interferogram.filter_type`

默认值：`no_filter`

- 高 coherence 的城市或沙漠场景：通常保持 `no_filter`
- 低 coherence 的植被场景：滤波可能有帮助，但只有在证据较强时才建议更改

### 解缠算法：`phase_unwrap.algorithm`

默认值：`snaphu`

- 对大多数场景，仍以 `snaphu` 作为默认推荐
- 只有在快速预览或 coherence 非常高的场景下，才考虑更快替代方案

### Snaphu cost mode：`phase_unwrap.snaphu.cost_mode`

默认值：`smooth`

- 缓慢、空间上平滑的形变：`smooth`
- 大的局部形变或震后形变：考虑 `defo`
- 地形主导相位或 DEM 敏感的大起伏地形：考虑 `topo`

### Snaphu nlooks / tiles

默认值：`nlooks = null`，`ntiles = null`

- 除非 unwrap 质量明显不好，否则保持 `nlooks = null`
- 对特别大、相位梯度很强的形变场景，可考虑 `ntiles`

### Additional unwrap looks：`phase_unwrap.range_looks` / `phase_unwrap.azimuth_looks`

默认值：`1 / 1`

- 通常保持默认值
- 只有在 unwrap 稳定性明显比空间细节更重要时才增加

### 电离层校正：`ionosphere_phase_correction.enabled`

默认值：`false`

- L 波段 + 高纬度或强电离层活动：可考虑开启
- L 波段赤道 / scintillation 易发区域：可考虑开启
- C 波段：通常保持关闭
- 如果所需 ancillary 输入缺失，应把它视为高风险建议

### 对流层校正：`troposphere_delay.enabled`

默认值：`false`

- 大起伏地形 + 宽覆盖：可考虑开启
- 潮湿 / 沿海 / 季风区的大范围场景：可考虑开启
- 干燥、紧凑场景：通常保持关闭
- 如果天气模型输入未准备好，应把它视为高风险建议

## 默认值 vs 变更的判断规则

优先保留默认值的情况：

- 证据弱或互相矛盾
- 改动需要额外 ancillary 输入，而当前没有准备
- 当前目标是探索性运行，而默认值已经是标准推荐

优先建议变更的情况：

- 本地元数据 + 用户上下文指向了一个已知的高影响不匹配
- 该变更属于白名单控制参数，且理由清晰
- 用户目标明确强调 coherence、形变敏感性或分辨率取舍

## 输出期望

对每一项建议变更，都应包含：

- 当前值
- 默认值
- 建议值
- 理由
- 风险
- 置信度
- provenance
