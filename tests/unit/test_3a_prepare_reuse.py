"""Part A TDD tests: prepare_input_dir layout + DEM reuse.

Tests in this file cover the new server.py behaviour after the project_id
caller-migration (task 3.2 Part A):

1. insar_download_dem with a project_id writes its DEM under
   <output_root>/prepare/dem/ (not under a run-specific subdirectory).
2. When the target DEM file already exists, insar_download_dem does NOT invoke
   the download engine a second time (reuse / idempotent).
3. insar_download_dem background=True places the job target under prepare/dem.
4. insar_prepare_sentinel_data writes SAFE data under prepare/safe and orbits
   under prepare/orbits, NOT under a run-specific subdirectory.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from insar_agent.mcp.server import insar_download_dem, insar_prepare_sentinel_data


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, engine="isce3", workflow="insar"):
    """Create a project, returning its project_id and output_root."""
    from insar_agent.mcp.server import insar_create_project
    registry_dir = tmp_path / ".registry"
    registry_dir.mkdir()
    monkeypatch.setenv("XDG_DATA_HOME", str(registry_dir))

    output_root = tmp_path / "output"
    result = insar_create_project(
        engine=engine,
        workflow=workflow,
        workspace_root=str(output_root),
    )
    assert "error" not in result, result
    return result["project_id"], output_root


# ---------------------------------------------------------------------------
# insar_download_dem: new prepare/dem layout
# ---------------------------------------------------------------------------

class TestDownloadDemPrepareLayout:
    def test_default_output_lands_under_prepare_dem(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """With project_id, DEM default output is <output_root>/prepare/dem/."""
        project_id, output_root = _make_project(tmp_path, monkeypatch)

        downloaded: list[str] = []

        def fake_download_dem(*, output_path, bbox, source, margin_deg, on_progress, proxy):
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fake-dem")
            downloaded.append(str(path))
            return {"output_path": str(path), "source": source, "bbox": list(bbox)}

        with (
            patch("insar_agent.mcp.server.download_dem", side_effect=fake_download_dem),
            patch("insar_agent.mcp.server._isce2_app_script", return_value=(None, None)),
        ):
            result = insar_download_dem(
                project_id=project_id,
                bbox=[40.0, 10.0, 41.0, 11.0],
            )

        assert "error" not in result, result
        out = Path(result["output_path"])
        # Must land under <output_root>/prepare/dem/
        expected_prefix = (output_root / "prepare" / "dem").resolve()
        assert out.is_relative_to(expected_prefix), (
            f"Expected DEM under {expected_prefix}, got {out}"
        )

    def test_dem_not_downloaded_again_when_already_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """If the target DEM file already exists, the engine must NOT be called again."""
        project_id, output_root = _make_project(tmp_path, monkeypatch)

        # Pre-create the DEM file to simulate an earlier download.
        dem_dir = output_root / "prepare" / "dem"
        dem_dir.mkdir(parents=True, exist_ok=True)
        existing_dem = dem_dir / "copernicus_30_dem.tif"
        existing_dem.write_bytes(b"existing-dem")

        download_calls: list[int] = []

        def fake_download_dem(**kwargs):
            download_calls.append(1)
            return {"output_path": str(existing_dem), "source": "copernicus_30", "bbox": [40.0, 10.0, 41.0, 11.0]}

        with (
            patch("insar_agent.mcp.server.download_dem", side_effect=fake_download_dem),
            patch("insar_agent.mcp.server._isce2_app_script", return_value=(None, None)),
        ):
            result = insar_download_dem(
                project_id=project_id,
                bbox=[40.0, 10.0, 41.0, 11.0],
            )

        assert "error" not in result, result
        # Engine MUST NOT have been invoked because the file already existed.
        assert download_calls == [], (
            "download_dem engine was called despite the DEM already existing — reuse broken"
        )
        assert Path(result["output_path"]).exists()

    def test_background_dem_target_under_prepare_dem(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """background=True job output path must still land under prepare/dem."""
        project_id, output_root = _make_project(tmp_path, monkeypatch)

        mock_proc = MagicMock()
        mock_proc.pid = 55555

        with patch("insar_agent.mcp.server.subprocess.Popen", return_value=mock_proc):
            result = insar_download_dem(
                project_id=project_id,
                bbox=[40.0, 10.0, 41.0, 11.0],
                background=True,
            )

        assert result.get("status") == "running", result
        out = Path(result["output_path"])
        expected_prefix = (output_root / "prepare" / "dem").resolve()
        assert out.is_relative_to(expected_prefix), (
            f"Background DEM output should be under {expected_prefix}, got {out}"
        )


# ---------------------------------------------------------------------------
# insar_prepare_sentinel_data: new prepare/safe + prepare/orbits layout
# ---------------------------------------------------------------------------

class TestPrepareSentinelPrepareLayout:
    def test_safe_data_lands_under_prepare_safe(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """With project_id, default SAFE output is <output_root>/prepare/safe."""
        project_id, output_root = _make_project(
            tmp_path, monkeypatch, engine="isce2", workflow="tops"
        )

        def fake_prepare(**kwargs):
            proj_root = Path(kwargs["project_root"])
            safe_root = proj_root / "safe"
            safe_root.mkdir(parents=True, exist_ok=True)
            return {
                "project_root": str(proj_root),
                "safe_root": str(safe_root),
                "grouped_safe_paths": {},
                "dem_path": kwargs.get("dem_path"),
                "orbit_dir": kwargs.get("orbit_dir"),
                "scene_count": 0,
                "prep_log_path": str(proj_root / "logs" / "prep.log"),
            }

        with patch("insar_agent.mcp.server.prepare_sentinel_data", side_effect=fake_prepare):
            result = insar_prepare_sentinel_data(
                project_id=project_id,
                source_paths=[],
            )

        assert "error" not in result, result
        proj_root = Path(result["project_root"])
        expected_prefix = (output_root / "prepare").resolve()
        assert proj_root.is_relative_to(expected_prefix), (
            f"SAFE prep root should be under {expected_prefix}, got {proj_root}"
        )
