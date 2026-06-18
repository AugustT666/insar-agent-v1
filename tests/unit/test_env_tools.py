"""Unit tests for insar_check_env MCP registration self-report.

Regression coverage for the inline ``--plugin-dir`` false-negative: a fresh
``claude mcp list`` subprocess cannot see a session-only plugin MCP server, so
the check must rely on the ``CLAUDE_PLUGIN_ROOT`` runtime signal instead of
treating that miss as "not registered".
"""

from __future__ import annotations

from types import SimpleNamespace

from insar_agent.mcp.tools import env_tools


def _fake_run_factory(mcp_list_stdout: str, mcp_list_rc: int = 0):
    """Build a subprocess.run stand-in that dispatches by command."""

    def fake_run(cmd, *_args, **_kwargs):
        if cmd[:3] == ["claude", "mcp", "list"]:
            return SimpleNamespace(returncode=mcp_list_rc, stdout=mcp_list_stdout, stderr="")
        if cmd[:3] == ["claude", "plugin", "list"]:
            return SimpleNamespace(
                returncode=0, stdout="insar-agent-plugin@inline  ✔ loaded\n", stderr=""
            )
        # conda env probes: pretend every expected env imports cleanly
        return SimpleNamespace(returncode=0, stdout="1.0.0\n", stderr="")

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
