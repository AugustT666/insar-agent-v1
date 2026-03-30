#!/usr/bin/env python3
"""Prepare ISCE3 runconfigs for an arbitrary interferogram network."""

from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import datetime
from pathlib import Path

from scripts.prepare_isce3_stack import (
    Scene,
    discover_scenes,
    read_text,
    render_runconfig,
    write_parallel_runner,
    write_runner,
)


PAIR_RE = re.compile(r"^(?P<d1>\d{8})_(?P<d2>\d{8})$")
DEFAULT_NETWORK_MODE = "tbase"
DEFAULT_CONNECTION_SPAN = 3
DEFAULT_MAX_TEMPORAL_BASELINE_DAYS = 36


def temporal_baseline_days(date1: str, date2: str) -> int:
    return (datetime.strptime(date2, "%Y%m%d") - datetime.strptime(date1, "%Y%m%d")).days


def build_forward_neighbor_pairs(
    dates: list[str], forward_links: int
) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for i in range(len(dates)):
        for j in range(i + 1, min(i + 1 + forward_links, len(dates))):
            pairs.append((dates[i], dates[j]))
    return pairs


def build_temporal_threshold_pairs(
    dates: list[str], max_temporal_baseline_days: int
) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for i in range(len(dates)):
        for j in range(i + 1, len(dates)):
            if temporal_baseline_days(dates[i], dates[j]) <= max_temporal_baseline_days:
                pairs.append((dates[i], dates[j]))
    return pairs


def resolve_network_definition(
    dates: list[str],
    network_mode: str,
    connection_span: int,
    max_temporal_baseline_days: int,
) -> tuple[str, list[tuple[str, str]], str]:
    if network_mode == "tbase":
        if max_temporal_baseline_days < 1:
            raise ValueError("--max-temporal-baseline-days must be >= 1")
        pair_label = f"pairs_tbase{max_temporal_baseline_days}d"
        pairs = build_temporal_threshold_pairs(dates, max_temporal_baseline_days)
        description = (
            f"Connect acquisitions with temporal baseline <= {max_temporal_baseline_days} days"
        )
        return pair_label, pairs, description

    if network_mode == "conn":
        if connection_span < 1:
            raise ValueError("--connection-span must be >= 1")
        pair_label = f"pairs_conn{connection_span}"
        pairs = build_forward_neighbor_pairs(dates, connection_span)
        description = f"Connect each date to the next {connection_span} acquisitions"
        return pair_label, pairs, description

    raise ValueError(f"Unsupported --network-mode: {network_mode}")


def load_pair_strings(pair_list_path: Path) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for raw_line in pair_list_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = PAIR_RE.fullmatch(line)
        if not match:
            raise ValueError(f"Invalid pair format in {pair_list_path}: {line}")
        d1 = match.group("d1")
        d2 = match.group("d2")
        if d1 >= d2:
            raise ValueError(f"Pairs must be ascending to avoid negative baselines: {line}")
        pairs.append((d1, d2))
    if not pairs:
        raise ValueError(f"No valid pairs found in {pair_list_path}")
    return pairs


def resolve_pairs(
    scenes: list[Scene],
    pair_list_path: Path | None,
    network_mode: str,
    connection_span: int,
    max_temporal_baseline_days: int,
) -> list[tuple[Scene, Scene]]:
    by_date = {scene.date: scene for scene in scenes}
    if pair_list_path:
        raw_pairs = load_pair_strings(pair_list_path)
    else:
        _, raw_pairs, _ = resolve_network_definition(
            [scene.date for scene in scenes],
            network_mode,
            connection_span,
            max_temporal_baseline_days,
        )

    resolved: list[tuple[Scene, Scene]] = []
    seen: set[tuple[str, str]] = set()
    for d1, d2 in raw_pairs:
        if d1 not in by_date or d2 not in by_date:
            raise ValueError(f"Pair {d1}_{d2} references a date not present in data/rslc")
        key = (d1, d2)
        if key in seen:
            continue
        resolved.append((by_date[d1], by_date[d2]))
        seen.add(key)
    return resolved


def write_network_metadata(
    output_dir: Path, pair_scenes: list[tuple[Scene, Scene]], pair_label: str
) -> None:
    pair_dir = output_dir / "pair_lists"
    pair_dir.mkdir(parents=True, exist_ok=True)

    text = "\n".join(f"{ref.date}_{sec.date}" for ref, sec in pair_scenes)
    if text:
        text += "\n"
    (pair_dir / "pairs_selected.txt").write_text(text, encoding="utf-8")
    (pair_dir / f"{pair_label}.txt").write_text(text, encoding="utf-8")

    manifest_path = pair_dir / "pairs_selected.csv"
    with manifest_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "date1",
                "date2",
                "date12",
                "reference_rslc",
                "secondary_rslc",
            ]
        )
        for ref_scene, sec_scene in pair_scenes:
            writer.writerow(
                [
                    ref_scene.date,
                    sec_scene.date,
                    f"{ref_scene.date}_{sec_scene.date}",
                    str(ref_scene.path),
                    str(sec_scene.path),
                ]
            )


def write_summary(
    output_dir: Path, pair_label: str, network_description: str, num_pairs: int
) -> None:
    summary = output_dir / "README.txt"
    lines = [
        "ISCE3 interferogram network prepared from local RSLC files.",
        "",
        f"Network label: {pair_label}",
        f"Network rule: {network_description}",
        f"Number of pairs: {num_pairs}",
        "",
        "Key outputs:",
        "  runconfigs/                Per-pair ISCE3 runconfigs",
        "  run_all.sh                 Sequential batch launcher",
        "  run_parallel.sh            Parallel batch launcher",
        f"  pair_lists/{pair_label}.txt        Pair list used for this network",
        "  pair_lists/pairs_selected.csv      Pair/date-to-RSLC manifest",
    ]
    summary.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate ISCE3 runconfigs for a downstream interferogram network."
    )
    parser.add_argument(
        "--base-runconfig",
        default="insar_nisar.yaml",
        help="Template ISCE3 runconfig",
    )
    parser.add_argument(
        "--data-dir",
        default="data/rslc",
        help="Directory containing RSLC .h5 files",
    )
    parser.add_argument(
        "--dem",
        default="data/dem/dem.tif",
        help="DEM path to inject into generated runconfigs",
    )
    parser.add_argument(
        "--output-dir",
        default="work/isce3_network",
        help="Output directory for generated network configs and manifests",
    )
    parser.add_argument(
        "--pair-list",
        default=None,
        help="Optional file with YYYYMMDD_YYYYMMDD pairs, one per line",
    )
    parser.add_argument(
        "--network-mode",
        choices=("tbase", "conn"),
        default=DEFAULT_NETWORK_MODE,
        help="If --pair-list is not given, tbase uses a temporal baseline threshold and conn connects each date to the next N dates",
    )
    parser.add_argument(
        "--connection-span",
        type=int,
        default=DEFAULT_CONNECTION_SPAN,
        help="If --pair-list is not given in conn mode, connect each acquisition to this many later acquisitions",
    )
    parser.add_argument(
        "--max-temporal-baseline-days",
        type=int,
        default=DEFAULT_MAX_TEMPORAL_BASELINE_DAYS,
        help="If --pair-list is not given in tbase mode, include pairs with temporal baseline <= this many days",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    repo_root = Path.cwd()
    base_runconfig = (repo_root / args.base_runconfig).resolve()
    data_dir = (repo_root / args.data_dir).resolve()
    dem_path = (repo_root / args.dem).resolve()
    output_dir = (repo_root / args.output_dir).resolve()
    pair_list_path = None
    if args.pair_list:
        pair_list_path = (repo_root / args.pair_list).resolve()

    if not base_runconfig.exists():
        raise FileNotFoundError(f"Template runconfig not found: {base_runconfig}")
    if not data_dir.exists():
        raise FileNotFoundError(f"RSLC directory not found: {data_dir}")
    if not dem_path.exists():
        raise FileNotFoundError(f"DEM not found: {dem_path}")
    if pair_list_path and not pair_list_path.exists():
        raise FileNotFoundError(f"Pair list not found: {pair_list_path}")
    if args.connection_span < 1:
        raise ValueError("--connection-span must be >= 1")
    if args.max_temporal_baseline_days < 1:
        raise ValueError("--max-temporal-baseline-days must be >= 1")

    template_text = read_text(base_runconfig)
    scenes = discover_scenes(data_dir)
    pair_scenes = resolve_pairs(
        scenes,
        pair_list_path,
        args.network_mode,
        args.connection_span,
        args.max_temporal_baseline_days,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    runconfig_dir = output_dir / "runconfigs"
    runconfig_dir.mkdir(parents=True, exist_ok=True)

    manifest_rows: list[list[str]] = []
    generated_runconfigs: list[Path] = []

    for reference_scene, secondary_scene in pair_scenes:
        pair_name = f"{reference_scene.date}_{secondary_scene.date}"
        pair_dir = output_dir / "runs" / pair_name
        for subdir in ("products", "scratch", "qa", "logs"):
            (pair_dir / subdir).mkdir(parents=True, exist_ok=True)

        runconfig_path = runconfig_dir / f"{pair_name}.yaml"
        rendered = render_runconfig(
            template_text=template_text,
            reference_scene=reference_scene,
            secondary_scene=secondary_scene,
            dem_path=dem_path,
            pair_dir=pair_dir,
        )
        runconfig_path.write_text(rendered, encoding="utf-8")
        generated_runconfigs.append(runconfig_path)
        manifest_rows.append(
            [
                reference_scene.date,
                secondary_scene.date,
                str(reference_scene.path),
                str(secondary_scene.path),
                str(runconfig_path.resolve()),
                str(pair_dir.resolve()),
            ]
        )

    write_runner(output_dir, generated_runconfigs)
    write_parallel_runner(output_dir)

    if pair_list_path:
        pair_label = pair_list_path.stem
        network_description = "User-supplied pair list"
    else:
        pair_label, _, network_description = resolve_network_definition(
            [scene.date for scene in scenes],
            args.network_mode,
            args.connection_span,
            args.max_temporal_baseline_days,
        )
    write_network_metadata(output_dir, pair_scenes, pair_label)
    write_summary(output_dir, pair_label, network_description, len(generated_runconfigs))

    manifest_path = output_dir / "stack_manifest.csv"
    with manifest_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "reference_date",
                "secondary_date",
                "reference_rslc",
                "secondary_rslc",
                "runconfig",
                "run_dir",
            ]
        )
        writer.writerows(manifest_rows)

    print(f"Generated {len(generated_runconfigs)} runconfigs in {runconfig_dir}")
    print(f"Network pair list: {output_dir / 'pair_lists' / (pair_label + '.txt')}")
    print(f"Batch runner: {output_dir / 'run_parallel.sh'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
