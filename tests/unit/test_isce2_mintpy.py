"""Unit tests for ISCE2 Sentinel MintPy launcher/tooling."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from insar_agent.engines.isce2.mintpy import (
    export_mintpy_tops_baselines,
    run_mintpy_isce2_stack,
)
from insar_agent.mcp.server import insar_run_mintpy_isce2


def _make_stack_root(root: Path) -> Path:
    (root / "reference").mkdir(parents=True, exist_ok=True)
    (root / "reference" / "IW2.xml").write_text("<xml />", encoding="utf-8")
    (root / "merged" / "interferograms" / "20260105_20260117").mkdir(parents=True, exist_ok=True)
    (root / "merged" / "geom_reference").mkdir(parents=True, exist_ok=True)
    base_dir = root / "merged" / "baselines"
    for date, value in {"20260105": 0.0, "20260117": 1.0}.items():
        d = base_dir / date
        d.mkdir(parents=True, exist_ok=True)
        raw = d / date
        import numpy as np
        np.asarray([value] * 36, dtype=np.float32).tofile(raw)
        _write_isce_image_xml(raw, width=9, length=4)
    return root


def _write_isce_image_xml(path: Path, width: int, length: int) -> None:
    xml = f"""<imageFile>
    <property name=\"width\"><value>{width}</value></property>
    <property name=\"length\"><value>{length}</value></property>
</imageFile>
"""
    path.with_suffix(path.suffix + ".xml").write_text(xml, encoding="utf-8")


class TestRunMintpyISCE2Stack:
    def test_export_mintpy_tops_baselines_creates_pair_texts(self, tmp_path: Path) -> None:
        stack = _make_stack_root(tmp_path / "stack")
        base_dir = stack / "merged" / "baselines"
        for date, values in {
            "20260105": [0.0] * 36,
            "20260117": [10.0] * 36,
            "20260129": [-5.0] * 36,
        }.items():
            d = base_dir / date
            d.mkdir(parents=True, exist_ok=True)
            raw = d / date
            import numpy as np
            np.asarray(values, dtype=np.float32).tofile(raw)
            _write_isce_image_xml(raw, width=9, length=4)

        out = export_mintpy_tops_baselines(stack)
        assert out == stack / "merged" / "baselines_txt"
        assert (out / "20260105_20260117" / "20260105_20260117.txt").exists()
        assert (out / "20260105_20260129" / "20260105_20260129.txt").exists()
        txt = (out / "20260105_20260117" / "20260105_20260117.txt").read_text(encoding="utf-8")
        assert "Bperp (average): 10.0" in txt

    def test_missing_stack_dir_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            run_mintpy_isce2_stack(
                mintpy_work_dir=str(tmp_path / "mintpy"),
                stack_work_dir=str(tmp_path / "no_such_stack"),
                conda_env="mintpy",
            )

    def test_missing_script_raises(self, tmp_path: Path) -> None:
        stack = _make_stack_root(tmp_path / "stack")
        with patch("insar_agent.engines.isce2.mintpy._SCRIPT", tmp_path / "no_script.sh"):
            with pytest.raises(FileNotFoundError, match="MintPy script"):
                run_mintpy_isce2_stack(
                    mintpy_work_dir=str(tmp_path / "mintpy"),
                    stack_work_dir=str(stack),
                    conda_env="mintpy",
                )

    def test_job_json_written_on_launch(self, tmp_path: Path) -> None:
        stack = _make_stack_root(tmp_path / "stack")
        fake_script = tmp_path / "run_mintpy_isce2_stack.sh"
        fake_script.write_text("#!/bin/bash\n", encoding="utf-8")
        mock_proc = MagicMock()
        mock_proc.pid = 4242

        with patch("insar_agent.engines.isce2.mintpy._SCRIPT", fake_script), \
             patch("subprocess.Popen", return_value=mock_proc):
            result = run_mintpy_isce2_stack(
                mintpy_work_dir=str(tmp_path / "mintpy"),
                stack_work_dir=str(stack),
                conda_env="mintpy",
            )

        job_file = tmp_path / "mintpy" / ".jobs" / f"{result['job_id']}.json"
        assert job_file.exists()
        data = json.loads(job_file.read_text())
        assert data["pid"] == 4242
        assert Path(data["mintpy_config"]).exists()
        template = Path(data["mintpy_config"]).read_text(encoding="utf-8")
        assert "mintpy.load.processor = isce" in template
        assert "merged/interferograms/*/filt_fine.unw" in template
        assert "merged/baselines_txt" in template
        assert "mintpy.troposphericDelay.method = no" in template
        assert "mintpy.topographicResidual = no" in template

    def test_launch_passes_prep_isce_env_override(self, tmp_path: Path) -> None:
        stack = _make_stack_root(tmp_path / "stack")
        fake_script = tmp_path / "run_mintpy_isce2_stack.sh"
        fake_script.write_text("#!/bin/bash\n", encoding="utf-8")
        mock_proc = MagicMock()
        mock_proc.pid = 77

        with patch("insar_agent.engines.isce2.mintpy._SCRIPT", fake_script), \
             patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            run_mintpy_isce2_stack(
                mintpy_work_dir=str(tmp_path / "mintpy"),
                stack_work_dir=str(stack),
                conda_env="mintpy",
                prep_isce_env="isce2",
            )

        _, kwargs = mock_popen.call_args
        assert kwargs["env"]["PREP_ISCE_ENV"] == "isce2"


class TestInsarRunMintpyISCE2:
    def test_missing_stack_dir_returns_path_not_found(self, tmp_path: Path) -> None:
        result = insar_run_mintpy_isce2(
            mintpy_work_dir=str(tmp_path / "mintpy"),
            stack_work_dir=str(tmp_path / "no_such_stack"),
            conda_env="mintpy",
        )
        assert result["error"] == "path_not_found"

    def test_success_returns_job_and_poll(self, tmp_path: Path) -> None:
        stack = _make_stack_root(tmp_path / "stack")
        fake = {
            "job_id": "job-1",
            "pid": 123,
            "status": "running",
            "log_path": "/tmp/mintpy.log",
            "submitted_at": "2026-01-01T00:00:00+00:00",
            "mintpy_config": "/tmp/isce2_stack.txt",
        }
        with patch("insar_agent.mcp.server.run_mintpy_isce2_stack", return_value=fake):
            result = insar_run_mintpy_isce2(
                mintpy_work_dir=str(tmp_path / "mintpy"),
                stack_work_dir=str(stack),
                conda_env="mintpy",
                interaction_mode="auto",
            )

        assert result["job_id"] == "job-1"
        assert result["interaction_mode"] == "auto"
        assert "insar_get_job" in result["poll"]
        assert str(tmp_path / "mintpy") in result["poll"]

    def test_success_passes_prep_env_override(self, tmp_path: Path) -> None:
        stack = _make_stack_root(tmp_path / "stack")
        fake = {
            "job_id": "job-1",
            "pid": 123,
            "status": "running",
            "log_path": "/tmp/mintpy.log",
            "submitted_at": "2026-01-01T00:00:00+00:00",
            "mintpy_config": "/tmp/isce2_stack.txt",
        }
        with patch("insar_agent.mcp.server.run_mintpy_isce2_stack", return_value=fake) as mock_run:
            insar_run_mintpy_isce2(
                mintpy_work_dir=str(tmp_path / "mintpy"),
                stack_work_dir=str(stack),
                conda_env="mintpy",
                prep_isce_env="isce2",
            )

        _, kwargs = mock_run.call_args
        assert kwargs["prep_isce_env"] == "isce2"
