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


OVERRIDE_KEYS = [
    "mintpy.load.processor", "mintpy.load.autoPath", "mintpy.load.metaFile",
    "mintpy.load.baselineDir", "mintpy.load.unwFile", "mintpy.load.corFile",
    "mintpy.load.connCompFile", "mintpy.load.intFile", "mintpy.load.demFile",
    "mintpy.load.lookupYFile", "mintpy.load.lookupXFile", "mintpy.load.incAngleFile",
    "mintpy.load.azAngleFile", "mintpy.load.shadowMaskFile", "mintpy.plot",
    "mintpy.unwrapError.method", "mintpy.solidEarthTides", "mintpy.deramp",
    "mintpy.ionosphericDelay.method", "mintpy.troposphericDelay.method",
    "mintpy.troposphericDelay.weatherModel", "mintpy.troposphericDelay.weatherDir",
    "mintpy.topographicResidual", "mintpy.network.coherenceBased",
    "mintpy.network.minCoherence", "mintpy.network.keepMinSpanTree",
]


def _non_comment_keys(text: str) -> set[str]:
    keys = set()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        keys.add(stripped.split("=", 1)[0].strip())
    return keys


def test_official_asset_is_full_and_has_all_override_keys():
    text = mp.OFFICIAL_MINTPY_TEMPLATE_ASSET.read_text(encoding="utf-8")
    # a full official template (>= 110 mintpy.* param lines)
    assert sum(1 for l in text.splitlines() if l.strip().startswith("mintpy.")) >= 110
    # every override key exists as a non-comment assignment (so upsert replaces, not appends)
    keys = _non_comment_keys(text)
    for key in OVERRIDE_KEYS:
        assert key in keys, f"missing override key in official asset: {key}"


def test_official_loader_falls_back_to_asset_when_no_env():
    text = mp._official_mintpy_template_text("")
    assert "mintpy.network.coherenceBased" in text
    assert sum(1 for l in text.splitlines() if l.strip().startswith("mintpy.")) >= 110
