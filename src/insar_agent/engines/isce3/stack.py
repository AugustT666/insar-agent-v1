"""Single-reference ISCE3 stack preparation.

Normalized from wangshuai/Scripts/prepare_isce3_stack.py.
Provides importable library functions used by both the MCP tool layer
and the network module.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from insar_agent.engines.isce3.defaults import get_default_runconfig_template_path


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
    pattern = re.compile(rf"(?m)^(?P<prefix>[ \t]*{re.escape(key)}):[ \t]*.*$")
    if not pattern.search(text):
        raise ValueError(f"Key '{key}' not found in template runconfig")
    return pattern.sub(rf"\g<prefix>: {value}", text, count=1)


def ensure_logging_group(text: str) -> str:
    """Inject a minimal logging group when the template omits one."""
    if re.search(r"(?m)^\s*logging:\s*$", text):
        return text
    return re.sub(
        r"(?m)^(?P<indent>\s*)groups:\s*$",
        (
            r"\g<indent>groups:\n"
            r"\g<indent>    logging:\n"
            r"\g<indent>        path:\n"
            r"\g<indent>        write_mode: w"
        ),
        text,
        count=1,
    )


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


def validate_reference_scene(reference_scene: Scene, scenes: list[Scene]) -> None:
    earlier_dates = [scene.date for scene in scenes if scene.date < reference_scene.date]
    if not earlier_dates:
        return
    earlier_str = ", ".join(earlier_dates)
    raise ValueError(
        "Selected reference scene would create negative temporal baselines for "
        f"earlier acquisitions: {earlier_str}. Use the earliest acquisition as "
        "--reference, or exclude earlier scenes."
    )


def render_runconfig(
    template_text: str,
    reference_scene: Scene,
    secondary_scene: Scene,
    dem_path: Path,
    pair_dir: Path,
    logs_dir: Path | None = None,
) -> str:
    pair_name = f"{reference_scene.date}_{secondary_scene.date}"
    product_dir = pair_dir / "products"
    product_file = product_dir / f"{pair_name}.h5"
    scratch_dir = pair_dir / "scratch"
    qa_dir = pair_dir / "qa"
    log_root = logs_dir or (pair_dir.parent.parent / "logs")
    log_path = log_root / f"{pair_dir.parent.parent.name}_{pair_name}.log"

    rendered = ensure_logging_group(template_text)
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
        'PY_BIN="${PYTHON_BIN:-python}"',
        "",
        'cmd=("${PYTHON_BIN:-python}" "-m" "nisar.workflows.insar")',
        'if [ "$#" -gt 0 ]; then',
        '  cmd=("$@")',
        "fi",
        "",
        "is_valid_product() {",
        '  local f="$1"',
        '  [ -n "$f" ] && [ -s "$f" ] || return 1',
        '  "$PY_BIN" -c "import sys,h5py; f=h5py.File(sys.argv[1],\'r\'); n=len(f.keys()); f.close(); sys.exit(0 if n>0 else 1)" "$f" >/dev/null 2>&1',
        "}",
        "",
        'echo "Using command: ${cmd[*]}"',
        "",
    ]
    for config in runconfigs:
        lines.extend(
            [
                f'cfg="$SCRIPT_DIR/runconfigs/{config.name}"',
                'out_file="$(sed -n \'s/^\\s*sas_output_file:\\s*//p\' "$cfg" | head -n 1)"',
                'if is_valid_product "$out_file"; then',
                f'  echo "SKIP {config.name} -> $out_file"',
                "else",
                f'  echo "Running {config.name}"',
                '  "${cmd[@]}" "$cfg"',
                "fi",
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
        "is_valid_product() {",
        '  local f="$1"',
        '  [ -n "$f" ] && [ -s "$f" ] || return 1',
        '  "$PY_BIN" -c "import sys,h5py; f=h5py.File(sys.argv[1],\'r\'); n=len(f.keys()); f.close(); sys.exit(0 if n>0 else 1)" "$f" >/dev/null 2>&1',
        "}",
        "",
        "run_one() {",
        '  local cfg="$1"',
        "  local out_file",
        '  out_file="$(sed -n \'s/^\\s*sas_output_file:\\s*//p\' "$cfg" | head -n 1)"',
        '  if is_valid_product "$out_file"; then',
        '    echo "SKIP $(basename "$cfg") -> $out_file"',
        "    return 0",
        "  fi",
        '  echo "RUN  $(basename "$cfg")"',
        '  "$PY_BIN" -m nisar.workflows.insar --no-log-file "$cfg"',
        "}",
        "",
        "fail=0",
        'for cfg in "$STACK_DIR"/runconfigs/*.yaml; do',
        '  while [ "$(jobs -pr | wc -l)" -ge "$MAX_JOBS" ]; do',
        "    if ! wait -n; then",
        "      fail=1",
        "    fi",
        "  done",
        '  run_one "$cfg" &',
        "done",
        "",
        '  while [ "$(jobs -pr | wc -l)" -gt 0 ]; do',
        "  if ! wait -n; then",
        "    fail=1",
        "  fi",
        "done",
        "",
        'exit "$fail"',
    ]
    runner.write_text("\n".join(lines) + "\n", encoding="utf-8")
    runner.chmod(0o755)


def prepare_stack(
    data_dir: str | Path,
    base_runconfig: str | Path | None = None,
    *,
    dem: str | Path,
    output_dir: str | Path,
    reference: str = "auto",
) -> dict:
    """Generate single-reference ISCE3 stack runconfigs.

    Args:
        data_dir: Directory containing RSLC .h5 files.
        base_runconfig: Template ISCE3 runconfig YAML path. If omitted, use the
            built-in default `insar` template.
        dem: DEM file path to inject into each runconfig.
        output_dir: Directory where runconfigs and runner scripts are written.
        reference: 'auto' (earliest date), a YYYYMMDD string, or an RSLC path.

    Returns:
        dict with reference_date, num_pairs, output_dir, runconfigs list,
        run_all_sh, run_parallel_sh, manifest_csv.

    Raises:
        FileNotFoundError: If any required input path is missing.
        ValueError: If reference selection or scene discovery fails.
    """
    data_dir = Path(data_dir)
    base_runconfig_source = "default_template" if base_runconfig in (None, "") else "user_provided"
    base_runconfig = (
        get_default_runconfig_template_path("insar")
        if base_runconfig_source == "default_template"
        else Path(base_runconfig)
    )
    dem_path = Path(dem)
    output_dir = Path(output_dir)

    if not base_runconfig.exists():
        raise FileNotFoundError(f"Template runconfig not found: {base_runconfig}")
    if not data_dir.exists():
        raise FileNotFoundError(f"RSLC directory not found: {data_dir}")
    if not dem_path.exists():
        raise FileNotFoundError(f"DEM not found: {dem_path}")

    template_text = read_text(base_runconfig)
    scenes = discover_scenes(data_dir)
    reference_scene = resolve_reference(reference, scenes)
    validate_reference_scene(reference_scene, scenes)

    output_dir.mkdir(parents=True, exist_ok=True)
    runconfig_dir = output_dir / "runconfigs"
    runconfig_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = output_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    manifest_rows: list[list[str]] = []
    generated_runconfigs: list[Path] = []

    for secondary_scene in scenes:
        if secondary_scene.date == reference_scene.date:
            continue
        pair_name = f"{reference_scene.date}_{secondary_scene.date}"
        pair_dir = output_dir / "runs" / pair_name
        for subdir in ("products", "scratch", "qa"):
            (pair_dir / subdir).mkdir(parents=True, exist_ok=True)

        runconfig_path = runconfig_dir / f"{pair_name}.yaml"
        rendered = render_runconfig(
            template_text=template_text,
            reference_scene=reference_scene,
            secondary_scene=secondary_scene,
            dem_path=dem_path,
            pair_dir=pair_dir,
            logs_dir=logs_dir,
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

    manifest_path = output_dir / "stack_manifest.csv"
    with manifest_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            ["reference_date", "secondary_date", "reference_rslc",
             "secondary_rslc", "runconfig", "run_dir"]
        )
        writer.writerows(manifest_rows)

    return {
        "reference_date": reference_scene.date,
        "num_pairs": len(generated_runconfigs),
        "base_runconfig": str(base_runconfig.resolve()),
        "base_runconfig_source": base_runconfig_source,
        "output_dir": str(output_dir.resolve()),
        "runconfigs": [str(p) for p in generated_runconfigs],
        "run_all_sh": str(output_dir / "run_all.sh"),
        "run_parallel_sh": str(output_dir / "run_parallel.sh"),
        "manifest_csv": str(manifest_path),
    }
