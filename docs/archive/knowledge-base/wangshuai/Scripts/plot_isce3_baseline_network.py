#!/usr/bin/env python3
"""Plot spatiotemporal baseline network from ISCE3 GUNW products."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import h5py
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np


PAIR_DATASET = "science/LSAR/GUNW/metadata/radarGrid/perpendicularBaseline"


@dataclass(frozen=True)
class PairBaseline:
    date1: str
    date2: str
    mean_bperp_m: float
    temporal_baseline_days: int
    product: Path


def read_pairs(pair_list: Path) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for raw_line in pair_list.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        d1, d2 = line.split("_")
        pairs.append((d1, d2))
    if not pairs:
        raise ValueError(f"No pairs found in {pair_list}")
    return pairs


def read_pair_baseline(network_dir: Path, date1: str, date2: str) -> PairBaseline:
    product = network_dir / "runs" / f"{date1}_{date2}" / "products" / f"{date1}_{date2}.h5"
    if not product.exists():
        raise FileNotFoundError(f"Missing GUNW product for {date1}_{date2}: {product}")

    with h5py.File(product, "r") as ds:
        bperp = ds[PAIR_DATASET][()]
    mean_bperp = float(np.nanmean(bperp))
    tbase_days = (datetime.strptime(date2, "%Y%m%d") - datetime.strptime(date1, "%Y%m%d")).days
    return PairBaseline(
        date1=date1,
        date2=date2,
        mean_bperp_m=mean_bperp,
        temporal_baseline_days=tbase_days,
        product=product.resolve(),
    )


def solve_scene_baselines(pair_data: list[PairBaseline]) -> dict[str, float]:
    dates = sorted({x.date1 for x in pair_data} | {x.date2 for x in pair_data})
    date_to_idx = {date: i for i, date in enumerate(dates)}

    rows: list[list[float]] = []
    targets: list[float] = []

    for item in pair_data:
        row = [0.0] * len(dates)
        row[date_to_idx[item.date1]] = -1.0
        row[date_to_idx[item.date2]] = 1.0
        rows.append(row)
        targets.append(item.mean_bperp_m)

    ref_row = [0.0] * len(dates)
    ref_row[0] = 1.0
    rows.append(ref_row)
    targets.append(0.0)

    solution, *_ = np.linalg.lstsq(np.asarray(rows), np.asarray(targets), rcond=None)
    return {date: float(solution[idx]) for date, idx in date_to_idx.items()}


def write_csvs(
    pair_dir: Path, pair_data: list[PairBaseline], scene_baselines: dict[str, float]
) -> None:
    pair_csv = pair_dir / "pair_baselines.csv"
    with pair_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "date1",
                "date2",
                "date12",
                "temporal_baseline_days",
                "mean_perpendicular_baseline_m",
                "product",
            ]
        )
        for item in pair_data:
            writer.writerow(
                [
                    item.date1,
                    item.date2,
                    f"{item.date1}_{item.date2}",
                    item.temporal_baseline_days,
                    f"{item.mean_bperp_m:.6f}",
                    str(item.product),
                ]
            )

    scene_csv = pair_dir / "scene_baselines.csv"
    with scene_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["date", "estimated_perpendicular_baseline_m"])
        for date in sorted(scene_baselines):
            writer.writerow([date, f"{scene_baselines[date]:.6f}"])


def plot_network(
    pair_dir: Path,
    pair_data: list[PairBaseline],
    scene_baselines: dict[str, float],
    title: str,
) -> None:
    fig, ax = plt.subplots(figsize=(10, 6))
    fig.patch.set_facecolor("white")

    dates = {date: datetime.strptime(date, "%Y%m%d") for date in scene_baselines}
    for item in pair_data:
        x = [dates[item.date1], dates[item.date2]]
        y = [scene_baselines[item.date1], scene_baselines[item.date2]]
        ax.plot(x, y, color="#4666a8", linewidth=1.4, alpha=0.7, zorder=1)

    sorted_dates = sorted(scene_baselines)
    x_nodes = [dates[date] for date in sorted_dates]
    y_nodes = [scene_baselines[date] for date in sorted_dates]
    ax.scatter(
        x_nodes,
        y_nodes,
        s=60,
        color="#c83e4d",
        edgecolor="white",
        linewidth=0.8,
        zorder=2,
    )

    for date in sorted_dates:
        ax.annotate(
            date,
            (dates[date], scene_baselines[date]),
            xytext=(0, 8),
            textcoords="offset points",
            ha="center",
            fontsize=8,
        )

    ax.set_title(title)
    ax.set_xlabel("Acquisition date")
    ax.set_ylabel("Estimated perpendicular baseline (m)")
    ax.grid(True, linestyle="--", linewidth=0.6, alpha=0.35)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    fig.autofmt_xdate(rotation=30, ha="right")
    fig.tight_layout()

    png_path = pair_dir / "baseline_network.png"
    pdf_path = pair_dir / "baseline_network.pdf"
    fig.savefig(png_path, dpi=180)
    fig.savefig(pdf_path)
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot a spatiotemporal baseline network from ISCE3 GUNW products."
    )
    parser.add_argument(
        "--network-dir",
        required=True,
        help="Network output directory, e.g. work/isce3_conn3",
    )
    parser.add_argument(
        "--pair-list",
        default=None,
        help="Optional pair list file; defaults to pair_lists/pairs_selected.txt",
    )
    parser.add_argument(
        "--title",
        default="ISCE3 Spatiotemporal Baseline Network",
        help="Figure title",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    network_dir = Path(args.network_dir).resolve()
    pair_dir = network_dir / "pair_lists"
    pair_list = Path(args.pair_list).resolve() if args.pair_list else pair_dir / "pairs_selected.txt"

    if not network_dir.exists():
        raise FileNotFoundError(f"Network directory not found: {network_dir}")
    if not pair_list.exists():
        raise FileNotFoundError(f"Pair list not found: {pair_list}")

    pair_data = [read_pair_baseline(network_dir, d1, d2) for d1, d2 in read_pairs(pair_list)]
    scene_baselines = solve_scene_baselines(pair_data)
    write_csvs(pair_dir, pair_data, scene_baselines)
    plot_network(pair_dir, pair_data, scene_baselines, args.title)
    print(f"Wrote baseline plot to {pair_dir / 'baseline_network.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
