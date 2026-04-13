#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from insar_agent.engines.isce2.stack_runtime import (
    materialize_single_burst_merged_outputs,
    normalize_offset_raster_to_slc_grid,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resume geometry-only ISCE2 stack run_files")
    parser.add_argument("--workspace", required=True, help="Geometry-only stack workspace")
    parser.add_argument("--conda-env", default="isce2", help="Conda environment name")
    return parser.parse_args()


def normalize_offsets(workspace: Path) -> None:
    root = workspace / "coreg_secondarys"
    for date_dir in sorted(root.glob("*")):
        iw2 = date_dir / "IW2"
        slc_xml = iw2 / "burst_01.slc.xml"
        for name in ["azimuth_01.off", "range_01.off"]:
            result = normalize_offset_raster_to_slc_grid(iw2 / name, slc_xml)
            print(result, flush=True)


def _run_in_isce2(conda_env: str, shell_cmd: str) -> None:
    subprocess.run(
        ["/home/august/miniconda3/bin/conda", "run", "-n", conda_env, "bash", "-lc", shell_cmd],
        check=True,
    )


def run_steps(workspace: Path, conda_env: str) -> None:
    run_dir = workspace / "run_files"
    prefix = f'export PATH="$ISCE_STACK/topsStack:$PATH" && cd "{run_dir}" && '

    for step in ["run_05_fullBurst_resample", "run_06_extract_stack_valid_region"]:
        print(f"=== {step} ===", flush=True)
        _run_in_isce2(conda_env, prefix + f"bash {step}")

    print("=== run_07_merge_reference_secondary_slc ===", flush=True)
    try:
        _run_in_isce2(conda_env, prefix + "bash run_07_merge_reference_secondary_slc")
    except subprocess.CalledProcessError:
        fallback = materialize_single_burst_merged_outputs(workspace, reference_date="20260105")
        print({"single_burst_merge_fallback": fallback}, flush=True)

    print("=== run_08_grid_baseline ===", flush=True)
    _run_in_isce2(conda_env, prefix + "bash run_08_grid_baseline")


def main() -> int:
    args = parse_args()
    workspace = Path(args.workspace)
    normalize_offsets(workspace)
    run_steps(workspace, args.conda_env)
    return 0


if __name__ == "__main__":
    sys.exit(main())
