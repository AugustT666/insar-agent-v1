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


def build_stack_command(
    params: dict,
    work_dir: str,
    conda_env: str | None = None,
    resume_from_run: int = 0,
    generate_only: bool = False,
    start_step: int = 0,
    end_step: int = 0,
) -> list[str]:
    """
    Build the full ISCE2 topsStack command: runs stackSentinel.py (prep),
    then executes all generated run_files/run_* scripts in order.

    Required params: slc_dir, orbit_dir, dem_file
    Optional params: aux_dir, bbox, swaths, polarization, workflow,
                     num_connections, coregistration, esd_coherence_threshold,
                     filter_strength, range_looks, azimuth_looks,
                     do_unwrap, unwrap_method, num_proc, use_gpu

    resume_from_run: when >= 1, resume a prior run instead of starting over —
        skip stackSentinel.py prep AND the rm -rf wipe, reuse the existing
        run_files/configs/outputs, and execute only run_NN steps with NN >=
        resume_from_run (run_files/ must already exist, else exit 4). 0 (default)
        runs the full prepare+execute from scratch.

    generate_only: when True, run only the wipe + stackSentinel.py prep to produce
        run_files/ + configs/, then STOP (no execution loop). The caller reviews the
        generated per-run configs and later executes via resume_from_run=1. Mutually
        exclusive with resume_from_run at the caller (see insar_run_workflow).

    start_step/end_step: reserved for the inclusive [start..end] run-window
        (0 == unbounded on that side). Accepted here for signature stability; the
        window loop is implemented in PHASE C4 and is inert in this phase.
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

    # Common prelude: ISCE2 import guard (before any destructive step, so a
    # wrong-env launch never wipes the stack dir) + ISCE env setup + cd work_dir.
    prelude = (
        'set -e && '
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
    )

    if generate_only:
        # Generation phase only: wipe + stackSentinel.py prep to produce run_files/ +
        # configs/, then STOP. No execution loop — the caller reviews the generated
        # per-run configs and later executes via resume_from_run=1.
        execute = (
            'rm -rf run_files configs SAFE_files.txt reference geom_reference '
            'secondary secondary_* merged misreg baselines baselines_txt DEM_files && '
            f'python "$ISCE_STACK/topsStack/stackSentinel.py" {args_str} && '
            'echo "[insar-agent] generate_only: run_files/ and configs/ generated; STOP '
            '(no execution). Review the generated configs, then execute with resume_from_run=1."'
        )
    elif resume_from_run and resume_from_run >= 1:
        # Resume: reuse the prior run's run_files/configs/outputs. Skip both the
        # stackSentinel.py prep and the rm -rf wipe, and skip run_NN steps below
        # the resume point. Fail with exit 4 if there is nothing to resume.
        execute = (
            f'RESUME_FROM={int(resume_from_run)} && '
            '{ [ -d run_files ] || { echo "[insar-agent] ERROR: resume_from_run set but '
            'run_files/ missing — run once without resume_from_run first"; exit 4; }; } && '
            'echo "[insar-agent] RESUME: skipping prep + wipe; '
            'running run_files with run >= $RESUME_FROM" && '
            'for f in $(ls -v run_files/run_* 2>/dev/null); do '
            '  b=$(basename "$f"); n=${b#run_}; n=${n%%_*}; num=$((10#$n)); '
            '  if [ "$num" -lt "$RESUME_FROM" ]; then echo "[insar-agent] Skip (resume <$RESUME_FROM): $f"; continue; fi; '
            '  echo "[insar-agent] Step: $f"; '
            '  . "$f" || exit 1; '
            '  sync; '
            'done && '
            'echo "[insar-agent] All stack steps completed."'
        )
    else:
        # Full run: wipe prior outputs, regenerate run_files via stackSentinel.py,
        # then execute every generated run step in order.
        execute = (
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

    inner_cmd = prelude + execute

    if conda_env:
        return ["conda", "run", "-n", conda_env, "--no-capture-output", "bash", "-c", inner_cmd]
    return ["bash", "-c", inner_cmd]
