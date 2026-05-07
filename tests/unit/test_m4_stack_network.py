"""Unit tests for M4: single-reference stack and interferogram network preparation."""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from insar_agent.engines.isce3.defaults import get_default_runconfig_template_path
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
    prepare_network,
)
from insar_agent.core.jobs import BatchJob, Job
from insar_agent.mcp.server import insar_prepare_stack, insar_prepare_network, insar_run_batch, insar_get_job


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
    assert result["base_runconfig_source"] == "user_provided"


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


def test_prepare_stack_runconfig_uses_workspace_dot_insar_logs(tmp_path):
    (tmp_path / ".insar_logs").mkdir()
    data_dir = tmp_path / "rslc"
    data_dir.mkdir()
    make_rslc(data_dir, "20251122")
    make_rslc(data_dir, "20251204")
    runconfig = make_fixture_runconfig(tmp_path)
    dem = make_dem(tmp_path)
    output_dir = tmp_path / "stack"

    result = prepare_stack(data_dir=data_dir, base_runconfig=runconfig, dem=dem, output_dir=output_dir)
    rendered = Path(result["runconfigs"][0]).read_text()
    assert str(tmp_path / ".insar_logs" / "stack_20251122_20251204.log") in rendered


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


def test_prepare_stack_uses_default_template_when_base_runconfig_omitted(tmp_path):
    data_dir = tmp_path / "rslc"
    data_dir.mkdir()
    make_rslc(data_dir, "20251122")
    make_rslc(data_dir, "20251204")
    dem = make_dem(tmp_path)

    result = prepare_stack(
        data_dir=data_dir,
        base_runconfig=None,
        dem=dem,
        output_dir=tmp_path / "stack",
    )

    assert result["base_runconfig_source"] == "default_template"
    assert result["base_runconfig"] == str(get_default_runconfig_template_path("insar"))


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


def test_prepare_network_uses_default_template_when_base_runconfig_omitted(tmp_path):
    data_dir = tmp_path / "rslc"
    data_dir.mkdir()
    make_rslc(data_dir, "20251122")
    make_rslc(data_dir, "20251204")
    dem = make_dem(tmp_path)

    result = prepare_network(
        data_dir=data_dir,
        base_runconfig=None,
        dem=dem,
        output_dir=tmp_path / "network",
    )

    assert result["base_runconfig_source"] == "default_template"
    assert result["base_runconfig"] == str(get_default_runconfig_template_path("insar"))


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
    assert result["base_runconfig"] == str(runconfig.resolve())
    assert result["base_runconfig_source"] == "user_provided"
    assert result["interaction_mode"] == "interactive"
    assert result["handoff_required"] is True
    assert "reference" in result["handoff_reason"].lower()
    assert any("stack_manifest.csv" in path for path in result["review_artifacts"])
    assert "insar_run_batch" in result["next_recommended_action"]


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
    assert result["base_runconfig"] == str(runconfig.resolve())
    assert result["base_runconfig_source"] == "user_provided"
    assert result["interaction_mode"] == "interactive"
    assert result["handoff_required"] is True
    assert any("pairs_selected.txt" in path for path in result["review_artifacts"])
    assert "insar_run_batch" in result["next_recommended_action"]


def test_mcp_insar_prepare_stack_auto_mode_skips_handoff(tmp_path):
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
        interaction_mode="auto",
    )

    assert result["interaction_mode"] == "auto"
    assert result["handoff_required"] is False


def test_mcp_insar_prepare_stack_uses_default_template_when_omitted(tmp_path):
    data_dir = tmp_path / "rslc"
    data_dir.mkdir()
    make_rslc(data_dir, "20251122")
    make_rslc(data_dir, "20251204")
    dem = make_dem(tmp_path)

    result = insar_prepare_stack(
        data_dir=str(data_dir),
        dem=str(dem),
        output_dir=str(tmp_path / "stack"),
    )

    assert "error" not in result
    assert result["base_runconfig_source"] == "default_template"
    assert result["base_runconfig"] == str(get_default_runconfig_template_path("insar"))


def test_mcp_insar_prepare_network_auto_mode_skips_handoff(tmp_path):
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
        interaction_mode="auto",
    )

    assert result["interaction_mode"] == "auto"
    assert result["handoff_required"] is False


def test_mcp_insar_prepare_network_uses_default_template_when_omitted(tmp_path):
    data_dir = tmp_path / "rslc"
    data_dir.mkdir()
    make_rslc(data_dir, "20251122")
    make_rslc(data_dir, "20251204")
    dem = make_dem(tmp_path)

    result = insar_prepare_network(
        data_dir=str(data_dir),
        dem=str(dem),
        output_dir=str(tmp_path / "network"),
    )

    assert "error" not in result
    assert result["base_runconfig_source"] == "default_template"
    assert result["base_runconfig"] == str(get_default_runconfig_template_path("insar"))


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


# ── BatchJob persistence ───────────────────────────────────────────────────────

def test_batch_job_save_and_load(tmp_path):
    """BatchJob round-trips through JSON save/load correctly."""
    batch_dir = str(tmp_path / "batch")
    Path(batch_dir).mkdir()
    job = BatchJob(
        batch_dir=batch_dir,
        batch_type="stack",
        num_pairs=4,
        run_parallel_sh=str(tmp_path / "batch" / "run_parallel.sh"),
        max_jobs=4,
    )
    job.save()
    loaded = BatchJob.load(job.job_id, batch_dir)
    assert loaded.job_id == job.job_id
    assert loaded.batch_type == "stack"
    assert loaded.num_pairs == 4


# ── insar_run_batch ────────────────────────────────────────────────────────────

def _make_batch_dir(tmp_path: Path, n_pairs: int = 2) -> Path:
    """Create a minimal prepared batch directory with run_parallel.sh and runconfigs."""
    batch_dir = tmp_path / "batch"
    (batch_dir / "runconfigs").mkdir(parents=True)
    run_parallel_sh = batch_dir / "run_parallel.sh"
    run_parallel_sh.write_text("#!/usr/bin/env bash\nexit 0\n")
    run_all_sh = batch_dir / "run_all.sh"
    run_all_sh.write_text("#!/usr/bin/env bash\nexit 0\n")
    for i in range(n_pairs):
        (batch_dir / "runconfigs" / f"pair_{i}.yaml").write_text("dummy: true\n")
    return batch_dir


def test_insar_run_batch_background_returns_job_id(tmp_path):
    """run_batch returns job_id, pid, log_path, and poll in background mode."""
    import unittest.mock as mock
    (tmp_path / ".insar_logs").mkdir()
    batch_dir = _make_batch_dir(tmp_path)
    mock_proc = mock.MagicMock()
    mock_proc.pid = 99999
    with mock.patch("insar_agent.mcp.server.subprocess.Popen", return_value=mock_proc):
        result = insar_run_batch(batch_dir=str(batch_dir), max_jobs=2)
    assert "error" not in result
    assert "job_id" in result
    assert result["status"] == "running"
    assert result["state"] == "running"
    assert result["running_count"] == 2
    assert result["queued_count"] == 0
    assert result["failed_count"] == 0
    assert result["pid"] == 99999
    assert result["interaction_mode"] == "interactive"
    assert result["execution_mode"] == "parallel"
    assert "log_path" in result
    assert "poll" in result
    assert "command" in result
    assert "progress_hint" in result
    assert "batch_dir" in result["poll"]
    assert Path(result["log_path"]).parent == tmp_path / ".insar_logs"
    # Job JSON persisted
    jobs_dir = batch_dir / ".insar_agent" / "jobs"
    assert any(jobs_dir.glob("*.json"))


def test_insar_run_batch_serial_mode_uses_run_all_and_python_override(tmp_path):
    import unittest.mock as mock

    batch_dir = _make_batch_dir(tmp_path)
    mock_proc = mock.MagicMock()
    mock_proc.pid = 123

    with mock.patch("insar_agent.mcp.server.subprocess.Popen", return_value=mock_proc) as mock_popen:
        result = insar_run_batch(
            batch_dir=str(batch_dir),
            execution_mode="serial",
            python_bin="/opt/conda/bin/python",
            interaction_mode="auto",
        )

    args, kwargs = mock_popen.call_args
    assert args[0] == ["bash", str(batch_dir / "run_all.sh")]
    assert kwargs["env"]["PYTHON_BIN"] == "/opt/conda/bin/python"
    assert result["execution_mode"] == "serial"
    assert result["interaction_mode"] == "auto"
    assert result["command"] == f"bash {batch_dir / 'run_all.sh'}"


def test_insar_run_batch_invalid_execution_mode(tmp_path):
    batch_dir = _make_batch_dir(tmp_path)
    result = insar_run_batch(batch_dir=str(batch_dir), execution_mode="bogus")
    assert result["error"] == "invalid_input"


def test_insar_run_batch_no_run_parallel_sh(tmp_path):
    """Returns not_prepared if run_parallel.sh is missing."""
    batch_dir = tmp_path / "batch"
    (batch_dir / "runconfigs").mkdir(parents=True)
    result = insar_run_batch(batch_dir=str(batch_dir))
    assert result["error"] == "not_prepared"


def test_insar_run_batch_no_runconfigs(tmp_path):
    """Returns no_pairs_to_run if runconfigs/ is empty."""
    batch_dir = tmp_path / "batch"
    (batch_dir / "runconfigs").mkdir(parents=True)
    (batch_dir / "run_parallel.sh").write_text("#!/usr/bin/env bash\n")
    result = insar_run_batch(batch_dir=str(batch_dir))
    assert result["warning"] == "no_pairs_to_run"


def test_insar_run_batch_launch_failure(tmp_path):
    """Returns launch_failed if Popen raises."""
    import unittest.mock as mock
    batch_dir = _make_batch_dir(tmp_path)
    with mock.patch("insar_agent.mcp.server.subprocess.Popen", side_effect=OSError("boom")):
        result = insar_run_batch(batch_dir=str(batch_dir))
    assert result["error"] == "launch_failed"


# ── insar_get_job batch_dir branch ────────────────────────────────────────────

def _make_batch_job(tmp_path: Path, status: str = "running", pid: int = 12345) -> tuple[BatchJob, str]:
    batch_dir = str(tmp_path / "batch")
    Path(batch_dir).mkdir(parents=True, exist_ok=True)
    log_path = str(tmp_path / "batch" / "logs" / "job.log")
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    Path(log_path).write_text("Starting ISCE3 workflow...\n")
    job = BatchJob(
        batch_dir=batch_dir,
        batch_type="stack",
        num_pairs=3,
        run_parallel_sh=str(tmp_path / "run_parallel.sh"),
        max_jobs=4,
        status=status,
        pid=pid,
        log_path=log_path,
    )
    job.save()
    return job, batch_dir


def test_insar_get_job_batch_running(tmp_path):
    """Returns status=running while process is alive."""
    import unittest.mock as mock
    job, batch_dir = _make_batch_job(tmp_path, status="running", pid=12345)
    # Patch os.kill to not raise (process alive) and proc status to show sleeping state.
    # Use side_effect on read_text to only intercept /proc paths.
    original_read_text = Path.read_text
    def _fake_read_text(self, *args, **kwargs):
        if str(self).startswith("/proc/"):
            return "Name: python\nState: S (sleeping)\n"
        return original_read_text(self, *args, **kwargs)
    with mock.patch("insar_agent.mcp.server.os.kill"):  # no exception = alive
        with mock.patch.object(Path, "read_text", _fake_read_text):
            result = insar_get_job(job_id=job.job_id, batch_dir=batch_dir)
    assert result["status"] == "running"
    assert result["batch_type"] == "stack"
    assert result["num_pairs"] == 3


def test_insar_get_job_batch_pid_dead_clean_log(tmp_path):
    """Transitions to done when PID is dead and log has no errors."""
    import unittest.mock as mock
    job, batch_dir = _make_batch_job(tmp_path, status="running", pid=12345)
    # Write a clean log
    Path(job.log_path).write_text("Processing complete.\n")
    with mock.patch("insar_agent.mcp.server.os.kill", side_effect=ProcessLookupError):
        result = insar_get_job(job_id=job.job_id, batch_dir=batch_dir)
    assert result["status"] == "done"
    assert result["exit_code"] == 0


def test_insar_get_job_batch_pid_dead_error_in_log(tmp_path):
    """Transitions to failed when PID is dead and log contains 'error:'."""
    import unittest.mock as mock
    job, batch_dir = _make_batch_job(tmp_path, status="running", pid=12345)
    Path(job.log_path).write_text("error: something went wrong\n")
    with mock.patch("insar_agent.mcp.server.os.kill", side_effect=ProcessLookupError):
        result = insar_get_job(job_id=job.job_id, batch_dir=batch_dir)
    assert result["status"] == "failed"
    assert result["exit_code"] == 1


def test_insar_get_job_batch_job_not_found(tmp_path):
    """Returns job_not_found for unknown job_id."""
    batch_dir = str(tmp_path / "batch")
    Path(batch_dir).mkdir()
    result = insar_get_job(job_id="no-such-job", batch_dir=batch_dir)
    assert result["error"] == "job_not_found"


def test_insar_get_job_batch_include_logs(tmp_path):
    """Returns log_content when include_logs=True."""
    job, batch_dir = _make_batch_job(tmp_path, status="done", pid=None)
    job.status = "done"
    job.save()
    result = insar_get_job(job_id=job.job_id, batch_dir=batch_dir, include_logs=True)
    assert "log_content" in result
    assert result["log_content"] is not None


def test_insar_get_job_batch_dir_reads_legacy_project_job_json(tmp_path):
    batch_dir = tmp_path / "sentinel-stack"
    log_path = tmp_path / "stack.log"
    log_path.write_text("failed in topsStack\n", encoding="utf-8")
    job = Job(
        project_id="project-1",
        engine="isce2",
        workflow="stack",
        status="failed",
        job_id="job-1",
        exit_code=1,
        log_path=str(log_path),
    )
    job.save(BatchJob.jobs_dir_for(batch_dir))

    result = insar_get_job(job_id="job-1", batch_dir=str(batch_dir), include_logs=True)

    assert result["job_id"] == "job-1"
    assert result["project_id"] == "project-1"
    assert result["workflow"] == "stack"
    assert result["status"] == "failed"
    assert result["exit_code"] == 1
    assert result["log_content"] == "failed in topsStack\n"


def test_insar_get_job_missing_all_params():
    """Returns missing_param mentioning batch_dir when no context given."""
    result = insar_get_job(job_id="x")
    assert result["error"] == "missing_param"
    assert "batch_dir" in result["message"]
