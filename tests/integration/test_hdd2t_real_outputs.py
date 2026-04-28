"""
Real-data integration tests using pre-processed outputs from HDD2T.

All tests here operate on existing artifacts — no expensive ISCE3/ISCE2
processing is triggered.  Runtime per test: < 30 seconds.

Data root: /mnt/HDD2T/August/inasr-agent-test/

Marker: @pytest.mark.real_data
"""

from __future__ import annotations

from pathlib import Path

import pytest

from insar_agent.mcp.server import (
    insar_describe_s1,
    insar_plot_baseline,
    insar_prepare_sentinel_data,
)

# ── Data paths ──────────────────────────────────────────────────────────────

_ROOT = Path("/mnt/HDD2T/August/inasr-agent-test")
_NETWORK_DIR = _ROOT / "isce3-network-real-20260403"
_SAFE_ASC = _ROOT / "safe" / "s1a_asc_rel014"
_SAFE_DESC = _ROOT / "safe" / "s1a_desc_rel079"
_BURST_MANIFEST = _ROOT / "temp" / "burst_manifest.txt"
_ORBIT_DIR = _ROOT / "temp" / "general" / "orbits"
_DEM_PATH = _ROOT / "dem-claude-test" / "dem.tif"


def _require(*paths: Path) -> None:
    for p in paths:
        if not p.exists():
            pytest.skip(f"Required path not found: {p}")


# ── insar_plot_baseline ───────────────────────────────────────────────────────


@pytest.mark.real_data
class TestPlotBaselineRealNetwork:
    """Validate insar_plot_baseline against the existing ISCE3 network."""

    def test_plot_baseline_produces_png_and_csv(self, tmp_path: Path) -> None:
        """
        insar_plot_baseline should read GUNW .h5 products from runs/ and
        produce PNG, PDF, and CSV files in the output directory.
        """
        _require(_NETWORK_DIR)
        result = insar_plot_baseline(
            network_dir=str(_NETWORK_DIR),
            interaction_mode="auto",
        )

        assert "error" not in result, f"plot_baseline failed: {result}"
        assert result.get("n_pairs", 0) > 0, "No pairs found"
        assert result.get("png_path") and Path(result["png_path"]).exists(), (
            f"PNG not produced: {result.get('png_path')}"
        )
        assert result.get("pair_csv") and Path(result["pair_csv"]).exists(), (
            f"CSV not produced: {result.get('pair_csv')}"
        )

    def test_plot_baseline_returns_expected_pair_count(self) -> None:
        """
        The network has 15 pairs; result should reflect a non-trivial baseline
        network spanning multiple scenes.
        """
        _require(_NETWORK_DIR)
        result = insar_plot_baseline(
            network_dir=str(_NETWORK_DIR),
            interaction_mode="auto",
        )
        assert "error" not in result, result
        assert result["n_pairs"] >= 5, (
            f"Expected ≥5 pairs, got {result['n_pairs']}"
        )

    def test_plot_baseline_custom_pair_list(self) -> None:
        """Using the tbase36d pair list produces a reduced baseline graph."""
        _require(_NETWORK_DIR)
        pair_list = _NETWORK_DIR / "pair_lists" / "pairs_tbase36d.txt"
        _require(pair_list)

        result = insar_plot_baseline(
            network_dir=str(_NETWORK_DIR),
            pair_list=str(pair_list),
            title="Short-baseline network (tbase≤36d)",
            interaction_mode="auto",
        )
        assert "error" not in result, result
        # tbase36d is a subset of all pairs
        full = insar_plot_baseline(
            network_dir=str(_NETWORK_DIR), interaction_mode="auto"
        )
        assert result["n_pairs"] <= full["n_pairs"]

    def test_plot_baseline_invalid_network_dir(self) -> None:
        result = insar_plot_baseline(
            network_dir="/nonexistent/path",
            interaction_mode="auto",
        )
        assert result.get("error") == "path_not_found"


# ── insar_describe_s1 ─────────────────────────────────────────────────────────


@pytest.mark.real_data
class TestDescribeS1RealSAFE:
    """Validate insar_describe_s1 against real Sentinel-1 .SAFE directories."""

    def test_describe_ascending_scene(self) -> None:
        """
        An ascending rel-014 scene should return correct pass direction,
        relative orbit, and dual-pol polarizations.
        """
        _require(_SAFE_ASC)
        safe_dirs = sorted(_SAFE_ASC.glob("S1?_IW_SLC__1S*.SAFE"))
        if not safe_dirs:
            pytest.skip("No .SAFE files in ascending directory")

        result = insar_describe_s1(zip_path=str(safe_dirs[0]))

        assert "error" not in result, f"describe_s1 failed: {result}"
        assert result["satellite"] in {"S1A", "S1B", "S1C"}
        assert result["pass_direction"] == "ASCENDING"
        assert result["relative_orbit"] == 14
        assert "VV" in result["polarizations"] or "VH" in result["polarizations"]
        assert result["mode"] == "IW"
        assert "start_time" in result
        assert "bbox" in result

    def test_describe_descending_scene(self) -> None:
        """A descending rel-079 scene should have correct pass direction and orbit."""
        _require(_SAFE_DESC)
        safe_dirs = sorted(_SAFE_DESC.glob("S1?_IW_SLC__1S*.SAFE"))
        if not safe_dirs:
            pytest.skip("No .SAFE files in descending directory")

        result = insar_describe_s1(zip_path=str(safe_dirs[0]))

        assert "error" not in result, f"describe_s1 failed: {result}"
        assert result["pass_direction"] == "DESCENDING"
        assert result["relative_orbit"] == 79

    def test_describe_two_scenes_have_same_orbit(self) -> None:
        """Two scenes from the same track share relative orbit and pass direction."""
        _require(_SAFE_ASC)
        safe_dirs = sorted(_SAFE_ASC.glob("S1?_IW_SLC__1S*.SAFE"))
        if len(safe_dirs) < 2:
            pytest.skip("Need ≥2 .SAFE files")

        r1 = insar_describe_s1(zip_path=str(safe_dirs[0]))
        r2 = insar_describe_s1(zip_path=str(safe_dirs[1]))

        assert r1["relative_orbit"] == r2["relative_orbit"]
        assert r1["pass_direction"] == r2["pass_direction"]
        assert r1["start_time"] < r2["start_time"], "Should be sorted chronologically"

    def test_describe_nonexistent_path(self) -> None:
        result = insar_describe_s1(zip_path="/nonexistent/S1A.SAFE")
        assert "error" in result


# ── insar_prepare_sentinel_data (burst manifest mode) ─────────────────────────


@pytest.mark.real_data
class TestPrepareSentinelBurstManifest:
    """
    Validate the burst-manifest mode of insar_prepare_sentinel_data.

    The burst manifest at temp/burst_manifest.txt lists tiff/xml paths for
    multiple S1A scenes in IW2 subswath. The MCP tool should synthesise
    lightweight .SAFE directories from these burst files.
    """

    def test_burst_manifest_produces_grouped_safe_paths(
        self, tmp_path: Path
    ) -> None:
        """
        Providing a burst_manifest should produce grouped_safe_paths with
        ≥2 scene groups even though no full .zip SAFE archives are used.
        """
        _require(_BURST_MANIFEST)

        result = insar_prepare_sentinel_data(
            project_root=str(tmp_path),
            mode="burst",
            burst_manifest=str(_BURST_MANIFEST),
            download_dem=False,
            download_orbits=False,
        )

        assert "error" not in result, f"prepare failed: {result}"
        assert result.get("grouped_safe_paths"), "grouped_safe_paths is empty"
        total_scenes = sum(
            len(v) for v in result["grouped_safe_paths"].values()
        )
        assert total_scenes >= 2, f"Expected ≥2 scenes, got {total_scenes}"

    def test_burst_manifest_scene_ids_match_burst_dirs(
        self, tmp_path: Path
    ) -> None:
        """Scene IDs returned should correspond to actual S1A scene directories."""
        _require(_BURST_MANIFEST)

        result = insar_prepare_sentinel_data(
            project_root=str(tmp_path),
            mode="burst",
            burst_manifest=str(_BURST_MANIFEST),
            download_dem=False,
            download_orbits=False,
        )
        assert "error" not in result, result

        burst_root = _ROOT / "bursts"
        for _track, paths in result["grouped_safe_paths"].items():
            for safe_path in paths:
                scene_id = Path(safe_path).stem  # strip .SAFE suffix if present
                matching = list(burst_root.glob(f"{scene_id}*"))
                assert matching, (
                    f"No burst directory found for scene_id={scene_id!r}"
                )
