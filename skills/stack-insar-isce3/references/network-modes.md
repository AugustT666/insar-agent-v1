# Interferogram Network Modes

Use with `insar_prepare_network(network_mode=..., ...)`.

## Mode comparison

| Mode | Parameter | Description |
|------|-----------|-------------|
| `tbase` | `max_temporal_baseline_days` (default 36) | Connect all pairs whose temporal separation ≤ threshold. Dense network, good for slow deformation. |
| `conn` | `connection_span` (default 3) | Connect each scene to the next N scenes in chronological order. Sparser, good for rapid deformation. |
| custom | `pair_list=/path/pairs.txt` | Use an explicit list of pairs. `network_mode`, `max_temporal_baseline_days`, and `connection_span` are ignored. |

## Custom pair list format

One pair per line, format `YYYYMMDD_YYYYMMDD`:

```
20240101_20240201
20240201_20240301
20240101_20240301
```

## Choosing a mode

- Start with `tbase` at 36 days for standard NISAR 12-day repeat.
- Use `conn` with span=1 for the minimum spanning network.
- Use custom when you have a specific science requirement (e.g., cross-season pairs).
