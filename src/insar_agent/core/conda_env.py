"""Dynamic conda-env discovery by package capability.

The plugin runs on machines whose conda env NAMES and install LOCATIONS differ,
so tools must NEVER hardcode an env name (e.g. "isce2") or a miniconda path.
Discover the env that actually has the required packages at runtime instead.
"""
from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path


def conda_env_paths() -> dict[str, str]:
    """Map of conda env name -> on-disk prefix path via ``conda env list --json``.

    The base/root env (whose path's parent is not ``envs``) is keyed ``"base"``.
    Returns {} if conda is absent or the command fails. Source of truth for WHERE
    an env lives, so callers never hardcode ``~/miniconda3/envs/<name>``.
    """
    try:
        r = subprocess.run(
            ["conda", "env", "list", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            return {}
        paths = json.loads(r.stdout).get("envs", [])
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return {}
    out: dict[str, str] = {}
    for p in paths:
        pp = Path(p)
        name = pp.name if pp.parent.name == "envs" else "base"
        out[name] = p
    return out


def discover_conda_envs() -> list[str]:
    """Names of all local conda envs (base labeled ``"base"``)."""
    return list(conda_env_paths().keys())


def conda_env_prefix(name: str, *, paths: dict[str, str] | None = None) -> str | None:
    """Filesystem prefix of conda env *name*, or None if it does not exist.

    Replaces hardcoded ``Path.home() / "miniconda3" / "envs" / <name>`` so script/
    library paths (e.g. ``<prefix>/share/isce2/topsStack/...``) resolve regardless of
    where conda is installed or what the env is named. Inject *paths* for testing.
    """
    paths = conda_env_paths() if paths is None else paths
    return paths.get(name)


def env_imports(env_name: str, packages: Sequence[str]) -> bool:
    """True if every package in *packages* imports inside *env_name*.

    One ``conda run -n <env> python -c "import a, b"`` probe. Tolerates all errors.
    """
    code = "import " + ", ".join(packages)
    try:
        r = subprocess.run(
            ["conda", "run", "-n", env_name, "--no-capture-output", "python", "-c", code],
            capture_output=True, text=True, timeout=60,
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def find_conda_env(
    packages: Sequence[str],
    *,
    envs: Sequence[str] | None = None,
    probe: Callable[[str, Sequence[str]], bool] | None = None,
    prefer: Sequence[str] = (),
    include_base: bool = False,
) -> str | None:
    """Return the name of a conda env where ALL *packages* import, or None.

    Discovers envs dynamically (``conda env list``) and probes each (``conda run``)
    unless *envs*/*probe* are injected (for testing). Skips the base env by default
    (geo/InSAR deps belong in dedicated envs). Among qualifying envs, returns the
    first whose name appears in *prefer*, else the first qualifying env.
    """
    if envs is None:
        envs = discover_conda_envs()
    if probe is None:
        probe = env_imports
    candidates = [e for e in envs if include_base or e != "base"]
    qualifying = [e for e in candidates if probe(e, packages)]
    if not qualifying:
        return None
    for p in prefer:
        if p in qualifying:
            return p
    return qualifying[0]


def resolve_conda_env(
    conda_env: str | None,
    packages: Sequence[str],
    *,
    prefer: Sequence[str] = (),
    envs: Sequence[str] | None = None,
    probe: Callable[[str, Sequence[str]], bool] | None = None,
) -> str | None:
    """Return *conda_env* if the caller specified one, else discover an env that
    imports *packages*. The single entry point tools use instead of a hardcoded
    ``conda_env="isce2"`` default (pass ``conda_env=""``/``None`` to auto-discover).
    """
    if conda_env:
        return conda_env
    return find_conda_env(packages, prefer=prefer, envs=envs, probe=probe)
