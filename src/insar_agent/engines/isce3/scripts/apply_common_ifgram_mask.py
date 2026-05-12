#!/usr/bin/env python3
"""Force a common valid-pixel mask across all interferograms in ifgramStack.h5."""

from __future__ import annotations

import argparse
from pathlib import Path

import h5py
import numpy as np


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply a common valid-pixel mask to MintPy ifgramStack datasets."
    )
    parser.add_argument("stack_file", help="Path to inputs/ifgramStack.h5")
    parser.add_argument(
        "--coherence-threshold",
        type=float,
        default=0.4,
        help="Common-mask threshold applied to coherence",
    )
    parser.add_argument(
        "--row-chunk",
        type=int,
        default=200,
        help="Rows processed per chunk",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    stack_path = Path(args.stack_file).resolve()
    if not stack_path.exists():
        raise FileNotFoundError(f"ifgramStack file not found: {stack_path}")

    with h5py.File(stack_path, "a") as f:
        unw_ds = f["unwrapPhase"]
        coh_ds = f["coherence"]
        conn_ds = f["connectComponent"]
        num_ifg, num_row, _ = unw_ds.shape
        ref_y = int(f.attrs["REF_Y"]) if "REF_Y" in f.attrs else None
        ref_x = int(f.attrs["REF_X"]) if "REF_X" in f.attrs else None
        ref_values = None
        if ref_y is not None and ref_x is not None:
            ref_values = unw_ds[:, ref_y, ref_x].astype(np.float32)
            print(f"Applying reference-aware mask using REF_Y/X = ({ref_y}, {ref_x})")

        common_mask = np.ones((num_row, unw_ds.shape[2]), dtype=bool)
        for row0 in range(0, num_row, args.row_chunk):
            row1 = min(row0 + args.row_chunk, num_row)
            unw = unw_ds[:, row0:row1, :].astype(np.float32)
            coh = coh_ds[:, row0:row1, :]
            conn = conn_ds[:, row0:row1, :]
            if ref_values is not None:
                unw_rel = unw - ref_values[:, None, None]
            else:
                unw_rel = unw
            valid = np.isfinite(unw)
            valid &= np.isfinite(coh)
            valid &= np.isfinite(conn)
            valid &= unw != 0.0
            valid &= unw_rel != 0.0
            valid &= conn > 0
            valid &= coh >= args.coherence_threshold
            # Require pixel valid in at least half of pairs (not all)
            common_mask[row0:row1, :] = np.sum(valid, axis=0) >= max(1, num_ifg // 2)

        if ref_y is not None and ref_x is not None:
            common_mask[ref_y, ref_x] = True

        valid_pixels = int(common_mask.sum())
        total_pixels = int(common_mask.size)
        print(
            f"Applying common mask: keep {valid_pixels} / {total_pixels} pixels "
            f"({100.0 * valid_pixels / total_pixels:.1f}%)"
        )

        for row0 in range(0, num_row, args.row_chunk):
            row1 = min(row0 + args.row_chunk, num_row)
            mask = common_mask[row0:row1, :]
            mask3 = np.broadcast_to(mask, (num_ifg, row1 - row0, unw_ds.shape[2]))

            unw = unw_ds[:, row0:row1, :]
            coh = coh_ds[:, row0:row1, :]
            conn = conn_ds[:, row0:row1, :]

            unw_ds[:, row0:row1, :] = np.where(mask3, unw, 0.0).astype(np.float32)
            coh_ds[:, row0:row1, :] = np.where(mask3, coh, 0.0).astype(np.float32)
            conn_ds[:, row0:row1, :] = np.where(mask3, conn, 0.0).astype(np.float32)

    print(f"Updated {stack_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
