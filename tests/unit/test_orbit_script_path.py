"""ISCE2 topsStack script location must be dynamic (no hardcoded ~/miniconda3/envs/isce2)."""
from pathlib import Path

import pytest

from insar_agent.engines.isce2.sentinel import orbit


def test_topsstack_script_builds_path_under_given_prefix():
    # pure: works for ANY conda root / env name, not just ~/miniconda3/envs/isce2
    p = orbit._topsstack_script("/opt/conda/envs/myisce", "fetchOrbit.py")
    assert p == Path("/opt/conda/envs/myisce/share/isce2/topsStack/fetchOrbit.py")


def test_fetch_scripts_resolve_dynamically_on_host_with_isce2():
    # non-mocked integration: where an ISCE2 env exists, the dynamic resolver finds
    # the REAL scripts via conda discovery (not a hardcoded home path).
    from insar_agent.core.conda_env import find_conda_env
    if not find_conda_env(["isce"], prefer=["isce2", "isce"]):
        pytest.skip("no ISCE2 conda env on this host")
    fo = orbit._fetch_orbit_script_path()
    sw = orbit._fetch_sentinel_wrapper_path()
    assert fo.exists() and fo.name == "fetchOrbit.py"
    assert sw.exists() and sw.name == "SentinelWrapper.py"
    # and it is NOT assuming ~/miniconda3 specifically
    assert "share/isce2/topsStack" in str(fo)
