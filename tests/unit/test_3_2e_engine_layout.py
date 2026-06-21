"""Task 3.2e TDD tests: ENGINE migration to new flat layout.

Tests in this file verify three behaviours after the engine-level migration:

1. materialize_dem_for_tops writes DEM under <output_root>/prepare/dem/
   AND reuses an existing DEM (underlying materialize/copy is NOT called again).
2. isce2 mintpy puts logs under <run_root>/insar_product/logs and
   jobs under <run_root>/.insar_agent/jobs.
3. isce3 mintpy puts logs under <run_root>/insar_product/logs and
   jobs under <run_root>/.insar_agent/jobs.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_dem_source(tmp_path: Path, name: str = "dem.tif") -> Path:
    """Create a fake DEM with .xml and .vrt sidecars, return the main file path."""
    source = tmp_path / "source" / name
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"dem-bytes")

    xml_content = """<image_name>
    <property name="file_name">
        <value>/stale/path/dem.tif</value>
    </property>
</image_name>
"""
    source.with_suffix(source.suffix + ".xml").write_text(xml_content, encoding="utf-8")

    vrt_content = """<VRTDataset rasterXSize="1" rasterYSize="1">
    <VRTRasterBand dataType="Float32" band="1" subClass="VRTRawRasterBand">
        <SourceFilename relativeToVRT="1">dem.tif</SourceFilename>
    </VRTRasterBand>
</VRTDataset>
"""
    source.with_suffix(source.suffix + ".vrt").write_text(vrt_content, encoding="utf-8")
    return source


def _make_stack_root(root: Path) -> Path:
    """Create a minimal topsStack directory structure for mintpy tests."""
    import numpy as np

    (root / "reference").mkdir(parents=True, exist_ok=True)
    (root / "reference" / "IW2.xml").write_text("<xml />", encoding="utf-8")
    (root / "merged" / "interferograms" / "20260105_20260117").mkdir(
        parents=True, exist_ok=True
    )
    (root / "merged" / "geom_reference").mkdir(parents=True, exist_ok=True)

    base_dir = root / "merged" / "baselines"
    for date, value in {"20260105": 0.0, "20260117": 1.0}.items():
        d = base_dir / date
        d.mkdir(parents=True, exist_ok=True)
        raw = d / date
        np.asarray([value] * 36, dtype=np.float32).tofile(raw)
        xml_path = raw.with_suffix(raw.suffix + ".xml")
        xml_path.write_text(
            f"""<imageFile>
    <property name="width"><value>9</value></property>
    <property name="length"><value>4</value></property>
</imageFile>
""",
            encoding="utf-8",
        )
    return root


# ---------------------------------------------------------------------------
# 1. materialize_dem_for_tops — new layout: <output_root>/prepare/dem/
# ---------------------------------------------------------------------------

class TestMaterializeDemForTopsNewLayout:
    def test_dem_materializes_under_prepare_dem(self, tmp_path: Path) -> None:
        """materialize_dem_for_tops must write under <output_root>/prepare/dem/."""
        from insar_agent.engines.isce2.runner import materialize_dem_for_tops

        source = _make_dem_source(tmp_path)
        output_root = tmp_path / "output"

        result = materialize_dem_for_tops(str(source), output_root=str(output_root))

        result_path = Path(result)
        expected_parent = (output_root / "prepare" / "dem").resolve()
        assert result_path.is_relative_to(expected_parent), (
            f"Expected DEM materialized under {expected_parent}, got {result_path}"
        )

    def test_dem_xml_updated_with_new_path(self, tmp_path: Path) -> None:
        """The materialized .xml must reference the new target path."""
        from insar_agent.engines.isce2.runner import materialize_dem_for_tops

        source = _make_dem_source(tmp_path)
        output_root = tmp_path / "output"

        result = materialize_dem_for_tops(str(source), output_root=str(output_root))

        xml_path = Path(result + ".xml")
        assert xml_path.exists(), "Materialized .xml sidecar must exist"
        xml_text = xml_path.read_text(encoding="utf-8")
        assert f"<value>{result}</value>" in xml_text, (
            f"xml sidecar must reference the new target path {result}"
        )

    def test_dem_reuses_existing_without_calling_materialize_again(
        self, tmp_path: Path
    ) -> None:
        """If the target DEM already exists under prepare/dem, materialize_dem_for_tops
        must return the existing path WITHOUT touching sidecar files (idempotent reuse)."""
        from insar_agent.engines.isce2.runner import materialize_dem_for_tops

        source = _make_dem_source(tmp_path)
        output_root = tmp_path / "output"

        # First call — creates the sidecar files (.xml, .vrt) under prepare/dem/.
        # Note: materialize_dem_for_tops writes sidecars but not the main binary file;
        # the VRT sidecar points at the original source path.
        first_result = materialize_dem_for_tops(str(source), output_root=str(output_root))
        xml_after_first = Path(first_result + ".xml")
        assert xml_after_first.exists(), "First call must materialise the .xml sidecar"

        # Record mtime before second call.
        xml_mtime_before = xml_after_first.stat().st_mtime
        vrt_mtime_before = (Path(first_result + ".vrt")).stat().st_mtime

        # Second call — DEM already exists, must reuse.
        second_result = materialize_dem_for_tops(str(source), output_root=str(output_root))

        assert second_result == first_result, "Reuse must return the same path"
        # Sidecars must NOT have been rewritten.
        assert (Path(second_result + ".xml")).stat().st_mtime == xml_mtime_before, (
            "xml sidecar was rewritten on second call — reuse broken"
        )
        assert (Path(second_result + ".vrt")).stat().st_mtime == vrt_mtime_before, (
            "vrt sidecar was rewritten on second call — reuse broken"
        )


# ---------------------------------------------------------------------------
# 2. isce2 mintpy — logs under insar_product/logs, jobs under .insar_agent/jobs
# ---------------------------------------------------------------------------

class TestISCE2MintpyRunLayout:
    def test_logs_land_under_insar_product_logs(self, tmp_path: Path) -> None:
        """run_mintpy_isce2_stack: log file must be under <mintpy_work_dir>/insar_product/logs/."""
        from insar_agent.engines.isce2.mintpy import run_mintpy_isce2_stack

        stack = _make_stack_root(tmp_path / "stack")
        mintpy_work_dir = tmp_path / "output" / "d-insar-isce2_run1"
        fake_script = tmp_path / "fake_mintpy.sh"
        fake_script.write_text("#!/bin/bash\n", encoding="utf-8")
        mock_proc = MagicMock()
        mock_proc.pid = 1234

        with (
            patch("insar_agent.engines.isce2.mintpy._SCRIPT", fake_script),
            patch("subprocess.Popen", return_value=mock_proc),
        ):
            result = run_mintpy_isce2_stack(
                mintpy_work_dir=str(mintpy_work_dir),
                stack_work_dir=str(stack),
                conda_env="isce2",
            )

        log_path = Path(result["log_path"])
        expected_logs_dir = (mintpy_work_dir / "insar_product" / "logs").resolve()
        assert log_path.is_relative_to(expected_logs_dir), (
            f"isce2 mintpy log must be under <work_dir>/insar_product/logs, got {log_path}"
        )

    def test_job_json_lands_under_insar_agent_jobs(self, tmp_path: Path) -> None:
        """run_mintpy_isce2_stack: job JSON must be under <mintpy_work_dir>/.insar_agent/jobs/."""
        from insar_agent.engines.isce2.mintpy import run_mintpy_isce2_stack

        stack = _make_stack_root(tmp_path / "stack")
        mintpy_work_dir = tmp_path / "output" / "d-insar-isce2_run1"
        fake_script = tmp_path / "fake_mintpy.sh"
        fake_script.write_text("#!/bin/bash\n", encoding="utf-8")
        mock_proc = MagicMock()
        mock_proc.pid = 5678

        with (
            patch("insar_agent.engines.isce2.mintpy._SCRIPT", fake_script),
            patch("subprocess.Popen", return_value=mock_proc),
        ):
            result = run_mintpy_isce2_stack(
                mintpy_work_dir=str(mintpy_work_dir),
                stack_work_dir=str(stack),
                conda_env="isce2",
            )

        job_id = result["job_id"]
        expected_jobs_dir = (mintpy_work_dir / ".insar_agent" / "jobs").resolve()
        job_file = expected_jobs_dir / f"{job_id}.json"
        assert job_file.exists(), (
            f"isce2 mintpy job JSON must be under <work_dir>/.insar_agent/jobs/, "
            f"expected {job_file}"
        )

    def test_legacy_dot_jobs_dir_not_used(self, tmp_path: Path) -> None:
        """run_mintpy_isce2_stack must NOT write job JSON to <work_dir>/.jobs/."""
        from insar_agent.engines.isce2.mintpy import run_mintpy_isce2_stack

        stack = _make_stack_root(tmp_path / "stack")
        mintpy_work_dir = tmp_path / "output" / "d-insar-isce2_run1"
        fake_script = tmp_path / "fake_mintpy.sh"
        fake_script.write_text("#!/bin/bash\n", encoding="utf-8")
        mock_proc = MagicMock()
        mock_proc.pid = 9999

        with (
            patch("insar_agent.engines.isce2.mintpy._SCRIPT", fake_script),
            patch("subprocess.Popen", return_value=mock_proc),
        ):
            result = run_mintpy_isce2_stack(
                mintpy_work_dir=str(mintpy_work_dir),
                stack_work_dir=str(stack),
                conda_env="isce2",
            )

        legacy_jobs_dir = mintpy_work_dir / ".jobs"
        assert not legacy_jobs_dir.exists(), (
            f"isce2 mintpy must NOT use legacy .jobs dir {legacy_jobs_dir}"
        )


# ---------------------------------------------------------------------------
# 3. isce3 mintpy — logs under insar_product/logs, jobs under .insar_agent/jobs
# ---------------------------------------------------------------------------

def _make_fake_dem(tmp_path: Path) -> Path:
    dem = tmp_path / "dem.tif"
    dem.write_bytes(b"fake-dem")
    return dem


class TestISCE3MintpyRunLayout:
    def test_logs_land_under_insar_product_logs(self, tmp_path: Path) -> None:
        """isce3 run_mintpy: log file must be under <mintpy_work_dir>/insar_product/logs/."""
        from insar_agent.engines.isce3.mintpy import run_mintpy

        dem = _make_fake_dem(tmp_path)
        mintpy_work_dir = tmp_path / "output" / "d-insar-isce3_run1"
        fake_script = tmp_path / "fake_mintpy.sh"
        fake_script.write_text("#!/bin/bash\n", encoding="utf-8")
        mock_proc = MagicMock()
        mock_proc.pid = 2222

        with (
            patch("insar_agent.engines.isce3.mintpy._SCRIPT", fake_script),
            patch("subprocess.Popen", return_value=mock_proc),
        ):
            result = run_mintpy(
                mintpy_work_dir=str(mintpy_work_dir),
                gunw_glob="/fake/path/*.h5",
                mintpy_config=None,
                dem_path=str(dem),
                conda_env="isce3",
            )

        log_path = Path(result["log_path"])
        expected_logs_dir = (mintpy_work_dir / "insar_product" / "logs").resolve()
        assert log_path.is_relative_to(expected_logs_dir), (
            f"isce3 mintpy log must be under <work_dir>/insar_product/logs, got {log_path}"
        )

    def test_job_json_lands_under_insar_agent_jobs(self, tmp_path: Path) -> None:
        """isce3 run_mintpy: job JSON must be under <mintpy_work_dir>/.insar_agent/jobs/."""
        from insar_agent.engines.isce3.mintpy import run_mintpy

        dem = _make_fake_dem(tmp_path)
        mintpy_work_dir = tmp_path / "output" / "d-insar-isce3_run1"
        fake_script = tmp_path / "fake_mintpy.sh"
        fake_script.write_text("#!/bin/bash\n", encoding="utf-8")
        mock_proc = MagicMock()
        mock_proc.pid = 3333

        with (
            patch("insar_agent.engines.isce3.mintpy._SCRIPT", fake_script),
            patch("subprocess.Popen", return_value=mock_proc),
        ):
            result = run_mintpy(
                mintpy_work_dir=str(mintpy_work_dir),
                gunw_glob="/fake/path/*.h5",
                mintpy_config=None,
                dem_path=str(dem),
                conda_env="isce3",
            )

        job_id = result["job_id"]
        expected_jobs_dir = (mintpy_work_dir / ".insar_agent" / "jobs").resolve()
        job_file = expected_jobs_dir / f"{job_id}.json"
        assert job_file.exists(), (
            f"isce3 mintpy job JSON must be under <work_dir>/.insar_agent/jobs/, "
            f"expected {job_file}"
        )

    def test_legacy_dot_jobs_dir_not_used(self, tmp_path: Path) -> None:
        """isce3 run_mintpy must NOT write job JSON to <work_dir>/.jobs/."""
        from insar_agent.engines.isce3.mintpy import run_mintpy

        dem = _make_fake_dem(tmp_path)
        mintpy_work_dir = tmp_path / "output" / "d-insar-isce3_run1"
        fake_script = tmp_path / "fake_mintpy.sh"
        fake_script.write_text("#!/bin/bash\n", encoding="utf-8")
        mock_proc = MagicMock()
        mock_proc.pid = 4444

        with (
            patch("insar_agent.engines.isce3.mintpy._SCRIPT", fake_script),
            patch("subprocess.Popen", return_value=mock_proc),
        ):
            result = run_mintpy(
                mintpy_work_dir=str(mintpy_work_dir),
                gunw_glob="/fake/path/*.h5",
                mintpy_config=None,
                dem_path=str(dem),
                conda_env="isce3",
            )

        legacy_jobs_dir = mintpy_work_dir / ".jobs"
        assert not legacy_jobs_dir.exists(), (
            f"isce3 mintpy must NOT use legacy .jobs dir {legacy_jobs_dir}"
        )


# ---------------------------------------------------------------------------
# 4. mintpy_work_dir nested at <run_root>/insar_product/mintpy (the real layout):
#    jobs/logs must resolve to the RUN ROOT, NOT nest a second insar_product/
#    under mintpy/.  Regression for E1 (stack-insar-isce2) where the mintpy job
#    wrote logs to mintpy/insar_product/logs and state to mintpy/.insar_agent.
# ---------------------------------------------------------------------------

def _make_run_root_marker(run_root: Path, task: str, run_id: str) -> None:
    """Create the .insar_agent/project.json marker that find_run_root keys on."""
    marker = run_root / ".insar_agent" / "project.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps({"output_root": str(run_root.parent), "task": task, "run_id": run_id}),
        encoding="utf-8",
    )


class TestMintpyDeepWorkDirResolvesRunRoot:
    def test_isce2_jobs_and_logs_land_at_run_root(self, tmp_path: Path) -> None:
        from insar_agent.engines.isce2.mintpy import run_mintpy_isce2_stack
        from insar_agent.engines.isce3.mintpy import get_mintpy_status

        run_root = tmp_path / "e1" / "stack-insar-isce2_run1"
        _make_run_root_marker(run_root, "stack-insar-isce2", "stack-insar-isce2_run1")
        mintpy_work_dir = run_root / "insar_product" / "mintpy"
        stack = _make_stack_root(tmp_path / "stack")
        fake_script = tmp_path / "fake_mintpy.sh"
        fake_script.write_text("#!/bin/bash\n", encoding="utf-8")
        mock_proc = MagicMock()
        mock_proc.pid = 4321

        with (
            patch("insar_agent.engines.isce2.mintpy._SCRIPT", fake_script),
            patch("subprocess.Popen", return_value=mock_proc),
        ):
            result = run_mintpy_isce2_stack(
                mintpy_work_dir=str(mintpy_work_dir),
                stack_work_dir=str(stack),
                conda_env="isce2",
            )

        job_id = result["job_id"]
        log_path = Path(result["log_path"])
        assert log_path.parent == (run_root / "insar_product" / "logs"), (
            f"log must be at <run_root>/insar_product/logs, got {log_path}"
        )
        assert "mintpy/insar_product" not in log_path.as_posix(), (
            f"log must NOT nest insar_product under mintpy/, got {log_path}"
        )
        job_file = run_root / ".insar_agent" / "jobs" / f"{job_id}.json"
        assert job_file.exists(), (
            f"job JSON must be at <run_root>/.insar_agent/jobs, expected {job_file}"
        )
        assert not (mintpy_work_dir / ".insar_agent").exists(), (
            "must NOT create .insar_agent under mintpy_work_dir"
        )
        # write/read consistency: status reader finds the job from the same work_dir
        status = get_mintpy_status(job_id=job_id, mintpy_work_dir=str(mintpy_work_dir))
        assert status["job_id"] == job_id

    def test_isce3_jobs_and_logs_land_at_run_root(self, tmp_path: Path) -> None:
        from insar_agent.engines.isce3.mintpy import run_mintpy, get_mintpy_status

        run_root = tmp_path / "e3" / "d-insar-isce3_run1"
        _make_run_root_marker(run_root, "d-insar-isce3", "d-insar-isce3_run1")
        mintpy_work_dir = run_root / "insar_product" / "mintpy"
        dem = _make_fake_dem(tmp_path)
        fake_script = tmp_path / "fake_mintpy3.sh"
        fake_script.write_text("#!/bin/bash\n", encoding="utf-8")
        mock_proc = MagicMock()
        mock_proc.pid = 8765

        with (
            patch("insar_agent.engines.isce3.mintpy._SCRIPT", fake_script),
            patch("subprocess.Popen", return_value=mock_proc),
        ):
            result = run_mintpy(
                mintpy_work_dir=str(mintpy_work_dir),
                gunw_glob="/fake/path/*.h5",
                mintpy_config=None,
                dem_path=str(dem),
                conda_env="isce3",
            )

        job_id = result["job_id"]
        log_path = Path(result["log_path"])
        assert log_path.parent == (run_root / "insar_product" / "logs"), (
            f"log must be at <run_root>/insar_product/logs, got {log_path}"
        )
        assert "mintpy/insar_product" not in log_path.as_posix(), (
            f"log must NOT nest insar_product under mintpy/, got {log_path}"
        )
        job_file = run_root / ".insar_agent" / "jobs" / f"{job_id}.json"
        assert job_file.exists(), (
            f"job JSON must be at <run_root>/.insar_agent/jobs, expected {job_file}"
        )
        assert not (mintpy_work_dir / ".insar_agent").exists(), (
            "must NOT create .insar_agent under mintpy_work_dir"
        )
        status = get_mintpy_status(job_id=job_id, mintpy_work_dir=str(mintpy_work_dir))
        assert status["job_id"] == job_id
