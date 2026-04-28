from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_mintpy_router_skill_replaces_engine_specific_name() -> None:
    router_skill = (REPO_ROOT / ".claude" / "agents" / "insar-agent.md").read_text(encoding="utf-8")
    nisar_stack_skill = (REPO_ROOT / "skills" / "stack-insar-isce3" / "SKILL.md").read_text(encoding="utf-8")
    sentinel_stack_skill = (REPO_ROOT / "skills" / "stack-insar-isce2" / "SKILL.md").read_text(encoding="utf-8")
    old_skill_name = "mintpy" + "-isce3"

    assert (REPO_ROOT / "skills" / "mintpy" / "SKILL.md").exists()
    assert not (REPO_ROOT / "skills" / old_skill_name / "SKILL.md").exists()

    assert "`mintpy`" in router_skill
    assert old_skill_name not in router_skill

    assert "`mintpy`" in nisar_stack_skill or "mintpy skill" in nisar_stack_skill.lower()
    assert old_skill_name not in nisar_stack_skill

    assert "mintpy" in sentinel_stack_skill.lower()
