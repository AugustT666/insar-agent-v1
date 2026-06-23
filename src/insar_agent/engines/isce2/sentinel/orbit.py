from __future__ import annotations

import netrc
import subprocess
import time
from pathlib import Path
from typing import Callable, TypeVar

from insar_agent.engines.isce2.sentinel._common import _conda_safe_env, _redact_command
from insar_agent.engines.isce2.sentinel.metadata import SceneRecord


T = TypeVar("T")


def _retry_with_backoff(
    func: Callable[..., T],
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    on_retry: Callable[[int, Exception], None] | None = None,
) -> T:
    """
    Execute a function with exponential backoff retry logic.

    Args:
        func: Callable to execute
        max_retries: Maximum number of retry attempts (3 = try once, retry twice more)
        initial_delay: Initial delay in seconds before first retry
        backoff_factor: Multiplier for delay between retries
        on_retry: Optional callback invoked on retry (receives attempt number and exception)

    Returns:
        Result of func() if successful within max_retries attempts

    Raises:
        Last exception if all retries are exhausted
    """
    last_exception = None
    delay = initial_delay

    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            last_exception = e
            if attempt < max_retries - 1:
                if on_retry:
                    on_retry(attempt + 1, e)
                time.sleep(delay)
                delay *= backoff_factor

    if last_exception:
        raise last_exception
    raise RuntimeError("Unexpected: no exception raised but all retries exhausted")


def _topsstack_script(prefix: str, script_name: str) -> Path:
    """Path to an ISCE2 topsStack script inside a conda env *prefix* (pure)."""
    return Path(prefix) / "share" / "isce2" / "topsStack" / script_name


def _topsstack_env_and_script(script_name: str, conda_env: str | None = None) -> tuple[str, Path]:
    """Discover the conda env that has ISCE2 (or use the given one) and return BOTH the
    env NAME and the resolved topsStack script path, so the same env feeds both the
    filesystem lookup and ``conda run -n <env>`` — WITHOUT hardcoding the conda install
    path or env name. Works for any conda root / env name."""
    from insar_agent.core.conda_env import conda_env_prefix, resolve_conda_env

    env = resolve_conda_env(conda_env, ["isce"], prefer=["isce2", "isce"])
    if not env:
        raise FileNotFoundError(
            f"No conda env with ISCE2 found to locate {script_name} "
            "(run insar_check_env to discover/create one)."
        )
    prefix = conda_env_prefix(env)
    if not prefix:
        raise FileNotFoundError(f"Cannot resolve filesystem prefix for conda env {env!r}")
    script = _topsstack_script(prefix, script_name)
    if not script.exists():
        raise FileNotFoundError(f"ISCE2 {script_name} not found under env {env!r}: {script}")
    return env, script


def _topsstack_script_path(script_name: str, conda_env: str | None = None) -> Path:
    return _topsstack_env_and_script(script_name, conda_env)[1]


def _fetch_orbit_script_path(conda_env: str | None = None) -> Path:
    return _topsstack_script_path("fetchOrbit.py", conda_env)


def _fetch_sentinel_wrapper_path(conda_env: str | None = None) -> Path:
    return _topsstack_script_path("SentinelWrapper.py", conda_env)


def _resolve_orbit_token_file(
    orbit_token_file: str | None,
    orbit_username: str | None,
    orbit_password: str | None,
    logs_dir: Path,
) -> str | None:
    if orbit_token_file:
        token_path = Path(orbit_token_file).expanduser().resolve()
        if not token_path.exists():
            raise FileNotFoundError(f"Orbit token file does not exist: {orbit_token_file}")
        return str(token_path)
    if orbit_username and orbit_password:
        return None
    try:
        hosts = netrc.netrc().hosts
    except (FileNotFoundError, netrc.NetrcParseError):
        hosts = {}
    if "dataspace.copernicus.eu" in hosts:
        return None
    default_token_file = logs_dir / "copernicus_dataspace_token.json"
    if default_token_file.exists():
        return str(default_token_file)
    raise ValueError(
        "Precise orbit download requires dataspace.copernicus.eu credentials in ~/.netrc, "
        "explicit orbit_username/orbit_password, or a token file at "
        f"{default_token_file}"
    )


def _download_orbits_for_scenes(
    scenes: list[SceneRecord],
    orbit_dir: Path,
    orbit_username: str | None = None,
    orbit_password: str | None = None,
    orbit_token_file: str | None = None,
    on_log: Callable[[str], None] | None = None,
) -> tuple[int, list[dict]]:
    log = on_log or (lambda _: None)
    orbit_dir.mkdir(parents=True, exist_ok=True)
    env, script = _topsstack_env_and_script("fetchOrbit.py")
    before = {path.name for path in orbit_dir.glob("*.EOF")}
    failed: list[dict] = []

    for scene in scenes:
        command = [
            "conda",
            "run",
            "-n",
            env,
            "python",
            str(script),
            "-i",
            scene.safe_path,
            "-o",
            str(orbit_dir),
        ]
        if orbit_token_file:
            command.extend(["-t", orbit_token_file])
        if orbit_username:
            command.extend(["-u", orbit_username])
        if orbit_password:
            command.extend(["-p", orbit_password])

        log(f"RUN {_redact_command(command)}")
        last_result: dict[str, object] = {}

        def run_with_timeout():
            result = subprocess.run(command, capture_output=True, text=True, timeout=300, env=_conda_safe_env())
            last_result.update(
                {
                    "returncode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
            )
            if result.returncode != 0:
                message = result.stderr.strip() or result.stdout.strip() or "orbit download failed"
                raise RuntimeError(message)
            return result

        def on_retry_log(attempt: int, exc: Exception) -> None:
            log(f"RETRY attempt {attempt} after transient failure: {exc}")

        try:
            result = _retry_with_backoff(
                run_with_timeout,
                max_retries=3,
                initial_delay=2.0,
                backoff_factor=2.0,
                on_retry=on_retry_log,
            )
        except Exception as e:
            failed.append(
                {
                    "scene_id": scene.scene_id,
                    "safe_path": scene.safe_path,
                    "command": command,
                    "message": f"orbit download failed after retries: {str(e)}",
                    "returncode": last_result.get("returncode"),
                    "stdout": last_result.get("stdout", ""),
                    "stderr": last_result.get("stderr", ""),
                }
            )
            continue
        if result.stdout.strip():
            for line in result.stdout.splitlines():
                if line.strip():
                    log(line)
        if result.stderr.strip():
            for line in result.stderr.splitlines():
                if line.strip():
                    log(line)
    after = {path.name for path in orbit_dir.glob("*.EOF")}
    return len(after - before), failed
