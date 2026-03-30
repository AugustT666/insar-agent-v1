from __future__ import annotations

from pathlib import Path

from insar_agent.mcp.server import insar_create_project, process_insar_batch, process_insar_pair


REPO_ROOT = Path("/home/august/insar-agent")


def test_create_project_guidance_mentions_subagent_requirement(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "registry"))
    result = insar_create_project(
        engine="isce3",
        workflow="insar",
        workspace_root=str(tmp_path / "ws"),
    )
    assert "guidance" in result
    guidance = result["guidance"].lower()
    assert "subagent" in guidance
    assert "param-advisor-isce3" in guidance


def test_process_prompts_require_subagent_delegation():
    pair_prompt = process_insar_pair()
    batch_prompt = process_insar_batch()
    assert "subagent" in pair_prompt.lower()
    assert "param-advisor-isce3" in pair_prompt
    assert "subagent" in batch_prompt.lower()
    assert "param-advisor-isce3" in batch_prompt


def test_param_advisor_skill_requires_subagent():
    skill = (REPO_ROOT / "skills" / "param-advisor-isce3" / "SKILL.md").read_text(encoding="utf-8")
    lowered = skill.lower()
    assert "subagent" in lowered
    assert "主 agent 不得直接" in skill
    assert "param-advisor-worker-isce3" in skill
    assert "gpt codex5.3" in lowered or "gpt-5.3-codex" in lowered
    assert "claude sonnet4.6" in lowered or "claude sonnet 4.6" in lowered


def test_param_advisor_worker_skill_exists_and_declares_contract():
    worker_path = REPO_ROOT / "skills" / "param-advisor-worker-isce3" / "SKILL.md"
    assert worker_path.exists()
    worker = worker_path.read_text(encoding="utf-8")
    lowered = worker.lower()
    assert "evidence profile" in lowered
    assert "runconfig" in lowered
    assert "默认值" in worker
    assert "建议值" in worker
    assert "风险" in worker
    assert "置信度" in worker
    assert "不调用 mcp 工具" in worker
    assert "gpt-5.3-codex" in worker or "gpt codex5.3" in worker.lower()
    assert "claude sonnet 4.6" in worker.lower() or "claude sonnet4.6" in worker.lower()


def test_core_docs_describe_skill_aware_subagent_boundary():
    guide = (REPO_ROOT / "docs" / "agent-guide.md").read_text(encoding="utf-8")
    architecture = (REPO_ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    claude = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "skill-aware client" in guide
    assert "subagent" in guide.lower()
    assert "plugin contract" in architecture.lower()
    assert "mcp contract" in architecture.lower()
    assert "subagent" in claude.lower()
    assert "gpt-5.3-codex" in claude.lower() or "gpt codex5.3" in claude.lower()
