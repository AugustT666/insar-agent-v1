from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from insar_agent.mcp import server


REPO_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_SKILLS = {
    "insar-agent",
    "env-setup",
    "data-prep",
    "data-prep-nisar",
    "data-prep-sentinel",
    "d-insar-isce3",
    "stack-insar-isce3",
    "param-advisor",
    "mintpy",
    "d-insar-isce2",
    "stack-insar-isce2",
}


def test_plugin_manifest_declares_mcp_server_config() -> None:
    plugin = json.loads((REPO_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    mcp_config_path = REPO_ROOT / ".mcp.json"
    mcp_config = json.loads(mcp_config_path.read_text(encoding="utf-8"))

    assert plugin["mcpServers"] == "./.mcp.json"
    assert set(mcp_config) == {"insar-mcp-server"}
    assert mcp_config["insar-mcp-server"]["command"] == "python"
    assert mcp_config["insar-mcp-server"]["args"] == [
        "-m",
        "insar_agent.mcp.server",
        "--stdio",
    ]
    assert mcp_config["insar-mcp-server"]["env"]["PYTHONPATH"] == "${CLAUDE_PLUGIN_ROOT}/src"


def test_plugin_hooks_use_plugin_wrapper_format() -> None:
    hooks = json.loads((REPO_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))

    assert "description" in hooks
    assert set(hooks["hooks"]) == {"PreToolUse", "PostToolUse"}
    assert "PreToolUse" not in hooks
    assert all(hooks["hooks"].values())


def test_plugin_has_stable_insar_agent_command() -> None:
    command = REPO_ROOT / "commands" / "insar-agent.md"
    text = command.read_text(encoding="utf-8")

    assert "description:" in text
    assert "insar_check_env" in text
    assert "insar://workflow-guide" in text
    assert "skills/insar-agent/SKILL.md" in text


def test_all_plugin_skills_have_versioned_third_person_frontmatter() -> None:
    skill_files = sorted((REPO_ROOT / "skills").glob("*/SKILL.md"))

    assert {path.parent.name for path in skill_files} == EXPECTED_SKILLS
    for skill_file in skill_files:
        text = skill_file.read_text(encoding="utf-8")
        frontmatter = text.split("---", 2)[1]
        assert "version: 0.1.0" in frontmatter
        assert "This skill should be used when" in frontmatter


def test_insar_check_env_tracks_router_skill(monkeypatch) -> None:
    listed_skills = "\n".join(sorted(EXPECTED_SKILLS - {"insar-agent"}))

    def fake_run(cmd, **kwargs):
        if cmd[:2] == ["conda", "run"]:
            return SimpleNamespace(returncode=0, stdout="1.0\n", stderr="")
        if cmd == ["claude", "mcp", "list"]:
            return SimpleNamespace(returncode=0, stdout="insar-mcp-server\n", stderr="")
        if cmd == ["claude", "plugin", "list"]:
            return SimpleNamespace(returncode=0, stdout=listed_skills, stderr="")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(server.subprocess, "run", fake_run)
    monkeypatch.setattr(server, "_configured_opencode_skill_sources", lambda repo_root: [])

    result = server.insar_check_env()

    assert "insar-agent" in result["skills"]["missing"]
    assert "insar-agent" in result["skills"]["claude"]["missing"]
    assert "insar-agent" in result["skills"]["opencode"]["missing"]


def test_param_advisor_agent_has_short_trigger_and_invoke_section() -> None:
    text = (REPO_ROOT / "agents" / "param-advisor.md").read_text(encoding="utf-8")
    frontmatter, body = text.split("---", 2)[1:]

    assert "Typical triggers include" in frontmatter
    assert "## When to invoke" in body
    assert "<example>" not in frontmatter
