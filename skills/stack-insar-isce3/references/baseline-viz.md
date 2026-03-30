# Baseline Network Visualization

Run after `insar_prepare_network` to visualize the spatiotemporal baseline network.

## Script

`docs/archive/knowledge-base/wangshuai/Scripts/plot_isce3_baseline_network.py`

## Usage

```bash
python docs/archive/knowledge-base/wangshuai/Scripts/plot_isce3_baseline_network.py \
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

Full time-series processing is available through `insar_run_mintpy` and the
`mintpy-isce3` skill.
