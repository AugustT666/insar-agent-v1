from __future__ import annotations

import shlex


def build_stack_command(params: dict, work_dir: str, conda_env: str | None = None) -> list[str]:
    """
    Build the stackSentinel.py command for time-series stack preparation.

    stackSentinel.py generates a structured directory of run scripts that
    are then executed in order by insar_run_batch.

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

    if params.get("aux_dir"):
        args += ["-a", shlex.quote(params["aux_dir"])]

    if params.get("bbox"):
        s, n, w, e = params["bbox"]
        args += ["-b", f"'{s} {n} {w} {e}'"]

    swaths = params.get("swaths", [1, 2, 3])
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
        f'PYTHONPATH="$ISCE_STACK" '
        f'python "$ISCE_STACK/topsStack/stackSentinel.py" {args_str}'
    )

    if conda_env:
        return ["conda", "run", "-n", conda_env, "--no-capture-output", "bash", "-c", inner_cmd]
    return ["bash", "-c", inner_cmd]
