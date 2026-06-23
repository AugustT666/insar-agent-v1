"""ISCE2 applications/ scripts must be located via conda discovery, not a hardcoded
~/miniconda3/envs/isce2 path."""
import pytest

from insar_agent.mcp import server


def test_isce2_app_script_returns_none_when_no_isce_env(monkeypatch):
    # No env imports 'isce' -> (None, None), no crash, no hardcoded path assumed.
    monkeypatch.setattr("insar_agent.core.conda_env.find_conda_env", lambda pkgs, **k: None)
    assert server._isce2_app_script("dem.py") == (None, None)


def test_isce2_app_script_globs_under_discovered_prefix(monkeypatch):
    monkeypatch.setattr("insar_agent.core.conda_env.find_conda_env", lambda pkgs, **k: "myisce")
    monkeypatch.setattr("insar_agent.core.conda_env.conda_env_prefix",
                        lambda name, **k: "/nonexistent/envs/myisce")
    env, script = server._isce2_app_script("dem.py")
    assert env == "myisce"        # discovered env name threaded through
    assert script is None          # glob under a fake prefix finds nothing (no crash)


def test_isce2_app_script_resolves_real_scripts_on_host():
    # non-mocked integration: where ISCE2 exists, locate the real applications scripts.
    from insar_agent.core.conda_env import find_conda_env
    if not find_conda_env(["isce"], prefer=["isce2", "isce"]):
        pytest.skip("no ISCE2 conda env on this host")
    for name in ("dem.py", "gdal2isce_xml.py"):
        env, script = server._isce2_app_script(name)
        assert env
        assert script is not None and script.exists() and script.name == name
        assert "site-packages/isce/applications" in str(script)
