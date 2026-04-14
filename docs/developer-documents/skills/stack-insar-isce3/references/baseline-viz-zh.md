# 基线网络可视化

在干涉图网络已经实际跑完并生成 GUNW 产品之后运行。
作为 AI 客户端时，应优先使用 MCP 工具 `insar_plot_baseline`，而不是直接调用脚本。

## MCP 用法

```text
insar_plot_baseline(
    network_dir=<network_output_dir>,
    pair_list="",          # 可选
    title="ISCE3 Spatiotemporal Baseline Network",
    interaction_mode=<interactive|auto>
)
```

在 `interactive` 模式下，这一步是进入 MintPy 之前的强制检查窗口。
如果用户看完图后想调整 pair 选择，就回到 `insar_prepare_network`，不要继续。

## 输出文件

| 文件 | 说明 |
|------|------|
| `pair_baselines.csv` | 每个 pair 的时间基线和垂直基线 |
| `scene_baselines.csv` | 各景相对于参考景的基线 |
| `baseline_network.png` | 时空网络图 |
| `baseline_network.pdf` | 同一图的矢量版本 |

## 说明

- 该工具从真实 GUNW 产品中读取垂直基线，不是仅凭 pair list 画图。
- 如果 network 没跑完，或者某些产品缺失，绘图会失败。
- 完整的时序处理继续通过 `insar_run_mintpy` 和 `mintpy` skill 完成。
