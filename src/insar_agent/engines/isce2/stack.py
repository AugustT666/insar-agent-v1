from __future__ import annotations

import re
import shlex
from pathlib import Path

_SWATH_RE = re.compile(r"(?:^|-)iw([123])(?:-|_)", re.IGNORECASE)


def _detect_stack_swaths(slc_dir: str, configured: list[int]) -> list[int]:
    """Return swaths common to all SAFE scenes in slc_dir.

    When the configured list is the default [1,2,3], auto-detects from data.
    If a specific non-default list is given, respects it as-is.
    Falls back to configured if detection yields nothing.
    """
    if configured != [1, 2, 3]:
        return configured
    common: set[int] | None = None
    for safe in Path(slc_dir).glob("*.SAFE"):
        annotation = safe / "annotation"
        swaths = {
            int(m.group(1))
            for f in annotation.glob("*.xml")
            for m in [_SWATH_RE.search(f.name)]
            if m
        }
        if not swaths:
            continue
        common = swaths if common is None else common & swaths
    return sorted(common) if common else configured


def build_stack_command(params: dict, work_dir: str, conda_env: str | None = None) -> list[str]:
    """
    Build the full ISCE2 topsStack command: runs stackSentinel.py (prep),
    then executes all generated run_files/run_* scripts in order.

    Required params: slc_dir, orbit_dir, dem_file
    Optional params: aux_dir, bbox, swaths, polarization, workflow,
                     num_connections, coregistration, esd_coherence_threshold,
                     filter_strength, range_looks, azimuth_looks,
                     do_unwrap, unwrap_method, num_proc, use_gpu
    """
    args = [
        "-s", shlex.quote(params["slc_dir"]),
        "-o", shlex.quote(params["orbit_dir"]),
        "-d", shlex.quote(params["dem_file"]),
        "-w", shlex.quote(work_dir),
    ]

    # stackSentinel.py always requires -a; use placeholder if not provided
    aux_dir = params.get("aux_dir") or f"{work_dir}/aux_cal"
    args += ["-a", shlex.quote(aux_dir)]

    if params.get("bbox"):
        s, n, w, e = params["bbox"]
        args += ["-b", f"'{s} {n} {w} {e}'"]

    swaths = _detect_stack_swaths(params["slc_dir"], params.get("swaths", [1, 2, 3]))
    args += ["-n", f"'{' '.join(str(s) for s in swaths)}'"]

    if params.get("polarization"):
        args += ["-p", params["polarization"]]

    workflow = params.get("workflow", "interferogram")
    args += ["-W", workflow]

    if params.get("num_connections"):
        args += ["-c", str(params["num_connections"])]

    coregistration = params.get("coregistration", "NESD")
    args += ["-C", coregistration]

    if params.get("esd_coherence_threshold") is not None:
        args += ["-e", str(params["esd_coherence_threshold"])]

    if params.get("filter_strength") is not None:
        args += ["-f", str(params["filter_strength"])]

    if params.get("range_looks") is not None:
        args += ["-r", str(params["range_looks"])]

    if params.get("azimuth_looks") is not None:
        args += ["-z", str(params["azimuth_looks"])]

    if params.get("unwrap_method"):
        args += ["-u", params["unwrap_method"]]

    if params.get("num_proc"):
        args += ["--num_proc", str(params["num_proc"])]

    if params.get("use_gpu"):
        args += ["-useGPU"]

    args_str = " ".join(args)
    inner_cmd = (
        'set -e && '
        # Fail fast before any rm -rf if ISCE2 is not importable in this environment.
        # Prevents destroying the stack directory when the wrong conda env is used.
        'python -c "import isce" 2>/dev/null || '
        '{ echo "[insar-agent] ERROR: ISCE2 not importable in this environment — '
        'pass a conda_env that has ISCE2 (run insar_check_env to discover capable envs)"; '
        'exit 3; } && '
        f'mkdir -p {shlex.quote(aux_dir)} && '
        "ISCE_PREFIX=\"${CONDA_PREFIX:-$(python -c 'import sys; print(sys.prefix)')}\" && "
        'export ISCE_STACK="${ISCE_STACK:-$ISCE_PREFIX/share/isce2}" && '
        "export ISCE_APPLICATIONS=\"$(python -c 'import pathlib, sys; matches=sorted(pathlib.Path(sys.prefix, \"lib\").glob(\"python*/site-packages/isce/applications\")); print(matches[0]) if matches else sys.exit(\"ISCE applications directory not found\")')\" && "
        'export ISCE_HOME="$(dirname "$ISCE_APPLICATIONS")" && '
        'export PYTHONPATH="$ISCE_STACK" && '
        'export PATH="$ISCE_STACK/topsStack:$ISCE_APPLICATIONS:$PATH" && '
        f'cd {shlex.quote(work_dir)} && '
        'rm -rf run_files configs SAFE_files.txt reference geom_reference '
        'secondary secondary_* merged misreg baselines baselines_txt DEM_files && '
        f'python "$ISCE_STACK/topsStack/stackSentinel.py" {args_str} && '
        'echo "[insar-agent] stackSentinel.py done; executing run_files..." && '
        'for f in $(ls -v run_files/run_* 2>/dev/null); do '
        '  echo "[insar-agent] Step: $f"; '
        '  . "$f" || exit 1; '
        '  sync; '  # flush parallel writes (e.g. fullBurst_resample IW2.xml) before the next step reads them
        'done && '
        'echo "[insar-agent] All stack steps completed."'
    )

    if conda_env:
        return ["conda", "run", "-n", conda_env, "--no-capture-output", "bash", "-c", inner_cmd]
    return ["bash", "-c", inner_cmd]
