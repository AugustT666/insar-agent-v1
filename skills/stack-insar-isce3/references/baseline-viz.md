# Baseline Network Visualization

Run after the interferogram network has actually finished and produced GUNW products.
Use the MCP tool `insar_plot_baseline`, not the raw script, when you are operating as an AI client.

## MCP usage

```text
insar_plot_baseline(
    network_dir=<network_output_dir>,
    pair_list="",          # optional
    title="ISCE3 Spatiotemporal Baseline Network",
    interaction_mode=<interactive|auto>
)
```

In `interactive` mode this is a mandatory review checkpoint before MintPy.
If the user wants to change pair selection after reviewing the figure, go back to
`insar_prepare_network` instead of continuing.

## Output files

| File | Description |
|------|-------------|
| `pair_baselines.csv` | Temporal and perpendicular baseline per pair |
| `scene_baselines.csv` | Per-scene baseline relative to reference |
| `baseline_network.png` | Spatiotemporal network plot |
| `baseline_network.pdf` | Vector version of the same plot |

## Notes

- The tool reads perpendicular baseline from the real GUNW products.
- If the network has not finished, or products are missing, plotting will fail.
- Full time-series processing continues through `insar_run_mintpy` and the
  `mintpy` skill (engine=isce3).
