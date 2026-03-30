#!/usr/bin/env python3
"""Prepare a single-reference ISCE3 stack."""

from __future__ import annotations

import argparse
import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path


DATE_RE = re.compile(r"_(\d{8})T\d{6}_")


@dataclass(frozen=True)
class Scene:
    date: str
    path: Path


def extract_date(text: str) -> str | None:
    match = DATE_RE.search(text)
    return match.group(1) if match else None


def discover_scenes(data_dir: Path) -> list[Scene]:
    scenes: list[Scene] = []
    seen_dates: set[str] = set()
    for path in sorted(data_dir.glob("*.h5")):
        date = extract_date(path.name)
        if not date:
            continue
        if date in seen_dates:
            raise ValueError(f"Duplicate acquisition date {date} in {data_dir}")
        scenes.append(Scene(date=date, path=path.resolve()))
        seen_dates.add(date)
    if len(scenes) < 2:
        raise ValueError(f"Need at least 2 RSLC files in {data_dir}")
    return scenes


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def replace_scalar(text: str, key: str, value: str) -> str:
    pattern = re.compile(rf"(?m)^(?P<prefix>\s*{re.escape(key)}:\s*).*$")
    if not pattern.search(text):
        raise ValueError(f"Key '{key}' not found in template runconfig")
    return pattern.sub(rf"\g<prefix>{value}", text, count=1)

def resolve_reference(reference_arg: str, scenes: list[Scene]) -> Scene:
    by_date = {scene.date: scene for scene in scenes}
    by_name = {scene.path.name: scene for scene in scenes}

    if reference_arg == "auto":
        return min(scenes, key=lambda scene: scene.date)

    if reference_arg in by_date:
        return by_date[reference_arg]

    ref_path = Path(reference_arg)
    if ref_path.exists():
        resolved = ref_path.resolve()
        for scene in scenes:
            if scene.path == resolved:
                return scene
    if reference_arg in by_name:
        return by_name[reference_arg]

    raise ValueError(
        f"Reference '{reference_arg}' not found. Use YYYYMMDD or an RSLC path."
    )


def cleanup_legacy_pair_lists(output_dir: Path) -> None:
    pair_dir = output_dir / "pair_lists"
    if not pair_dir.exists():
        return

    patterns = [
        "pairs_all.txt",
        "pairs_sequential.txt",
        "pairs_single_reference.txt",
        "pairs_all.csv",
        "reference_date.txt",
        "pairs_conn*.txt",
        "pairs_tbase*d.txt",
    ]
    for pattern in patterns:
        for path in pair_dir.glob(pattern):
            if path.is_file():
                path.unlink()

    try:
        pair_dir.rmdir()
    except OSError:
        pass


def validate_reference_scene(reference_scene: Scene, scenes: list[Scene]) -> None:
    earlier_dates = [scene.date for scene in scenes if scene.date < reference_scene.date]
    if not earlier_dates:
        return

    earlier_str = ", ".join(earlier_dates)
    raise ValueError(
        "Selected reference scene would create negative temporal baselines for "
        f"earlier acquisitions: {earlier_str}. Current ISCE3 InSAR processing "
        "fails on these pairs. Use the earliest acquisition as --reference, or "
        "exclude earlier scenes before generating the single-reference stack."
    )


def render_runconfig(
    template_text: str,
    reference_scene: Scene,
    secondary_scene: Scene,
    dem_path: Path,
    pair_dir: Path,
) -> str:
    pair_name = f"{reference_scene.date}_{secondary_scene.date}"
    product_dir = pair_dir / "products"
    product_file = product_dir / f"{pair_name}.h5"
    scratch_dir = pair_dir / "scratch"
    qa_dir = pair_dir / "qa"
    log_path = pair_dir / "logs" / "insar_process.log"

    rendered = template_text
    replacements = {
        "path": str(log_path.resolve()),
        "reference_rslc_file": str(reference_scene.path),
        "secondary_rslc_file": str(secondary_scene.path),
        "dem_file": str(dem_path.resolve()),
        "product_path": str(product_dir.resolve()),
        "scratch_path": str(scratch_dir.resolve()),
        "sas_output_file": str(product_file.resolve()),
        "qa_output_dir": str(qa_dir.resolve()),
        "qa_rifg_input_file": f"RIFG_{pair_name}.h5",
        "qa_runw_input_file": f"RUNW_{pair_name}.h5",
        "qa_gunw_input_file": f"GUNW_{pair_name}.h5",
        "qa_roff_input_file": f"ROFF_{pair_name}.h5",
        "qa_goff_input_file": f"GOFF_{pair_name}.h5",
    }
    for key, value in replacements.items():
        rendered = replace_scalar(rendered, key, value)
    return rendered


def write_runner(output_dir: Path, runconfigs: list[Path]) -> None:
    runner = output_dir / "run_all.sh"
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
        'export MPLCONFIGDIR="${MPLCONFIGDIR:-$SCRIPT_DIR/mplconfig}"',
        'mkdir -p "$MPLCONFIGDIR"',
        "",
        'cmd=("${PYTHON_BIN:-python}" "-m" "nisar.workflows.insar")',
        'if [ "$#" -gt 0 ]; then',
        '  cmd=("$@")',
        "fi",
        "",
        'echo "Using command: ${cmd[*]}"',
        "",
    ]
    for config in runconfigs:
        lines.extend(
            [
                f'echo "Running {config.name}"',
                f'"${{cmd[@]}}" "$SCRIPT_DIR/runconfigs/{config.name}"',
                "",
            ]
        )
    runner.write_text("\n".join(lines), encoding="utf-8")
    runner.chmod(0o755)


def write_parallel_runner(output_dir: Path) -> None:
    runner = output_dir / "run_parallel.sh"
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
        'STACK_DIR="${1:-$SCRIPT_DIR}"',
        'MAX_JOBS="${2:-8}"',
        "",
        'export MPLCONFIGDIR="${MPLCONFIGDIR:-$STACK_DIR/mplconfig}"',
        'mkdir -p "$MPLCONFIGDIR"',
        'PY_BIN="${PYTHON_BIN:-python}"',
        "",
        'run_one() {',
        '  local cfg="$1"',
        '  local out_file',
        '  out_file="$(sed -n "s/^\\s*sas_output_file:\\s*//p" "$cfg" | head -n 1)"',
        '  if [ -n "$out_file" ] && [ -s "$out_file" ]; then',
        '    echo "SKIP $(basename "$cfg") -> $out_file"',
        '    return 0',
        '  fi',
        '  echo "RUN  $(basename "$cfg")"',
        '  "$PY_BIN" -m nisar.workflows.insar --no-log-file "$cfg"',
        '}',
        "",
        'fail=0',
        'for cfg in "$STACK_DIR"/runconfigs/*.yaml; do',
        '  while [ "$(jobs -pr | wc -l)" -ge "$MAX_JOBS" ]; do',
        '    if ! wait -n; then',
        '      fail=1',
        '    fi',
        '  done',
        '  run_one "$cfg" &',
        'done',
        "",
        'while [ "$(jobs -pr | wc -l)" -gt 0 ]; do',
        '  if ! wait -n; then',
        '    fail=1',
        '  fi',
        'done',
        "",
        'exit "$fail"',
    ]
    runner.write_text("\n".join(lines) + "\n", encoding="utf-8")
    runner.chmod(0o755)


def write_summary(
    output_dir: Path,
    scenes: list[Scene],
    reference_scene: Scene,
) -> None:
    summary = output_dir / "README.txt"
    lines = [
        "ISCE3 stack prepared from local RSLC files.",
        "",
        f"Reference date: {reference_scene.date}",
        "Acquisition dates:",
    ]
    lines.extend(f"  {scene.date}  {scene.path.name}" for scene in scenes)
    lines.extend(
        [
            "",
            "Key outputs:",
            "  runconfigs/                Per-secondary ISCE3 runconfigs",
            "  run_all.sh                 Batch launcher; pass your isce3 entry command",
            "  run_parallel.sh            Parallel batch launcher",
            "  stack_manifest.csv         Reference/secondary/runconfig manifest",
            "  reference_date.txt         Selected single-reference acquisition date",
        ]
    )
    summary.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate single-reference ISCE3 runconfigs."
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
        default="work/isce3_stack",
        help="Output directory for generated configs and manifests",
    )
    parser.add_argument(
        "--reference",
        default="auto",
        help="Reference scene date YYYYMMDD or an RSLC path; default uses the earliest acquisition",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    repo_root = Path.cwd()
    base_runconfig = (repo_root / args.base_runconfig).resolve()
    data_dir = (repo_root / args.data_dir).resolve()
    dem_path = (repo_root / args.dem).resolve()
    output_dir = (repo_root / args.output_dir).resolve()

    if not base_runconfig.exists():
        raise FileNotFoundError(f"Template runconfig not found: {base_runconfig}")
    if not data_dir.exists():
        raise FileNotFoundError(f"RSLC directory not found: {data_dir}")
    if not dem_path.exists():
        raise FileNotFoundError(f"DEM not found: {dem_path}")

    template_text = read_text(base_runconfig)
    scenes = discover_scenes(data_dir)
    reference_scene = resolve_reference(args.reference, scenes)
    validate_reference_scene(reference_scene, scenes)

    output_dir.mkdir(parents=True, exist_ok=True)
    cleanup_legacy_pair_lists(output_dir)
    runconfig_dir = output_dir / "runconfigs"
    runconfig_dir.mkdir(parents=True, exist_ok=True)

    manifest_rows: list[list[str]] = []
    generated_runconfigs: list[Path] = []

    for secondary_scene in scenes:
        if secondary_scene.date == reference_scene.date:
            continue
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
    (output_dir / "reference_date.txt").write_text(
        f"{reference_scene.date}\n", encoding="utf-8"
    )
    write_summary(output_dir, scenes, reference_scene)

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

    print(f"Reference date: {reference_scene.date}")
    print(f"Generated {len(generated_runconfigs)} runconfigs in {runconfig_dir}")
    print(f"Batch runner: {output_dir / 'run_all.sh'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
