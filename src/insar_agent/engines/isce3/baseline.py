"""ISCE3 spatiotemporal baseline network computation and visualisation.

Normalised from knowledge-base/wangshuai/Scripts/plot_isce3_baseline_network.py.
Provides importable library functions used by the MCP tool layer.

Runtime dependencies: h5py, matplotlib, numpy — only available inside the
isce3 conda environment.  Import errors are surfaced as RuntimeError so the
MCP tool can return a meaningful error code.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


# HDF5 dataset path for perpendicular baseline inside GUNW products
_BPERP_DATASET = "science/LSAR/GUNW/metadata/radarGrid/perpendicularBaseline"


@dataclass(frozen=True)
class PairBaseline:
    date1: str
    date2: str
    mean_bperp_m: float
    temporal_baseline_days: int
    product: Path


def read_pairs(pair_list: Path) -> list[tuple[str, str]]:
    """Parse a pair-list text file.

    Each non-comment line must be ``YYYYMMDD_YYYYMMDD``.
    """
    pairs: list[tuple[str, str]] = []
    for raw in pair_list.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        d1, d2 = line.split("_")
        pairs.append((d1, d2))
    if not pairs:
        raise ValueError(f"No pairs found in {pair_list}")
    return pairs


def read_pair_baseline(network_dir: Path, date1: str, date2: str) -> PairBaseline:
    """Read mean perpendicular baseline for one interferogram pair.

    Expects the GUNW product at::

        <network_dir>/runs/<date1>_<date2>/products/<date1>_<date2>.h5
    """
    try:
        import h5py
        import numpy as np
    except ImportError as exc:
        raise RuntimeError(
            f"Baseline reading requires h5py and numpy: {exc}. "
            "Run inside the isce3 conda environment."
        ) from exc

    product = (
        network_dir / "runs" / f"{date1}_{date2}" / "products" / f"{date1}_{date2}.h5"
    )
    if not product.exists():
        raise FileNotFoundError(f"GUNW product not found: {product}")

    with h5py.File(product, "r") as ds:
        bperp = ds[_BPERP_DATASET][()]
    mean_bperp = float(np.nanmean(bperp))
    tbase = (
        datetime.strptime(date2, "%Y%m%d") - datetime.strptime(date1, "%Y%m%d")
    ).days
    return PairBaseline(
        date1=date1,
        date2=date2,
        mean_bperp_m=mean_bperp,
        temporal_baseline_days=tbase,
        product=product.resolve(),
    )


def solve_scene_baselines(pair_data: list[PairBaseline]) -> dict[str, float]:
    """Estimate per-scene perpendicular baseline via least-squares.

    The first scene is held at zero (reference).
    """
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError(f"Requires numpy: {exc}") from exc

    dates = sorted({x.date1 for x in pair_data} | {x.date2 for x in pair_data})
    idx = {d: i for i, d in enumerate(dates)}

    rows: list[list[float]] = []
    targets: list[float] = []
    for item in pair_data:
        row = [0.0] * len(dates)
        row[idx[item.date1]] = -1.0
        row[idx[item.date2]] = 1.0
        rows.append(row)
        targets.append(item.mean_bperp_m)

    # pin reference scene to zero
    ref_row = [0.0] * len(dates)
    ref_row[0] = 1.0
    rows.append(ref_row)
    targets.append(0.0)

    solution, *_ = np.linalg.lstsq(
        np.asarray(rows), np.asarray(targets), rcond=None
    )
    return {d: float(solution[idx[d]]) for d in dates}


def write_csvs(
    pair_dir: Path,
    pair_data: list[PairBaseline],
    scene_baselines: dict[str, float],
) -> tuple[str, str]:
    """Write pair_baselines.csv and scene_baselines.csv to *pair_dir*.

    Returns (pair_csv_path, scene_csv_path).
    """
    pair_dir.mkdir(parents=True, exist_ok=True)

    pair_csv = pair_dir / "pair_baselines.csv"
    with pair_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "date1", "date2", "date12",
            "temporal_baseline_days", "mean_perpendicular_baseline_m", "product",
        ])
        for item in pair_data:
            writer.writerow([
                item.date1, item.date2, f"{item.date1}_{item.date2}",
                item.temporal_baseline_days,
                f"{item.mean_bperp_m:.6f}",
                str(item.product),
            ])

    scene_csv = pair_dir / "scene_baselines.csv"
    with scene_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["date", "estimated_perpendicular_baseline_m"])
        for date in sorted(scene_baselines):
            writer.writerow([date, f"{scene_baselines[date]:.6f}"])

    return str(pair_csv), str(scene_csv)


def plot_network(
    pair_dir: Path,
    pair_data: list[PairBaseline],
    scene_baselines: dict[str, float],
    title: str,
) -> tuple[str, str]:
    """Render the spatiotemporal baseline network and save PNG + PDF.

    Returns (png_path, pdf_path).
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError(
            f"Baseline plotting requires matplotlib: {exc}. "
            "Run inside the isce3 conda environment."
        ) from exc

    fig, ax = plt.subplots(figsize=(10, 6))
    fig.patch.set_facecolor("white")

    dates = {d: datetime.strptime(d, "%Y%m%d") for d in scene_baselines}
    for item in pair_data:
        x = [dates[item.date1], dates[item.date2]]
        y = [scene_baselines[item.date1], scene_baselines[item.date2]]
        ax.plot(x, y, color="#4666a8", linewidth=1.4, alpha=0.7, zorder=1)

    sorted_dates = sorted(scene_baselines)
    x_nodes = [dates[d] for d in sorted_dates]
    y_nodes = [scene_baselines[d] for d in sorted_dates]
    ax.scatter(x_nodes, y_nodes, s=60, color="#c83e4d",
               edgecolor="white", linewidth=0.8, zorder=2)

    for d in sorted_dates:
        ax.annotate(d, (dates[d], scene_baselines[d]),
                    xytext=(0, 8), textcoords="offset points",
                    ha="center", fontsize=8)

    ax.set_title(title)
    ax.set_xlabel("Acquisition date")
    ax.set_ylabel("Estimated perpendicular baseline (m)")
    ax.grid(True, linestyle="--", linewidth=0.6, alpha=0.35)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
    fig.autofmt_xdate(rotation=30, ha="right")
    fig.tight_layout()

    png_path = str(pair_dir / "baseline_network.png")
    pdf_path = str(pair_dir / "baseline_network.pdf")
    fig.savefig(png_path, dpi=180)
    fig.savefig(pdf_path)
    plt.close(fig)

    return png_path, pdf_path


def plot_baseline_network(
    network_dir: str | Path,
    pair_list: str | Path | None = None,
    title: str = "ISCE3 Spatiotemporal Baseline Network",
) -> dict[str, object]:
    """Generate baseline network plot and CSV files.

    Reads GUNW products from the interferogram network directory produced by
    :func:`insar_agent.engines.isce3.network.prepare_network`.

    Args:
        network_dir: Network output directory containing ``runs/`` and
                     ``pair_lists/``.
        pair_list:   Path to a pair-list text file (``YYYYMMDD_YYYYMMDD`` per
                     line).  Defaults to
                     ``<network_dir>/pair_lists/pairs_selected.txt``.
        title:       Figure title string.

    Returns:
        dict with keys: png_path, pdf_path, pair_csv, scene_csv, n_pairs
    """
    network_dir = Path(network_dir).resolve()
    if not network_dir.exists():
        raise FileNotFoundError(f"Network directory not found: {network_dir}")

    pair_dir = network_dir / "pair_lists"
    if pair_list is None:
        pair_list_path = pair_dir / "pairs_selected.txt"
    else:
        pair_list_path = Path(pair_list).resolve()

    if not pair_list_path.exists():
        raise FileNotFoundError(f"Pair list not found: {pair_list_path}")

    pairs = read_pairs(pair_list_path)
    pair_data = [read_pair_baseline(network_dir, d1, d2) for d1, d2 in pairs]
    scene_baselines = solve_scene_baselines(pair_data)
    pair_csv, scene_csv = write_csvs(pair_dir, pair_data, scene_baselines)
    png_path, pdf_path = plot_network(pair_dir, pair_data, scene_baselines, title)

    return {
        "png_path": png_path,
        "pdf_path": pdf_path,
        "pair_csv": pair_csv,
        "scene_csv": scene_csv,
        "n_pairs": len(pair_data),
    }
