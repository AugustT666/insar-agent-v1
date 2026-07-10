from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_freeform_skill_exists_with_frontmatter() -> None:
    skill = REPO / "skills" / "freeform" / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    assert text.startswith("---")
    assert "name: freeform" in text
    assert "version:" in text


def test_freeform_skill_states_safety_red_lines() -> None:
    text = (REPO / "skills" / "freeform" / "SKILL.md").read_text(encoding="utf-8")
    # No bare bash over run_files; run-containment; gate still applies.
    assert "run_files" in text
    assert "run-containment" in text or "run_root" in text
    assert "param-advisor" in text or "gate" in text


def test_freeform_skill_maps_each_engine_native_unit() -> None:
    text = (REPO / "skills" / "freeform" / "SKILL.md").read_text(encoding="utf-8")
    for token in ("resume_from_run", "from_step", "to_step", "insar_set_runconfig_value",
                  "insar_run_mintpy_isce2", "insar_run_batch", "generate_only",
                  "start_step", "end_step"):
        assert token in text


def test_freeform_skill_warns_mintpy_config_required_on_tuned_rerun() -> None:
    # A tuned MintPy rerun that omits mintpy_config=<mintpy_work_dir>/isce2_stack.txt
    # silently regenerates the template from defaults via smallbaselineApp.py -g,
    # discarding the scope="mintpy" edits. The skill must call this out explicitly.
    text = (REPO / "skills" / "freeform" / "SKILL.md").read_text(encoding="utf-8")
    assert "mintpy_config" in text
    assert "isce2_stack.txt" in text


def test_router_has_freeform_row() -> None:
    text = (REPO / "skills" / "insar-agent" / "SKILL.md").read_text(encoding="utf-8")
    assert "`freeform`" in text
    assert "partial execution" in text.lower()
