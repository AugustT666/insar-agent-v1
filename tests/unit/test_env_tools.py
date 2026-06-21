"""Unit tests for insar_check_env MCP registration self-report and conda discovery.

Regression coverage for the inline ``--plugin-dir`` false-negative: a fresh
``claude mcp list`` subprocess cannot see a session-only plugin MCP server, so
the check must rely on the ``CLAUDE_PLUGIN_ROOT`` runtime signal instead of
treating that miss as "not registered".

Also covers FIX 1 — real conda env discovery: insar_check_env must enumerate
ACTUAL local envs via ``conda env list --json``, probe each for ISCE2/ISCE3/MintPy
capabilities, and surface ``discovered_envs`` + ``capable`` keyed by real env names.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from insar_agent.mcp.tools import env_tools


# ---------------------------------------------------------------------------
# Helpers shared by legacy MCP-registration tests
# ---------------------------------------------------------------------------

def _fake_run_factory(mcp_list_stdout: str, mcp_list_rc: int = 0):
    """Build a subprocess.run stand-in that dispatches by command."""

    def fake_run(cmd, *_args, **_kwargs):
        if cmd[:3] == ["claude", "mcp", "list"]:
            return SimpleNamespace(returncode=mcp_list_rc, stdout=mcp_list_stdout, stderr="")
        if cmd[:3] == ["claude", "plugin", "list"]:
            return SimpleNamespace(
                returncode=0, stdout="insar-agent-plugin@inline  ✔ loaded\n", stderr=""
            )
        # conda env list --json
        if cmd[:3] == ["conda", "env", "list"] and "--json" in cmd:
            return SimpleNamespace(returncode=0, stdout='{"envs": ["/opt/conda", "/opt/conda/envs/base"]}', stderr="")
        # conda run per-env probe: pretend every env imports cleanly
        return SimpleNamespace(returncode=0, stdout='{"isce2": "2.6.3", "isce3": null, "mintpy": null}\n', stderr="")

    return fake_run


# ---------------------------------------------------------------------------
# Helpers for conda-discovery tests
# ---------------------------------------------------------------------------

def _make_discovery_run(env_paths: list[str], env_probe_map: dict[str, dict]):
    """
    Return a fake subprocess.run that:
    - responds to ``conda env list --json`` with the given env_paths
    - responds to ``conda run -n <name> python -c ...`` with the capability JSON
      from env_probe_map[<name>], or returncode=1 if name not in map
    - handles claude and plugin list calls for the rest of insar_check_env
    """

    def fake_run(cmd, *_args, **_kwargs):
        # conda env list --json
        if list(cmd[:4]) == ["conda", "env", "list", "--json"]:
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps({"envs": env_paths}),
                stderr="",
            )
        # conda run -n <name> python -c ...  (per-env capability probe)
        if list(cmd[:2]) == ["conda", "run"] and "-n" in cmd:
            n_idx = list(cmd).index("-n")
            env_name = cmd[n_idx + 1]
            if env_name in env_probe_map:
                return SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps(env_probe_map[env_name]) + "\n",
                    stderr="",
                )
            return SimpleNamespace(returncode=1, stdout="", stderr="probe failed")
        # claude mcp list
        if list(cmd[:3]) == ["claude", "mcp", "list"]:
            return SimpleNamespace(returncode=0, stdout="No MCP servers configured.\n", stderr="")
        # claude plugin list
        if list(cmd[:3]) == ["claude", "plugin", "list"]:
            return SimpleNamespace(returncode=0, stdout="insar-agent-plugin@inline  ✔ loaded\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    return fake_run


def test_reports_registered_when_running_inside_plugin_server(monkeypatch):
    """Inline --plugin-dir: CLAUDE_PLUGIN_ROOT is set but `claude mcp list`
    (no --plugin-dir) sees nothing. We must still report registered=True and
    the plugin-namespaced server_name."""
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", "/home/august/insar-agent")
    monkeypatch.setattr(
        env_tools.subprocess,
        "run",
        _fake_run_factory("No MCP servers configured. Use `claude mcp add`.\n"),
    )

    result = env_tools.insar_check_env()

    assert result["mcp"]["registered"] is True
    assert result["mcp"]["server_name"] == "plugin:insar-agent-plugin:insar-mcp-server"


def test_uses_exact_name_from_claude_mcp_list_when_cli_can_see_server(monkeypatch):
    """Persistent / project install: no CLAUDE_PLUGIN_ROOT, but `claude mcp list`
    shows the connected server. Use its exact namespaced name. Guards the
    `✔ Connected` glyph match (the prior code looked for the wrong check mark)."""
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    listing = (
        "Checking MCP server health…\n\n"
        "plugin:insar-agent-plugin:insar-mcp-server: "
        "python -m insar_agent.mcp.server --stdio - ✔ Connected\n"
    )
    monkeypatch.setattr(env_tools.subprocess, "run", _fake_run_factory(listing))

    result = env_tools.insar_check_env()

    assert result["mcp"]["registered"] is True
    assert result["mcp"]["server_name"] == "plugin:insar-agent-plugin:insar-mcp-server"


# ---------------------------------------------------------------------------
# FIX 1 — Real conda env discovery tests (RED → GREEN)
# ---------------------------------------------------------------------------

def test_discovered_envs_keyed_by_real_env_names(monkeypatch):
    """insar_check_env must discover real conda env names (not a hardcoded list).

    Given two non-standard envs s1_isce (has ISCE2) and mymintpy (has MintPy),
    discovered_envs must be keyed by those real names and carry the probe results.
    """
    env_paths = [
        "/opt/conda",                    # base — skip or label "base"
        "/opt/conda/envs/s1_isce",       # has ISCE2
        "/opt/conda/envs/mymintpy",      # has MintPy only
    ]
    env_probe_map = {
        "s1_isce": {"isce2": "2.6.3", "isce3": None, "mintpy": None},
        "mymintpy": {"isce2": None, "isce3": None, "mintpy": "1.5.2"},
    }
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    monkeypatch.setattr(
        env_tools.subprocess, "run", _make_discovery_run(env_paths, env_probe_map)
    )

    result = env_tools.insar_check_env()

    assert "discovered_envs" in result, "result must include 'discovered_envs'"
    discovered = result["discovered_envs"]
    assert "s1_isce" in discovered, f"s1_isce missing from discovered_envs: {discovered.keys()}"
    assert "mymintpy" in discovered, f"mymintpy missing from discovered_envs: {discovered.keys()}"
    # base env should NOT appear under its path-basename (it's /opt/conda, basename=conda)
    # or it may appear as "base"; in either case it must not shadow real env names
    assert "s1_isce" not in {k for k in discovered if k in ("conda", "base", "opt")}

    assert discovered["s1_isce"]["isce2"] == "2.6.3"
    assert discovered["s1_isce"]["isce3"] is None
    assert discovered["mymintpy"]["mintpy"] == "1.5.2"
    assert discovered["mymintpy"]["isce2"] is None


def test_capable_maps_real_env_names_to_capabilities(monkeypatch):
    """capable[<cap>] must list REAL env names that successfully import each package."""
    env_paths = [
        "/opt/conda",
        "/opt/conda/envs/s1_isce",
        "/opt/conda/envs/mymintpy",
    ]
    env_probe_map = {
        "s1_isce": {"isce2": "2.6.3", "isce3": None, "mintpy": None},
        "mymintpy": {"isce2": None, "isce3": None, "mintpy": "1.5.2"},
    }
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    monkeypatch.setattr(
        env_tools.subprocess, "run", _make_discovery_run(env_paths, env_probe_map)
    )

    result = env_tools.insar_check_env()

    assert "capable" in result, "result must include 'capable'"
    capable = result["capable"]
    assert capable.get("isce2") == ["s1_isce"], (
        f"capable.isce2 must be ['s1_isce'], got {capable.get('isce2')}"
    )
    assert capable.get("mintpy") == ["mymintpy"], (
        f"capable.mintpy must be ['mymintpy'], got {capable.get('mintpy')}"
    )
    assert capable.get("isce3", []) == [], (
        f"capable.isce3 must be [] (no env has it), got {capable.get('isce3')}"
    )


def test_install_hints_only_for_capabilities_with_no_capable_env(monkeypatch):
    """install_hints must appear ONLY for capabilities where capable[cap] is empty."""
    env_paths = [
        "/opt/conda",
        "/opt/conda/envs/s1_isce",
    ]
    env_probe_map = {
        "s1_isce": {"isce2": "2.6.3", "isce3": None, "mintpy": None},
    }
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    monkeypatch.setattr(
        env_tools.subprocess, "run", _make_discovery_run(env_paths, env_probe_map)
    )

    result = env_tools.insar_check_env()

    hints = result.get("install_hints", {})
    # isce2 is covered — no hint needed
    assert "isce2" not in hints, f"isce2 is capable, must not appear in install_hints: {hints}"
    # isce3 and mintpy have no capable env — hints should appear
    assert "isce3" in hints, f"isce3 not capable, must appear in install_hints: {hints}"
    assert "mintpy" in hints, f"mintpy not capable, must appear in install_hints: {hints}"
