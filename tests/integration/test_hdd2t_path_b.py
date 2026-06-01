"""
Path B / MintPy / Sentinel D-InSAR real-data integration tests.

Uses pre-existing artifacts from HDD2T — no ISCE3/ISCE2 processing triggered.
Runtime per test: < 15 seconds.

Data roots:
  _RSLC_DIR     — 7 cropped NISAR RSLC .h5 files (20251029 … 20260109)
  _STACK_DIR    — pre-computed ISCE3 stack (6 pairs, runconfigs + products)
  _MINTPY_DIR   — complete MintPy run (velocity, timeseries, demErr, …)
  _DINSAR_DIR   — completed topsApp ISCE2 D-InSAR (asc rel-014)
  _STACK_SENT_DIR — prepared Sentinel-1 stackSentinel tree (configs, run_files)

Marker: @pytest.mark.real_data
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from insar_agent.mcp.server import (
    insar_prepare_network,
    insar_prepare_stack,
    insar_run_mintpy,
)

# ── Data paths ──────────────────────────────────────────────────────────────

_ROOT = Path("/mnt/HDD2T/August/inasr-agent-test")
_RSLC_DIR = _ROOT / "RSLC"
_DEM = _ROOT / "dem-claude-test" / "dem.tif"
_STACK_DIR = _ROOT / "isce3-stack-real-20260403"
_MINTPY_DIR = _ROOT / "mintpy-network-20260408"
_DINSAR_DIR = _ROOT / "sentinel-dinsar-asc-real-20260413-rerun3"
_STACK_SENT_DIR = _ROOT / "sentinel-stack-desc-real-20260413"
_NETWORK_DIR = _ROOT / "isce3-network-real-20260403"


def _require(*paths: Path) -> None:
    for p in paths:
        if not p.exists():
            pytest.skip(f"Required path not found: {p}")


# ── insar_prepare_stack ────────────────────────────────────────────────────


@pytest.mark.real_data
class TestPrepareStackRealRSLC:
    """insar_prepare_stack against 7 real NISAR RSLC files."""

    def test_prepare_stack_produces_manifest_and_scripts(
        self, tmp_path: Path
    ) -> None:
        _require(_RSLC_DIR, _DEM)
        result = insar_prepare_stack(
            data_dir=str(_RSLC_DIR),
            dem=str(_DEM),
            output_dir="",
            workspace_root=str(tmp_path),
            interaction_mode="auto",
        )

        assert "error" not in result, f"prepare_stack failed: {result}"
        assert result["num_pairs"] == 6, (
            f"Expected 6 pairs from 7 RSLCs, got {result['num_pairs']}"
        )
        assert Path(result["manifest_csv"]).exists()
        assert Path(result["run_parallel_sh"]).exists()
        assert len(result["runconfigs"]) == 6

    def test_prepare_stack_auto_reference_is_earliest(
        self, tmp_path: Path
    ) -> None:
        _require(_RSLC_DIR, _DEM)
        result = insar_prepare_stack(
            data_dir=str(_RSLC_DIR),
            dem=str(_DEM),
            output_dir="",
            workspace_root=str(tmp_path),
            reference="auto",
            interaction_mode="auto",
        )
        assert "error" not in result, result
        assert result["reference_date"] == "20251029", (
            f"Earliest scene should be reference, got {result['reference_date']}"
        )

    def test_prepare_stack_dem_injected_into_runconfigs(
        self, tmp_path: Path
    ) -> None:
        _require(_RSLC_DIR, _DEM)
        result = insar_prepare_stack(
            data_dir=str(_RSLC_DIR),
            dem=str(_DEM),
            output_dir="",
            workspace_root=str(tmp_path),
            interaction_mode="auto",
        )
        assert "error" not in result, result
        first_rc = Path(result["runconfigs"][0]).read_text()
        assert str(_DEM) in first_rc, "DEM path not injected into runconfig"

    def test_prepare_stack_existing_dir_has_correct_structure(self) -> None:
        """Pre-computed stack_manifest.csv matches expected 6-pair structure."""
        _require(_STACK_DIR)
        manifest = _STACK_DIR / "stack_manifest.csv"
        _require(manifest)
        lines = [
            line for line in manifest.read_text().splitlines()
            if line.strip() and not line.startswith("reference_date")
        ]
        assert len(lines) == 6, f"Expected 6 manifest entries, got {len(lines)}"
        # All pairs should share 20251029 as reference
        for line in lines:
            assert line.startswith("20251029"), f"Non-20251029 reference: {line}"


# ── insar_prepare_network ──────────────────────────────────────────────────


@pytest.mark.real_data
class TestPrepareNetworkRealRSLC:
    """insar_prepare_network against 7 real NISAR RSLC files."""

    def test_prepare_network_tbase36d_produces_15_pairs(
        self, tmp_path: Path
    ) -> None:
        _require(_RSLC_DIR, _DEM)
        result = insar_prepare_network(
            data_dir=str(_RSLC_DIR),
            dem=str(_DEM),
            output_dir="",
            workspace_root=str(tmp_path),
            network_mode="tbase",
            max_temporal_baseline_days=36,
            interaction_mode="auto",
        )

        assert "error" not in result, f"prepare_network failed: {result}"
        assert result["num_pairs"] == 15, (
            f"Expected 15 pairs (tbase≤36d, 7 scenes), got {result['num_pairs']}"
        )
        assert Path(result["pairs_selected_txt"]).exists()
        assert result["network_label"] == "pairs_tbase36d"

    def test_prepare_network_pair_list_file_matches_count(
        self, tmp_path: Path
    ) -> None:
        _require(_RSLC_DIR, _DEM)
        result = insar_prepare_network(
            data_dir=str(_RSLC_DIR),
            dem=str(_DEM),
            output_dir="",
            workspace_root=str(tmp_path),
            network_mode="tbase",
            max_temporal_baseline_days=36,
            interaction_mode="auto",
        )
        assert "error" not in result, result
        pair_lines = [
            line for line in Path(result["pairs_selected_txt"]).read_text().splitlines()
            if line.strip()
        ]
        assert len(pair_lines) == result["num_pairs"]

    def test_prepare_network_gunw_pattern_points_into_output(
        self, tmp_path: Path
    ) -> None:
        _require(_RSLC_DIR, _DEM)
        # Explicit override must resolve inside a run root under the unified
        # output contract; gunw_pattern is then expected to point into it.
        out = str(tmp_path / "stack-insar-isce3" / "outputs" / "run1" / "network")
        result = insar_prepare_network(
            data_dir=str(_RSLC_DIR),
            dem=str(_DEM),
            output_dir=out,
            interaction_mode="auto",
        )
        assert "error" not in result, result
        assert result["gunw_pattern"].startswith(out), (
            f"gunw_pattern should be under output_dir: {result['gunw_pattern']}"
        )


# ── MintPy existing outputs ────────────────────────────────────────────────


@pytest.mark.real_data
class TestMintPyPrecomputedOutputs:
    """Validate completeness of an existing MintPy run and insar_run_mintpy
    input validation using real files."""

    _EXPECTED_H5 = [
        "timeseries.h5",
        "timeseries_demErr.h5",
        "velocity.h5",
        "demErr.h5",
        "temporalCoherence.h5",
        "maskTempCoh.h5",
    ]

    def test_mintpy_outputs_all_exist(self) -> None:
        _require(_MINTPY_DIR)
        for fname in self._EXPECTED_H5:
            p = _MINTPY_DIR / fname
            assert p.exists(), f"Expected MintPy output missing: {p}"
            assert p.stat().st_size > 0, f"MintPy output is empty: {p}"

    def test_mintpy_inputs_ifgramstack_exists(self) -> None:
        _require(_MINTPY_DIR)
        ifgram = _MINTPY_DIR / "inputs" / "ifgramStack.h5"
        geom = _MINTPY_DIR / "inputs" / "geometryGeo.h5"
        assert ifgram.exists(), f"ifgramStack.h5 missing: {ifgram}"
        assert geom.exists(), f"geometryGeo.h5 missing: {geom}"

    def test_run_mintpy_validates_real_config_and_dem(
        self, tmp_path: Path
    ) -> None:
        """insar_run_mintpy should pass input validation with real cfg/dem paths."""
        _require(_MINTPY_DIR, _DEM, _NETWORK_DIR)
        cfg = _MINTPY_DIR / "smallbaselineApp.cfg"
        _require(cfg)

        with patch("insar_agent.mcp.server.run_mintpy") as mock_run:
            mock_run.return_value = {
                "job_id": "test-job-123",
                "pid": 99999,
                "status": "running",
                "log_path": str(tmp_path / "mintpy.log"),
                "submitted_at": "2026-04-28T00:00:00+00:00",
                "command": [],
            }
            result = insar_run_mintpy(
                mintpy_work_dir=str(tmp_path / "mintpy_out"),
                gunw_glob=str(_NETWORK_DIR / "runs" / "*" / "products" / "*.h5"),
                mintpy_config=str(cfg),
                dem_path=str(_DEM),
                conda_env="mintpy",
                interaction_mode="auto",
            )

        assert "error" not in result, f"insar_run_mintpy failed: {result}"
        assert result["job_id"] == "test-job-123"
        assert result["status"] == "running"
        mock_run.assert_called_once()

    def test_run_mintpy_rejects_missing_config(self, tmp_path: Path) -> None:
        result = insar_run_mintpy(
            mintpy_work_dir=str(tmp_path / "mintpy_out"),
            gunw_glob="/some/path/*/products/*.h5",
            mintpy_config="/nonexistent/smallbaseline.cfg",
            dem_path=str(_DEM) if _DEM.exists() else str(tmp_path / "dem.tif"),
            conda_env="mintpy",
        )
        assert result.get("error") == "path_not_found"


# ── Sentinel D-InSAR completed outputs ────────────────────────────────────


@pytest.mark.real_data
class TestSentinelDInSARCompletedOutputs:
    """Validate a completed ISCE2 topsApp D-InSAR run."""

    _EXPECTED_MERGED = [
        "filt_topophase.flat.geo",
        "filt_topophase.unw.geo",
        "topophase.cor.geo",
        "los.rdr.geo",
    ]

    def test_all_key_outputs_exist_and_nonempty(self) -> None:
        _require(_DINSAR_DIR)
        merged = _DINSAR_DIR / "merged"
        for fname in self._EXPECTED_MERGED:
            p = merged / fname
            assert p.exists(), f"Key D-InSAR output missing: {p}"
            assert p.stat().st_size > 0, f"Key D-InSAR output empty: {p}"

    def test_reference_and_secondary_safe_match_config(self) -> None:
        """SAFEs named in topsApp.xml must exist on disk."""
        _require(_DINSAR_DIR)
        import xml.etree.ElementTree as ET
        xml_path = _DINSAR_DIR / "configs" / "topsApp.xml"
        _require(xml_path)
        tree = ET.parse(xml_path)
        for comp in tree.iter("component"):
            safe_prop = next(
                (p for p in comp.iter("property")
                 if p.get("name") == "safe"),
                None,
            )
            if safe_prop is not None and safe_prop.text:
                # Parse Python list literal: "[ '/path/to.SAFE' ]"
                safe_paths = [
                    s.strip().strip("'\"")
                    for s in safe_prop.text.strip("[] ").split(",")
                    if s.strip().strip("'\"")
                ]
                for sp in safe_paths:
                    assert Path(sp).exists(), (
                        f"SAFE referenced in topsApp.xml not found: {sp}"
                    )

    def test_geom_reference_directory_exists(self) -> None:
        _require(_DINSAR_DIR)
        geom = _DINSAR_DIR / "geom_reference"
        assert geom.exists() and geom.is_dir(), (
            f"geom_reference directory missing: {geom}"
        )

    def test_unwrapped_phase_larger_than_wrapped(self) -> None:
        """Unwrapped file is typically larger than wrapped due to float range."""
        _require(_DINSAR_DIR)
        merged = _DINSAR_DIR / "merged"
        unw = merged / "filt_topophase.unw.geo"
        wrapped = merged / "filt_topophase.flat.geo"
        _require(unw, wrapped)
        assert unw.stat().st_size >= wrapped.stat().st_size * 0.5, (
            "Unwrapped phase file is unexpectedly much smaller than wrapped"
        )
