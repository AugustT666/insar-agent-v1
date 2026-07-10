from __future__ import annotations

from pathlib import Path

from insar_agent.engines.isce2.stack import (
    detect_stack_topology_change,
    stack_topology_signature,
    write_stack_topology,
)


def _params(slc_dir: Path, **overrides) -> dict:
    base = {
        "slc_dir": str(slc_dir),
        "orbit_dir": "/tmp/orbits",
        "dem_file": "/tmp/dem.tif",
    }
    base.update(overrides)
    return base


def test_stack_topology_signature_captures_topology_fields(tmp_path: Path) -> None:
    slc_dir = tmp_path / "safe"
    slc_dir.mkdir()
    sig = stack_topology_signature(
        _params(slc_dir, num_connections=4, swaths=[1, 2], coregistration="geometry")
    )

    assert sig == {"num_connections": 4, "swaths": [1, 2], "coregistration": "geometry"}


def test_stack_topology_signature_defaults_match_build_command(tmp_path: Path) -> None:
    """Defaults mirror build_stack_command: num_connections None, swaths [1,2,3], coreg NESD."""
    slc_dir = tmp_path / "safe"
    slc_dir.mkdir()
    sig = stack_topology_signature(_params(slc_dir))

    assert sig == {"num_connections": None, "swaths": [1, 2, 3], "coregistration": "NESD"}


def test_detect_topology_change_returns_empty_without_signature(tmp_path: Path) -> None:
    """No recorded signature (legacy run) -> cannot prove a change -> resume allowed."""
    slc_dir = tmp_path / "safe"
    slc_dir.mkdir()

    assert detect_stack_topology_change(str(tmp_path / "stack"), _params(slc_dir)) == []


def test_detect_topology_change_flags_changed_num_connections(tmp_path: Path) -> None:
    slc_dir = tmp_path / "safe"
    slc_dir.mkdir()
    stack_dir = tmp_path / "stack"
    write_stack_topology(str(stack_dir), _params(slc_dir, num_connections=3))

    changed = detect_stack_topology_change(str(stack_dir), _params(slc_dir, num_connections=5))

    assert changed == ["num_connections"]


def test_detect_topology_change_empty_when_unchanged(tmp_path: Path) -> None:
    slc_dir = tmp_path / "safe"
    slc_dir.mkdir()
    stack_dir = tmp_path / "stack"
    params = _params(slc_dir, num_connections=4, swaths=[1, 2], coregistration="NESD")
    write_stack_topology(str(stack_dir), params)

    assert detect_stack_topology_change(str(stack_dir), params) == []


def test_write_then_detect_roundtrip_flags_swaths_change(tmp_path: Path) -> None:
    slc_dir = tmp_path / "safe"
    slc_dir.mkdir()
    stack_dir = tmp_path / "stack"
    write_stack_topology(str(stack_dir), _params(slc_dir, swaths=[1, 2, 3]))

    changed = detect_stack_topology_change(str(stack_dir), _params(slc_dir, swaths=[2]))

    assert changed == ["swaths"]
