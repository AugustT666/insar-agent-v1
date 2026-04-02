# 干涉图网络模式

配合 `insar_prepare_network(network_mode=..., ...)` 使用。

## 模式对比

| 模式 | 参数 | 说明 |
|------|------|------|
| `tbase` | `max_temporal_baseline_days`（默认 36） | 连接所有时间间隔 ≤ 阈值的 pair。网络更密，适合缓慢形变。 |
| `conn` | `connection_span`（默认 3） | 按时间顺序，把每一景连接到后续的 N 景。网络更稀疏，适合快速形变。 |
| custom | `pair_list=/path/pairs.txt` | 使用显式给定的 pair 列表。`network_mode`、`max_temporal_baseline_days` 和 `connection_span` 都会被忽略。 |

## 自定义 pair list 格式

一行一个 pair，格式为 `YYYYMMDD_YYYYMMDD`：

```
20240101_20240201
20240201_20240301
20240101_20240301
```

## 如何选择模式

- 对标准 NISAR 12 天重访场景，可先从 `tbase`、36 天起步。
- 若想要最小连接网络，可使用 `conn` 且 `span=1`。
- 如果有明确科学需求（例如跨季节配对），就使用 custom 模式。
