"""Dynamic conda-env discovery by package capability (no hardcoded env names)."""
from insar_agent.core import conda_env


def _probe_from(caps):
    # caps: {env_name: set(importable_packages)}
    return lambda env, pkgs: set(pkgs) <= caps.get(env, set())


def test_find_conda_env_returns_env_with_all_packages():
    caps = {"isce2": {"cdsapi", "pygrib", "mintpy"}, "geo": {"gdal"}, "empty": set()}
    got = conda_env.find_conda_env(
        ["cdsapi", "pygrib"], envs=["base", "empty", "geo", "isce2"], probe=_probe_from(caps))
    assert got == "isce2"


def test_find_conda_env_returns_none_when_no_env_qualifies():
    assert conda_env.find_conda_env(
        ["cdsapi"], envs=["a", "b"], probe=lambda e, p: False) is None


def test_find_conda_env_skips_base_by_default():
    # base would import everything but must NOT be chosen (geo deps belong in a real env)
    got = conda_env.find_conda_env(["x"], envs=["base", "real"], probe=lambda e, p: True)
    assert got == "real"


def test_find_conda_env_honors_prefer_order():
    got = conda_env.find_conda_env(
        ["x"], envs=["aaa", "mintpy", "isce2"], probe=lambda e, p: True,
        prefer=["isce2", "mintpy"])
    assert got == "isce2"


def test_find_conda_env_falls_back_to_first_qualifying_when_no_prefer_match():
    caps = {"alpha": {"x"}, "beta": {"x"}}
    got = conda_env.find_conda_env(
        ["x"], envs=["alpha", "beta"], probe=_probe_from(caps), prefer=["zzz"])
    assert got in ("alpha", "beta")


def test_conda_env_prefix_looks_up_path_by_name():
    # Resolves the env's real prefix from a name->path map (no ~/miniconda3 guess).
    paths = {"base": "/opt/conda", "isce2": "/data/envs/isce2", "mintpy": "/x/envs/mintpy"}
    assert conda_env.conda_env_prefix("mintpy", paths=paths) == "/x/envs/mintpy"
    assert conda_env.conda_env_prefix("isce2", paths=paths) == "/data/envs/isce2"
    assert conda_env.conda_env_prefix("nope", paths=paths) is None


def test_resolve_conda_env_returns_explicit_when_given():
    # Caller-specified env wins; no discovery attempted.
    got = conda_env.resolve_conda_env("myenv", ["isce"], envs=["other"], probe=lambda e, p: False)
    assert got == "myenv"


def test_resolve_conda_env_discovers_when_empty():
    caps = {"isce2": {"isce"}}
    got = conda_env.resolve_conda_env(
        "", ["isce"], envs=["base", "isce2"], probe=_probe_from(caps), prefer=["isce2"])
    assert got == "isce2"
