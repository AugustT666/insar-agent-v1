import json
from pathlib import Path

from insar_agent.mcp.server import _configured_opencode_skill_sources


def test_configured_opencode_skill_sources_reads_xdg_and_project_configs(tmp_path, monkeypatch):
    xdg_root = tmp_path / "xdg"
    xdg_config = xdg_root / "opencode" / "opencode.json"
    project_root = tmp_path / "repo"
    project_config = project_root / ".opencode" / "opencode.json"
    skill_source = tmp_path / "skills"
    other_source = tmp_path / "other-skills"
    xdg_config.parent.mkdir(parents=True)
    project_config.parent.mkdir(parents=True)
    xdg_config.write_text(
        json.dumps({"skills": {"sources": [{"path": str(skill_source)}]}}),
        encoding="utf-8",
    )
    project_config.write_text(
        json.dumps(
            {
                "skills": {
                    "sources": [
                        {"path": str(skill_source)},
                        {"path": str(other_source)},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_root))

    assert _configured_opencode_skill_sources(project_root) == [
        skill_source.resolve(),
        other_source.resolve(),
    ]


def test_project_opencode_config_denies_bash_for_insar_sessions():
    repo_root = Path(__file__).resolve().parents[2]
    config = json.loads((repo_root / ".opencode" / "opencode.json").read_text(encoding="utf-8"))

    assert config["permission"]["bash"] == "deny"
