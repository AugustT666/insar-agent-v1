# Baseline Network Visualization

Run after `insar_prepare_network` to visualize the spatiotemporal baseline network.

## Script

`knowledge-base/wangshuai/Scripts/plot_isce3_baseline_network.py`

## Usage

```bash
python knowledge-base/wangshuai/Scripts/plot_isce3_baseline_network.py \
    --pair-list <network_output_dir>/pairs_manifest.txt \
    --output-dir <network_output_dir>
```

## Output files

| File | Description |
|------|-------------|
| `pair_baselines.csv` | Temporal and perpendicular baseline per pair |
| `scene_baselines.csv` | Per-scene baseline relative to reference |
| `baseline_network.png` | Spatiotemporal network plot |
| `baseline_network.pdf` | Vector version of the same plot |

## Future

Full time-series processing (MintPy) will be available via the `mintpy-isce3` skill
once M6 MCP tools are implemented.
