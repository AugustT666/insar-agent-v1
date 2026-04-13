#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


CONDA = "/home/august/miniconda3/bin/conda"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resume interferogram-only ISCE2 stack run_files")
    parser.add_argument("--workspace", required=True, help="Interferogram stack workspace")
    parser.add_argument("--conda-env", default="isce2", help="Conda environment name")
    return parser.parse_args()


def _run_in_isce2(conda_env: str, shell_cmd: str) -> None:
    subprocess.run([CONDA, "run", "-n", conda_env, "bash", "-lc", shell_cmd], check=True)


def _copy_tree_sidecars(src_base: Path, dst_base: Path) -> None:
    dst_base.parent.mkdir(parents=True, exist_ok=True)
    if src_base.exists():
        shutil.copy2(src_base, dst_base)
    for suffix in [".xml", ".vrt"]:
        src = src_base.with_suffix(src_base.suffix + suffix)
        if src.exists():
            shutil.copy2(src, dst_base.with_suffix(dst_base.suffix + suffix))


def _materialize_from_vrt(vrt_base: Path, out_base: Path, conda_env: str) -> None:
    out_base.parent.mkdir(parents=True, exist_ok=True)
    shell_cmd = (
        f'gdal_translate -of ENVI "{vrt_base}.vrt" "{out_base}" && '
        f'python -m isce.applications.gdal2isce_xml -i "{out_base}"'
    )
    _run_in_isce2(conda_env, shell_cmd)


def prepare_single_burst_ifg_outputs(workspace: Path, conda_env: str) -> None:
    merged_slc = workspace / "merged" / "SLC"
    for date_dir in sorted(merged_slc.glob("*")):
        base = date_dir / f"{date_dir.name}.slc"
        full = date_dir / f"{date_dir.name}.slc.full"
        if not base.exists():
            source_vrt = None
            if date_dir.name == "20260105":
                source_vrt = workspace / "reference" / "IW2" / "burst_01.slc"
            else:
                source_vrt = workspace / "secondarys" / date_dir.name / "IW2" / "burst_01.slc"
            _materialize_from_vrt(source_vrt, base, conda_env)
        _copy_tree_sidecars(base, full)

    merged_ifg_root = workspace / "merged" / "interferograms"
    for pair_dir in sorted((workspace / "interferograms").glob("*_*")):
        src = pair_dir / "IW2" / "fine_01.int"
        dst_dir = merged_ifg_root / pair_dir.name
        fine = dst_dir / "fine.int"
        fine_full = dst_dir / "fine.int.full"
        _copy_tree_sidecars(src, fine)
        _copy_tree_sidecars(src, fine_full)


def main() -> int:
    args = parse_args()
    workspace = Path(args.workspace)
    run_dir = workspace / "run_files"
    prefix = f'export PATH="$ISCE_STACK/topsStack:$PATH" && cd "{run_dir}" && '

    print("=== run_08_generate_burst_igram ===", flush=True)
    _run_in_isce2(args.conda_env, prefix + "bash run_08_generate_burst_igram")

    print("=== run_09_merge_burst_igram ===", flush=True)
    try:
        _run_in_isce2(args.conda_env, prefix + "bash run_09_merge_burst_igram")
    except subprocess.CalledProcessError:
        prepare_single_burst_ifg_outputs(workspace, args.conda_env)
        print({"single_burst_ifg_merge_fallback": str(workspace / 'merged' / 'interferograms')}, flush=True)

    print("=== run_10_filter_coherence ===", flush=True)
    _run_in_isce2(args.conda_env, prefix + "bash run_10_filter_coherence")

    print("=== run_11_unwrap ===", flush=True)
    _run_in_isce2(args.conda_env, prefix + "bash run_11_unwrap")
    return 0


if __name__ == "__main__":
    sys.exit(main())
