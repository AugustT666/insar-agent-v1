"""Unit tests for M4: single-reference stack and interferogram network preparation."""
from __future__ import annotations

import csv
from pathlib import Path

import pytest
import yaml

from insar_agent.engines.isce3.stack import (
    discover_scenes,
    extract_date,
    resolve_reference,
    validate_reference_scene,
    prepare_stack,
)
from insar_agent.engines.isce3.network import (
    build_forward_neighbor_pairs,
    build_temporal_threshold_pairs,
    load_pair_strings,
    resolve_pairs,
    prepare_network,
)
from insar_agent.mcp.server import insar_prepare_stack, insar_prepare_network


# ── helpers ───────────────────────────────────────────────────────────────────

NISAR_TEMPLATE = """\
NISAR_L1_PR_RSLC_005_172_A_008_2005_DHDH_A_{date}T024618_{date}T024652_X05007_N_F_J_001_cropped.h5
"""

def make_rslc(data_dir: Path, date: str) -> Path:
    """Create a fake NISAR RSLC .h5 file whose name encodes the given date."""
    name = (
        f"NISAR_L1_PR_RSLC_005_172_A_008_2005_DHDH_A_{date}T024618_{date}T024652"
        "_X05007_N_F_J_001_cropped.h5"
    )
    p = data_dir / name
    p.write_bytes(b"")   # zero-byte placeholder
    return p


def make_fixture_runconfig(tmp_path: Path) -> Path:
    """Copy the insar_nisar.yaml fixture to a temp location."""
    fixture = Path("tests/fixtures/insar_nisar.yaml")
    if not fixture.exists():
        pytest.skip("Fixture tests/fixtures/insar_nisar.yaml not found")
    dest = tmp_path / "insar_nisar.yaml"
    dest.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")
    return dest


def make_dem(tmp_path: Path) -> Path:
    dem = tmp_path / "dem.tif"
    dem.write_bytes(b"")
    return dem


# ── extract_date ──────────────────────────────────────────────────────────────

def test_extract_date_valid():
    name = "NISAR_L1_PR_RSLC_005_172_A_20250101T024618_20250101T024652.h5"
    assert extract_date(name) == "20250101"


def test_extract_date_no_match():
    assert extract_date("random_file.h5") is None


# ── discover_scenes ───────────────────────────────────────────────────────────

def test_discover_scenes_two_files(tmp_path):
    data_dir = tmp_path / "rslc"
    data_dir.mkdir()
    make_rslc(data_dir, "20251122")
    make_rslc(data_dir, "20251204")
    scenes = discover_scenes(data_dir)
    assert len(scenes) == 2
    dates = [s.date for s in scenes]
    assert "20251122" in dates
    assert "20251204" in dates


def test_discover_scenes_requires_two(tmp_path):
    data_dir = tmp_path / "rslc"
    data_dir.mkdir()
    make_rslc(data_dir, "20251122")
    with pytest.raises(ValueError, match="at least 2"):
        discover_scenes(data_dir)


def test_discover_scenes_duplicate_date_raises(tmp_path):
    data_dir = tmp_path / "rslc"
    data_dir.mkdir()
    make_rslc(data_dir, "20251122")
    # Create a second file with the same date but different name suffix
    (data_dir / "NISAR_L1_PR_RSLC_005_172_A_008_2005_DHDH_A_20251122T030000_20251122T030001_X05007_N_F_J_002_cropped.h5").write_bytes(b"")
    with pytest.raises(ValueError, match="Duplicate"):
        discover_scenes(data_dir)


# ── resolve_reference ─────────────────────────────────────────────────────────

def test_resolve_reference_auto(tmp_path):
    data_dir = tmp_path / "rslc"
    data_dir.mkdir()
    make_rslc(data_dir, "20251204")
    make_rslc(data_dir, "20251122")
    scenes = discover_scenes(data_dir)
    ref = resolve_reference("auto", scenes)
    assert ref.date == "20251122"


def test_resolve_reference_by_date(tmp_path):
    data_dir = tmp_path / "rslc"
    data_dir.mkdir()
    make_rslc(data_dir, "20251122")
    make_rslc(data_dir, "20251204")
    scenes = discover_scenes(data_dir)
    ref = resolve_reference("20251122", scenes)
    assert ref.date == "20251122"


def test_resolve_reference_not_found(tmp_path):
    data_dir = tmp_path / "rslc"
    data_dir.mkdir()
    make_rslc(data_dir, "20251122")
    make_rslc(data_dir, "20251204")
    scenes = discover_scenes(data_dir)
    with pytest.raises(ValueError, match="not found"):
        resolve_reference("19990101", scenes)


# ── validate_reference_scene ──────────────────────────────────────────────────

def test_validate_reference_earliest_ok(tmp_path):
    data_dir = tmp_path / "rslc"
    data_dir.mkdir()
    make_rslc(data_dir, "20251122")
    make_rslc(data_dir, "20251204")
    scenes = discover_scenes(data_dir)
    ref = resolve_reference("20251122", scenes)
    validate_reference_scene(ref, scenes)  # should not raise


def test_validate_reference_not_earliest_raises(tmp_path):
    data_dir = tmp_path / "rslc"
    data_dir.mkdir()
    make_rslc(data_dir, "20251122")
    make_rslc(data_dir, "20251204")
    scenes = discover_scenes(data_dir)
    late_ref = resolve_reference("20251204", scenes)
    with pytest.raises(ValueError, match="negative temporal baselines"):
        validate_reference_scene(late_ref, scenes)


# ── network pair builders ─────────────────────────────────────────────────────

def test_forward_neighbor_pairs_span1():
    dates = ["20251101", "20251113", "20251125"]
    pairs = build_forward_neighbor_pairs(dates, 1)
    assert pairs == [("20251101", "20251113"), ("20251113", "20251125")]


def test_forward_neighbor_pairs_span2():
    dates = ["20251101", "20251113", "20251125", "20251207"]
    pairs = build_forward_neighbor_pairs(dates, 2)
    assert ("20251101", "20251113") in pairs
    assert ("20251101", "20251125") in pairs
    assert ("20251113", "20251125") in pairs
    assert ("20251113", "20251207") in pairs


def test_temporal_threshold_pairs():
    # 12 days apart → both within 36-day threshold
    dates = ["20251122", "20251204"]
    pairs = build_temporal_threshold_pairs(dates, 36)
    assert pairs == [("20251122", "20251204")]


def test_temporal_threshold_pairs_excludes_long():
    dates = ["20251101", "20260101"]  # ~61 days
    pairs = build_temporal_threshold_pairs(dates, 36)
    assert pairs == []


# ── load_pair_strings ─────────────────────────────────────────────────────────

def test_load_pair_strings_valid(tmp_path):
    pair_file = tmp_path / "pairs.txt"
    pair_file.write_text("20251122_20251204\n20251204_20251216\n", encoding="utf-8")
    pairs = load_pair_strings(pair_file)
    assert pairs == [("20251122", "20251204"), ("20251204", "20251216")]


def test_load_pair_strings_skips_comments(tmp_path):
    pair_file = tmp_path / "pairs.txt"
    pair_file.write_text("# comment\n20251122_20251204\n", encoding="utf-8")
    pairs = load_pair_strings(pair_file)
    assert len(pairs) == 1


def test_load_pair_strings_invalid_format(tmp_path):
    pair_file = tmp_path / "pairs.txt"
    pair_file.write_text("20251122-20251204\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid pair format"):
        load_pair_strings(pair_file)


def test_load_pair_strings_descending_raises(tmp_path):
    pair_file = tmp_path / "pairs.txt"
    pair_file.write_text("20251204_20251122\n", encoding="utf-8")
    with pytest.raises(ValueError, match="ascending"):
        load_pair_strings(pair_file)


# ── prepare_stack (library function) ──────────────────────────────────────────

def test_prepare_stack_generates_runconfigs(tmp_path):
    data_dir = tmp_path / "rslc"
    data_dir.mkdir()
    make_rslc(data_dir, "20251122")
    make_rslc(data_dir, "20251204")
    runconfig = make_fixture_runconfig(tmp_path)
    dem = make_dem(tmp_path)
    output_dir = tmp_path / "stack"

    result = prepare_stack(
        data_dir=data_dir,
        base_runconfig=runconfig,
        dem=dem,
        output_dir=output_dir,
    )

    assert result["reference_date"] == "20251122"
    assert result["num_pairs"] == 1
    assert Path(result["run_all_sh"]).exists()
    assert Path(result["run_parallel_sh"]).exists()
    assert Path(result["manifest_csv"]).exists()
    assert len(result["runconfigs"]) == 1
    assert Path(result["runconfigs"][0]).exists()


def test_prepare_stack_runconfig_contains_paths(tmp_path):
    data_dir = tmp_path / "rslc"
    data_dir.mkdir()
    ref_file = make_rslc(data_dir, "20251122")
    sec_file = make_rslc(data_dir, "20251204")
    runconfig = make_fixture_runconfig(tmp_path)
    dem = make_dem(tmp_path)
    output_dir = tmp_path / "stack"

    result = prepare_stack(data_dir=data_dir, base_runconfig=runconfig, dem=dem, output_dir=output_dir)
    rendered = Path(result["runconfigs"][0]).read_text()
    assert str(ref_file) in rendered
    assert str(sec_file) in rendered
    assert str(dem) in rendered


def test_prepare_stack_manifest_csv(tmp_path):
    data_dir = tmp_path / "rslc"
    data_dir.mkdir()
    make_rslc(data_dir, "20251122")
    make_rslc(data_dir, "20251204")
    runconfig = make_fixture_runconfig(tmp_path)
    dem = make_dem(tmp_path)
    output_dir = tmp_path / "stack"

    result = prepare_stack(data_dir=data_dir, base_runconfig=runconfig, dem=dem, output_dir=output_dir)
    rows = list(csv.DictReader(Path(result["manifest_csv"]).open()))
    assert len(rows) == 1
    assert rows[0]["reference_date"] == "20251122"
    assert rows[0]["secondary_date"] == "20251204"


def test_prepare_stack_missing_dem_error(tmp_path):
    data_dir = tmp_path / "rslc"
    data_dir.mkdir()
    make_rslc(data_dir, "20251122")
    make_rslc(data_dir, "20251204")
    runconfig = make_fixture_runconfig(tmp_path)
    with pytest.raises(FileNotFoundError):
        prepare_stack(data_dir=data_dir, base_runconfig=runconfig, dem="/nonexistent/dem.tif", output_dir=tmp_path / "out")


def test_prepare_stack_negative_baseline_error(tmp_path):
    data_dir = tmp_path / "rslc"
    data_dir.mkdir()
    make_rslc(data_dir, "20251122")
    make_rslc(data_dir, "20251204")
    runconfig = make_fixture_runconfig(tmp_path)
    dem = make_dem(tmp_path)
    with pytest.raises(ValueError, match="negative temporal baselines"):
        prepare_stack(data_dir=data_dir, base_runconfig=runconfig, dem=dem,
                      output_dir=tmp_path / "out", reference="20251204")


# ── prepare_network (library function) ────────────────────────────────────────

def test_prepare_network_tbase_mode(tmp_path):
    data_dir = tmp_path / "rslc"
    data_dir.mkdir()
    make_rslc(data_dir, "20251122")
    make_rslc(data_dir, "20251204")
    runconfig = make_fixture_runconfig(tmp_path)
    dem = make_dem(tmp_path)
    output_dir = tmp_path / "network"

    result = prepare_network(
        data_dir=data_dir,
        base_runconfig=runconfig,
        dem=dem,
        output_dir=output_dir,
        network_mode="tbase",
        max_temporal_baseline_days=36,
    )

    assert result["num_pairs"] == 1  # 12 days < 36 days threshold
    assert result["network_label"] == "pairs_tbase36d"
    assert Path(result["pairs_selected_txt"]).exists()
    assert Path(result["manifest_csv"]).exists()


def test_prepare_network_tbase_excludes_long_baseline(tmp_path):
    data_dir = tmp_path / "rslc"
    data_dir.mkdir()
    make_rslc(data_dir, "20251101")
    make_rslc(data_dir, "20260101")  # ~61 days
    runconfig = make_fixture_runconfig(tmp_path)
    dem = make_dem(tmp_path)
    output_dir = tmp_path / "network"

    result = prepare_network(
        data_dir=data_dir,
        base_runconfig=runconfig,
        dem=dem,
        output_dir=output_dir,
        network_mode="tbase",
        max_temporal_baseline_days=36,
    )
    assert result["num_pairs"] == 0


def test_prepare_network_conn_mode(tmp_path):
    data_dir = tmp_path / "rslc"
    data_dir.mkdir()
    make_rslc(data_dir, "20251101")
    make_rslc(data_dir, "20251113")
    make_rslc(data_dir, "20251125")
    runconfig = make_fixture_runconfig(tmp_path)
    dem = make_dem(tmp_path)
    output_dir = tmp_path / "network"

    result = prepare_network(
        data_dir=data_dir,
        base_runconfig=runconfig,
        dem=dem,
        output_dir=output_dir,
        network_mode="conn",
        connection_span=2,
    )
    # dates: [01, 13, 25]. conn=2 → (01,13), (01,25), (13,25) = 3 pairs
    assert result["num_pairs"] == 3
    assert result["network_label"] == "pairs_conn2"


def test_prepare_network_custom_pair_list(tmp_path):
    data_dir = tmp_path / "rslc"
    data_dir.mkdir()
    make_rslc(data_dir, "20251122")
    make_rslc(data_dir, "20251204")
    runconfig = make_fixture_runconfig(tmp_path)
    dem = make_dem(tmp_path)

    pair_file = tmp_path / "my_pairs.txt"
    pair_file.write_text("20251122_20251204\n", encoding="utf-8")

    result = prepare_network(
        data_dir=data_dir,
        base_runconfig=runconfig,
        dem=dem,
        output_dir=tmp_path / "network",
        pair_list=pair_file,
    )
    assert result["num_pairs"] == 1
    assert result["network_label"] == "my_pairs"


# ── MCP tool wrappers ─────────────────────────────────────────────────────────

def test_mcp_insar_prepare_stack_success(tmp_path):
    data_dir = tmp_path / "rslc"
    data_dir.mkdir()
    make_rslc(data_dir, "20251122")
    make_rslc(data_dir, "20251204")
    runconfig = make_fixture_runconfig(tmp_path)
    dem = make_dem(tmp_path)

    result = insar_prepare_stack(
        data_dir=str(data_dir),
        base_runconfig=str(runconfig),
        dem=str(dem),
        output_dir=str(tmp_path / "stack"),
    )
    assert "error" not in result
    assert result["num_pairs"] == 1
    assert result["reference_date"] == "20251122"


def test_mcp_insar_prepare_stack_bad_dem(tmp_path):
    data_dir = tmp_path / "rslc"
    data_dir.mkdir()
    make_rslc(data_dir, "20251122")
    make_rslc(data_dir, "20251204")
    runconfig = make_fixture_runconfig(tmp_path)

    result = insar_prepare_stack(
        data_dir=str(data_dir),
        base_runconfig=str(runconfig),
        dem="/nonexistent/dem.tif",
        output_dir=str(tmp_path / "stack"),
    )
    assert result["error"] == "path_not_found"


def test_mcp_insar_prepare_network_success(tmp_path):
    data_dir = tmp_path / "rslc"
    data_dir.mkdir()
    make_rslc(data_dir, "20251122")
    make_rslc(data_dir, "20251204")
    runconfig = make_fixture_runconfig(tmp_path)
    dem = make_dem(tmp_path)

    result = insar_prepare_network(
        data_dir=str(data_dir),
        base_runconfig=str(runconfig),
        dem=str(dem),
        output_dir=str(tmp_path / "network"),
    )
    assert "error" not in result
    assert result["num_pairs"] == 1
    assert result["network_label"] == "pairs_tbase36d"


def test_mcp_insar_prepare_network_conn_mode(tmp_path):
    data_dir = tmp_path / "rslc"
    data_dir.mkdir()
    make_rslc(data_dir, "20251101")
    make_rslc(data_dir, "20251113")
    make_rslc(data_dir, "20251125")
    runconfig = make_fixture_runconfig(tmp_path)
    dem = make_dem(tmp_path)

    result = insar_prepare_network(
        data_dir=str(data_dir),
        base_runconfig=str(runconfig),
        dem=str(dem),
        output_dir=str(tmp_path / "network"),
        network_mode="conn",
        connection_span=1,
    )
    assert "error" not in result
    assert result["num_pairs"] == 2  # (01→13), (13→25)


def test_mcp_insar_prepare_network_invalid_mode(tmp_path):
    data_dir = tmp_path / "rslc"
    data_dir.mkdir()
    make_rslc(data_dir, "20251122")
    make_rslc(data_dir, "20251204")
    runconfig = make_fixture_runconfig(tmp_path)
    dem = make_dem(tmp_path)

    result = insar_prepare_network(
        data_dir=str(data_dir),
        base_runconfig=str(runconfig),
        dem=str(dem),
        output_dir=str(tmp_path / "network"),
        network_mode="bogus",
    )
    assert result["error"] == "invalid_input"
