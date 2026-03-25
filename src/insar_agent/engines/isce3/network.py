"""ISCE3 interferogram network preparation.

Normalized from wangshuai/Scripts/prepare_isce3_network.py.
Supports tbase (temporal baseline threshold) and conn (fixed neighbor) network modes.
"""
from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path

from insar_agent.engines.isce3.stack import (
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
    return (
        datetime.strptime(date2, "%Y%m%d") - datetime.strptime(date1, "%Y%m%d")
    ).days


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
            raise ValueError("max_temporal_baseline_days must be >= 1")
        pair_label = f"pairs_tbase{max_temporal_baseline_days}d"
        pairs = build_temporal_threshold_pairs(dates, max_temporal_baseline_days)
        description = (
            f"Connect acquisitions with temporal baseline <= {max_temporal_baseline_days} days"
        )
        return pair_label, pairs, description

    if network_mode == "conn":
        if connection_span < 1:
            raise ValueError("connection_span must be >= 1")
        pair_label = f"pairs_conn{connection_span}"
        pairs = build_forward_neighbor_pairs(dates, connection_span)
        description = f"Connect each date to the next {connection_span} acquisitions"
        return pair_label, pairs, description

    raise ValueError(f"Unsupported network_mode: {network_mode!r}. Use 'tbase' or 'conn'.")


def load_pair_strings(pair_list_path: Path) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for raw_line in pair_list_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = PAIR_RE.fullmatch(line)
        if not match:
            raise ValueError(f"Invalid pair format in {pair_list_path}: {line!r}")
        d1 = match.group("d1")
        d2 = match.group("d2")
        if d1 >= d2:
            raise ValueError(
                f"Pairs must be ascending to avoid negative baselines: {line!r}"
            )
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
            raise ValueError(
                f"Pair {d1}_{d2} references a date not present in the RSLC directory"
            )
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
        writer.writerow(["date1", "date2", "date12", "reference_rslc", "secondary_rslc"])
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


def prepare_network(
    data_dir: str | Path,
    base_runconfig: str | Path,
    dem: str | Path,
    output_dir: str | Path,
    network_mode: str = DEFAULT_NETWORK_MODE,
    max_temporal_baseline_days: int = DEFAULT_MAX_TEMPORAL_BASELINE_DAYS,
    connection_span: int = DEFAULT_CONNECTION_SPAN,
    pair_list: str | Path | None = None,
) -> dict:
    """Generate ISCE3 runconfigs for an interferogram network.

    Args:
        data_dir: Directory containing RSLC .h5 files.
        base_runconfig: Template ISCE3 runconfig YAML path.
        dem: DEM file path to inject into each runconfig.
        output_dir: Directory where runconfigs and runner scripts are written.
        network_mode: 'tbase' (temporal baseline threshold) or 'conn' (fixed neighbors).
        max_temporal_baseline_days: Max temporal baseline in days (tbase mode).
        connection_span: Number of forward neighbors per date (conn mode).
        pair_list: Optional path to a file with YYYYMMDD_YYYYMMDD pairs, one per line.

    Returns:
        dict with num_pairs, output_dir, runconfigs list, run_all_sh,
        run_parallel_sh, pairs_selected_txt, manifest_csv, network_label,
        network_description.

    Raises:
        FileNotFoundError: If any required input path is missing.
        ValueError: If network configuration or pair resolution fails.
    """
    data_dir = Path(data_dir)
    base_runconfig = Path(base_runconfig)
    dem_path = Path(dem)
    output_dir = Path(output_dir)
    pair_list_path = Path(pair_list) if pair_list else None

    if not base_runconfig.exists():
        raise FileNotFoundError(f"Template runconfig not found: {base_runconfig}")
    if not data_dir.exists():
        raise FileNotFoundError(f"RSLC directory not found: {data_dir}")
    if not dem_path.exists():
        raise FileNotFoundError(f"DEM not found: {dem_path}")
    if pair_list_path and not pair_list_path.exists():
        raise FileNotFoundError(f"Pair list not found: {pair_list_path}")

    template_text = read_text(base_runconfig)
    scenes = discover_scenes(data_dir)
    pair_scenes = resolve_pairs(
        scenes,
        pair_list_path,
        network_mode,
        connection_span,
        max_temporal_baseline_days,
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
            network_mode,
            connection_span,
            max_temporal_baseline_days,
        )
    write_network_metadata(output_dir, pair_scenes, pair_label)

    manifest_path = output_dir / "stack_manifest.csv"
    with manifest_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["reference_date", "secondary_date", "reference_rslc",
             "secondary_rslc", "runconfig", "run_dir"]
        )
        writer.writerows(manifest_rows)

    pairs_selected_txt = str(output_dir / "pair_lists" / "pairs_selected.txt")

    return {
        "num_pairs": len(generated_runconfigs),
        "output_dir": str(output_dir.resolve()),
        "runconfigs": [str(p) for p in generated_runconfigs],
        "run_all_sh": str(output_dir / "run_all.sh"),
        "run_parallel_sh": str(output_dir / "run_parallel.sh"),
        "pairs_selected_txt": pairs_selected_txt,
        "manifest_csv": str(manifest_path),
        "network_label": pair_label,
        "network_description": network_description,
    }
