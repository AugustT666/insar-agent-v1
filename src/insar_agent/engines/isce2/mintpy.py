"""MintPy launcher for ISCE2/topsStack Sentinel workflows."""
from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import numpy as np

from insar_agent.core.project import resolve_plugin_logs_dir

_SCRIPT = Path(__file__).parent / "assets" / "run_mintpy_isce2_stack.sh"


def _default_meta_file(stack_work_dir: Path) -> Path:
    matches = sorted((stack_work_dir / "reference").glob("IW*.xml"))
    if not matches:
        raise FileNotFoundError(f"No reference IW*.xml found under {stack_work_dir / 'reference'}")
    return matches[0]


def _read_isce_image_shape(xml_path: Path) -> tuple[int, int]:
    text = xml_path.read_text(encoding="utf-8")
    import re
    width_match = re.search(r"<property name=\"width\">\s*<value>(\d+)</value>", text)
    length_match = re.search(r"<property name=\"length\">\s*<value>(\d+)</value>", text)
    if not width_match or not length_match:
        raise ValueError(f"Could not read width/length from {xml_path}")
    return int(width_match.group(1)), int(length_match.group(1))


def export_mintpy_tops_baselines(stack_work_dir: str | Path) -> Path:
    stack_dir = Path(stack_work_dir)
    baseline_root = stack_dir / "merged" / "baselines"
    output_root = stack_dir / "merged" / "baselines_txt"
    output_root.mkdir(parents=True, exist_ok=True)

    means: dict[str, float] = {}
    for date_dir in sorted(baseline_root.glob("*")):
        raw = date_dir / date_dir.name
        xml = raw.with_suffix(raw.suffix + ".xml")
        if not raw.exists() or not xml.exists():
            continue
        width, length = _read_isce_image_shape(xml)
        arr = np.fromfile(raw, dtype=np.float32).reshape(length, width)
        means[date_dir.name] = float(arr.mean())

    if not means:
        raise FileNotFoundError(f"No baseline rasters found under {baseline_root}")

    reference_date = min(means, key=lambda k: abs(means[k]))
    for date, value in means.items():
        if date == reference_date:
            continue
        pair_dir = output_root / f"{reference_date}_{date}"
        pair_dir.mkdir(parents=True, exist_ok=True)
        txt = pair_dir / f"{reference_date}_{date}.txt"
        txt.write_text(
            f"swath: IW2\nBperp (average): {value}\nBpar (average): 0.0\n",
            encoding="utf-8",
        )

    return output_root


def _default_template_text(stack_work_dir: Path) -> str:
    baseline_dir = export_mintpy_tops_baselines(stack_work_dir)
    return "\n".join(
        [
            "mintpy.load.processor = isce",
            "mintpy.load.autoPath = no",
            f"mintpy.load.metaFile = {(_default_meta_file(stack_work_dir)).as_posix()}",
            f"mintpy.load.baselineDir = {baseline_dir.as_posix()}",
            f"mintpy.load.unwFile = {(stack_work_dir / 'merged' / 'interferograms' / '*' / 'filt_fine.unw').as_posix()}",
            f"mintpy.load.corFile = {(stack_work_dir / 'merged' / 'interferograms' / '*' / 'filt_fine.cor').as_posix()}",
            f"mintpy.load.connCompFile = {(stack_work_dir / 'merged' / 'interferograms' / '*' / 'filt_fine.unw.conncomp').as_posix()}",
            "mintpy.load.intFile = None",
            f"mintpy.load.demFile = {(stack_work_dir / 'merged' / 'geom_reference' / 'hgt.rdr').as_posix()}",
            f"mintpy.load.lookupYFile = {(stack_work_dir / 'merged' / 'geom_reference' / 'lat.rdr').as_posix()}",
            f"mintpy.load.lookupXFile = {(stack_work_dir / 'merged' / 'geom_reference' / 'lon.rdr').as_posix()}",
            f"mintpy.load.incAngleFile = {(stack_work_dir / 'merged' / 'geom_reference' / 'los.rdr').as_posix()}",
            f"mintpy.load.azAngleFile = {(stack_work_dir / 'merged' / 'geom_reference' / 'los.rdr').as_posix()}",
            f"mintpy.load.shadowMaskFile = {(stack_work_dir / 'merged' / 'geom_reference' / 'shadowMask.rdr').as_posix()}",
            "mintpy.plot = no",
            "mintpy.unwrapError.method = no",
            "mintpy.troposphericDelay.method = no",
            "mintpy.topographicResidual = no",
        ]
    ) + "\n"


def _write_default_template(mintpy_work_dir: Path, stack_work_dir: Path) -> Path:
    template_path = mintpy_work_dir / "isce2_stack.txt"
    template_path.write_text(_default_template_text(stack_work_dir), encoding="utf-8")
    return template_path


def run_mintpy_isce2_stack(
    mintpy_work_dir: str | Path,
    stack_work_dir: str | Path,
    conda_env: str,
    mintpy_config: str | Path | None = None,
    python_bin: str | None = None,
    smallbaseline_bin: str | None = None,
    prep_isce_bin: str | None = None,
    prep_isce_env: str | None = None,
) -> dict[str, object]:
    work_dir = Path(mintpy_work_dir)
    stack_dir = Path(stack_work_dir)

    if not _SCRIPT.exists():
        raise FileNotFoundError(f"MintPy script not found: {_SCRIPT}")
    if not stack_dir.exists():
        raise FileNotFoundError(str(stack_dir))
    if not (stack_dir / "merged" / "interferograms").exists():
        raise FileNotFoundError(str(stack_dir / "merged" / "interferograms"))
    if not (stack_dir / "merged" / "geom_reference").exists():
        raise FileNotFoundError(str(stack_dir / "merged" / "geom_reference"))
    if not (stack_dir / "merged" / "baselines").exists():
        raise FileNotFoundError(str(stack_dir / "merged" / "baselines"))

    work_dir.mkdir(parents=True, exist_ok=True)
    jobs_dir = work_dir / ".jobs"
    jobs_dir.mkdir(exist_ok=True)
    logs_dir = resolve_plugin_logs_dir(work_dir, fallback_root=work_dir)
    logs_dir.mkdir(parents=True, exist_ok=True)

    config_path = Path(mintpy_config) if mintpy_config else _write_default_template(work_dir, stack_dir)
    if not config_path.exists():
        raise FileNotFoundError(str(config_path))

    job_id = str(uuid4())
    log_path = str(logs_dir / f"{job_id}.log")
    command = [
        "conda",
        "run",
        "--no-capture-output",
        "-n",
        conda_env,
        "bash",
        str(_SCRIPT),
        str(work_dir),
        str(stack_dir),
        str(config_path),
    ]

    env = os.environ.copy()
    if python_bin:
        env["PYTHON_BIN"] = python_bin
    if smallbaseline_bin:
        env["SMALLBASELINE_BIN"] = smallbaseline_bin
    if prep_isce_bin:
        env["PREP_ISCE_BIN"] = prep_isce_bin
    if prep_isce_env:
        env["PREP_ISCE_ENV"] = prep_isce_env

    with open(log_path, "w") as lf:
        proc = subprocess.Popen(command, stdout=lf, stderr=subprocess.STDOUT, env=env)

    job_data: dict[str, object] = {
        "job_id": job_id,
        "pid": proc.pid,
        "status": "running",
        "log_path": log_path,
        "submitted_at": datetime.now(UTC).isoformat(),
        "finished_at": None,
        "command": command,
        "stack_work_dir": str(stack_dir),
        "mintpy_config": str(config_path),
    }
    (jobs_dir / f"{job_id}.json").write_text(json.dumps(job_data, indent=2))
    return job_data
