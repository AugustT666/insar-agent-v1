"""MintPy launcher for ISCE2/topsStack Sentinel workflows."""
from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import numpy as np

_SCRIPT = Path(__file__).parent / "assets" / "run_mintpy_isce2_stack.sh"

# Pinned copy of MintPy's official full smallbaselineApp.cfg template (all 119
# parameters listed with comments). Used as the seed base and as a fallback when
# the official template cannot be read from the resolved MintPy conda env.
OFFICIAL_MINTPY_TEMPLATE_ASSET = Path(__file__).parent / "assets" / "smallbaselineApp_full.cfg"

# Canonical managed MintPy template filename for ISCE2/topsStack runs.
# ONE file is the single source of truth: (a) the auto-generated default template,
# (b) the target that scope="mintpy" science-param writes edit, and (c) the file the
# tuned rerun passes back as mintpy_config=. run_mintpy_isce2_stack feeds this file to
# `smallbaselineApp.py -g`, which regenerates <work_dir>/smallbaselineApp.cfg FROM it —
# so edits must land here to reach the workflow. Writing smallbaselineApp.cfg directly
# is clobbered by the -g regeneration.
MANAGED_MINTPY_CFG_NAME = "isce2_stack.txt"


def managed_mintpy_cfg_path(mintpy_work_dir: str | Path) -> Path:
    """Absolute path of the canonical managed MintPy template inside a work dir."""
    return Path(mintpy_work_dir) / MANAGED_MINTPY_CFG_NAME


def _format_cfg_value(value: object) -> str:
    """Render a MintPy cfg value using MintPy conventions (yes/no bools, comma lists)."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (list, tuple)):
        return ",".join(str(v) for v in value)
    return str(value)


def _upsert_cfg_line(text: str, key: str, value: object) -> str:
    """Upsert ``mintpy.<key> = <value>`` into MintPy cfg text (pure).

    Replaces the single non-comment assignment whose left-hand side exactly
    equals the fully-qualified key; appends the line if absent. Every other
    line (comments, unrelated keys) is preserved verbatim. Exact-key matching
    means ``mintpy.deramp`` never clobbers ``mintpy.deramp.maskFile``. Returns
    new text ending in a newline. Never mutates its input.
    """
    full_key = key if key.startswith("mintpy.") else f"mintpy.{key}"
    new_line = f"{full_key} = {_format_cfg_value(value)}"
    out: list[str] = []
    replaced = False
    for line in text.splitlines():
        stripped = line.strip()
        left = stripped.split("=", 1)[0].strip() if "=" in stripped else ""
        if left == full_key and not stripped.startswith("#"):
            out.append(new_line)
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(new_line)
    return "\n".join(out) + "\n"


def set_mintpy_cfg_value(mintpy_work_dir: str | Path, key: str, value: object) -> Path:
    """Upsert ``mintpy.<key> = <value>`` into the canonical managed MintPy template.

    Writes to ``<mintpy_work_dir>/isce2_stack.txt`` — the exact file
    run_mintpy_isce2_stack feeds to ``smallbaselineApp.py -g`` — so scope="mintpy"
    science-param edits actually reach the regenerated smallbaselineApp.cfg and the
    workflow. Delegates the text edit to :func:`_upsert_cfg_line` (matching key
    replaced in place, else appended; all other lines preserved). Creates the file
    (and its parent directory) if absent. Never mutates its inputs. Returns the cfg
    path written.
    """
    cfg_path = managed_mintpy_cfg_path(mintpy_work_dir)
    existing = cfg_path.read_text(encoding="utf-8") if cfg_path.exists() else ""
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(_upsert_cfg_line(existing, key, value), encoding="utf-8")
    return cfg_path


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


def _tops_text_baseline_dir(stack_dir: Path) -> Path | None:
    baseline_dir = stack_dir / "baselines"
    if any(path.is_file() and path.stat().st_size > 0 for path in baseline_dir.glob("*/*.txt")):
        return baseline_dir
    return None


def export_mintpy_tops_baselines(stack_work_dir: str | Path) -> Path:
    stack_dir = Path(stack_work_dir)
    text_baseline_dir = _tops_text_baseline_dir(stack_dir)
    if text_baseline_dir is not None:
        return text_baseline_dir

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
        raise FileNotFoundError(
            f"No topsStack baseline text files or baseline rasters found under "
            f"{stack_dir / 'baselines'} or {baseline_root}"
        )

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


def _official_mintpy_template_text(conda_env: str = "") -> str:
    """Return the official full MintPy smallbaselineApp.cfg template text.

    Prefers the copy shipped inside the resolved MintPy conda env (so the seed
    matches the exact MintPy version the run will use); falls back to the pinned
    asset shipped with the plugin when no env is given or the lookup fails.
    """
    if conda_env:
        try:
            proc = subprocess.run(
                [
                    "conda", "run", "-n", conda_env, "python", "-c",
                    "import mintpy, os, sys; "
                    "sys.stdout.write(os.path.join(os.path.dirname(mintpy.__file__), "
                    "'defaults', 'smallbaselineApp.cfg'))",
                ],
                capture_output=True, text=True, timeout=60,
            )
            cand = Path(proc.stdout.strip())
            if proc.returncode == 0 and cand.is_file():
                return cand.read_text(encoding="utf-8")
        except Exception:
            pass
    return OFFICIAL_MINTPY_TEMPLATE_ASSET.read_text(encoding="utf-8")


def _default_template_text(
    stack_work_dir: Path,
    baseline_dir: Path | None = None,
    *,
    weather_dir: str | None = None,
    weather_model: str = "ERA5",
    conda_env: str = "",
) -> str:
    baseline_dir = baseline_dir or export_mintpy_tops_baselines(stack_work_dir)
    ifg = stack_work_dir / "merged" / "interferograms"
    geom = stack_work_dir / "merged" / "geom_reference"
    overrides: list[tuple[str, object]] = [
        # dask parallelism default-on: invert_network / correct_topography are
        # CPU-bound and single-threaded under MintPy's default cluster=none.
        ("mintpy.compute.cluster", "local"),
        ("mintpy.compute.numWorker", 8),
        ("mintpy.load.processor", "isce"),
        ("mintpy.load.autoPath", False),
        ("mintpy.load.metaFile", _default_meta_file(stack_work_dir).as_posix()),
        ("mintpy.load.baselineDir", baseline_dir.as_posix()),
        ("mintpy.load.unwFile", (ifg / "*" / "filt_fine.unw").as_posix()),
        ("mintpy.load.corFile", (ifg / "*" / "filt_fine.cor").as_posix()),
        ("mintpy.load.connCompFile", (ifg / "*" / "filt_fine.unw.conncomp").as_posix()),
        ("mintpy.load.intFile", "None"),
        ("mintpy.load.demFile", (geom / "hgt.rdr").as_posix()),
        ("mintpy.load.lookupYFile", (geom / "lat.rdr").as_posix()),
        ("mintpy.load.lookupXFile", (geom / "lon.rdr").as_posix()),
        ("mintpy.load.incAngleFile", (geom / "los.rdr").as_posix()),
        ("mintpy.load.azAngleFile", (geom / "los.rdr").as_posix()),
        ("mintpy.load.shadowMaskFile", (geom / "shadowMask.rdr").as_posix()),
        ("mintpy.plot", False),
        ("mintpy.unwrapError.method", "bridging+phase_closure"),
        ("mintpy.solidEarthTides", True),
        ("mintpy.deramp", "quadratic"),
        ("mintpy.ionosphericDelay.method", "no"),
        ("mintpy.topographicResidual", True),
        # network trimming defaults (increment A): mechanism on, conservative floor.
        ("mintpy.network.coherenceBased", True),
        ("mintpy.network.minCoherence", 0.2),
        ("mintpy.network.keepMinSpanTree", True),
    ]
    if weather_dir:
        overrides += [
            ("mintpy.troposphericDelay.method", "pyaps"),
            ("mintpy.troposphericDelay.weatherModel", weather_model),
            ("mintpy.troposphericDelay.weatherDir", weather_dir),
        ]
    else:
        overrides += [("mintpy.troposphericDelay.method", "no")]

    text = _official_mintpy_template_text(conda_env)
    for key, value in overrides:
        text = _upsert_cfg_line(text, key, value)
    return text


def _write_default_template(
    mintpy_work_dir: Path,
    stack_work_dir: Path,
    baseline_dir: Path | None = None,
    *,
    weather_dir: str | None = None,
    weather_model: str = "ERA5",
    conda_env: str = "",
) -> Path:
    template_path = managed_mintpy_cfg_path(mintpy_work_dir)
    template_path.write_text(
        _default_template_text(
            stack_work_dir, baseline_dir,
            weather_dir=weather_dir, weather_model=weather_model, conda_env=conda_env,
        ),
        encoding="utf-8",
    )
    return template_path


def run_mintpy_isce2_stack(
    mintpy_work_dir: str | Path,
    stack_work_dir: str | Path,
    conda_env: str = "",
    mintpy_config: str | Path | None = None,
    python_bin: str | None = None,
    smallbaseline_bin: str | None = None,
    weather_dir: str | None = None,
    weather_model: str = "ERA5",
    start_step: str = "",
    end_step: str = "velocity",
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
    baseline_dir = export_mintpy_tops_baselines(stack_dir)

    work_dir.mkdir(parents=True, exist_ok=True)
    from insar_agent.core.output_resolver import resolve_output
    from insar_agent.core.layout import find_run_root
    # Job state and logs belong at the RUN ROOT (<run_root>/.insar_agent/jobs and
    # <run_root>/insar_product/logs), not under work_dir — otherwise, when work_dir
    # is <run_root>/insar_product/mintpy, a second insar_product/ gets nested under
    # mintpy/. Fall back to work_dir when no run-root marker is present.
    run_root = find_run_root(work_dir) or work_dir
    jobs_dir = run_root / ".insar_agent" / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = resolve_output(run_root, "logs")
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Discover a MintPy+pyaps3 env at runtime FIRST — the seed reads the official
    # template from this env, and the runner uses it. Never hardcode the env name.
    from insar_agent.core.conda_env import resolve_conda_env
    conda_env = resolve_conda_env(conda_env, ["mintpy", "pyaps3"], prefer=["isce2", "mintpy"])
    if not conda_env:
        raise RuntimeError(
            "no conda env with MintPy+pyaps3 found to run smallbaselineApp (run insar_check_env)"
        )

    config_path = Path(mintpy_config) if mintpy_config else _write_default_template(
        work_dir, stack_dir, baseline_dir,
        weather_dir=weather_dir, weather_model=weather_model, conda_env=conda_env,
    )
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
        str(baseline_dir),
        str(start_step),
        str(end_step),
    ]

    env = os.environ.copy()
    if python_bin:
        env["PYTHON_BIN"] = python_bin
    if smallbaseline_bin:
        env["SMALLBASELINE_BIN"] = smallbaseline_bin

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
        "baseline_dir": str(baseline_dir),
        "mintpy_config": str(config_path),
    }
    (jobs_dir / f"{job_id}.json").write_text(json.dumps(job_data, indent=2))
    return job_data
