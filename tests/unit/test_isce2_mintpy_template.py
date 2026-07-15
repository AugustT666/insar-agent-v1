from __future__ import annotations

from pathlib import Path

from insar_agent.engines.isce2 import mintpy as mp


def test_upsert_replaces_in_place_and_preserves_comments():
    text = (
        "# header comment\n"
        "mintpy.deramp          = auto  #[no / linear / quadratic]\n"
        "mintpy.deramp.maskFile = auto  #[filename / no]\n"
        "mintpy.plot            = auto  #[yes / no]\n"
    )
    out = mp._upsert_cfg_line(text, "mintpy.deramp", "quadratic")
    lines = out.splitlines()
    # exact-key match: only mintpy.deramp changed, NOT mintpy.deramp.maskFile
    assert "mintpy.deramp = quadratic" in lines
    assert "mintpy.deramp.maskFile = auto  #[filename / no]" in lines
    # untouched lines preserved byte-for-byte
    assert "# header comment" in lines
    assert "mintpy.plot            = auto  #[yes / no]" in lines
    # no duplicate deramp line
    assert sum(1 for l in lines if l.strip().startswith("mintpy.deramp ")) == 1


def test_upsert_appends_when_absent():
    out = mp._upsert_cfg_line("", "network.minCoherence", 0.406)
    assert out == "mintpy.network.minCoherence = 0.406\n"
