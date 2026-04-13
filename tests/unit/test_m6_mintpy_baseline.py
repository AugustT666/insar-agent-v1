"""Unit tests for M6: MintPy launcher and baseline network tools."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from insar_agent.engines.isce3.mintpy import get_mintpy_status, run_mintpy
from insar_agent.mcp.server import (
    insar_get_mintpy_status,
    insar_plot_baseline,
    insar_run_mintpy,
)


# ── run_mintpy engine tests ───────────────────────────────────────────────────

class TestRunMintpy:
    def test_missing_config_raises(self, tmp_path):
        dem = tmp_path / "dem.tif"
        dem.write_bytes(b"")
        with pytest.raises(FileNotFoundError, match="config"):
            run_mintpy(
                mintpy_work_dir=str(tmp_path / "work"),
                gunw_glob="/data/runs/*/products/*.h5",
                mintpy_config=str(tmp_path / "no_such.cfg"),
                dem_path=str(dem),
                conda_env="mintpy",
            )

    def test_missing_dem_raises(self, tmp_path):
        cfg = tmp_path / "mintpy.cfg"
        cfg.write_text("")
        with pytest.raises(FileNotFoundError, match="dem"):
            run_mintpy(
                mintpy_work_dir=str(tmp_path / "work"),
                gunw_glob="/data/runs/*/products/*.h5",
                mintpy_config=str(cfg),
                dem_path=str(tmp_path / "no_dem.tif"),
                conda_env="mintpy",
            )

    def test_missing_script_raises(self, tmp_path):
        cfg = tmp_path / "mintpy.cfg"
        cfg.write_text("")
        dem = tmp_path / "dem.tif"
        dem.write_bytes(b"")

        with patch("insar_agent.engines.isce3.mintpy._SCRIPT", tmp_path / "no_script.sh"):
            with pytest.raises(FileNotFoundError, match="MintPy script"):
                run_mintpy(
                    mintpy_work_dir=str(tmp_path / "work"),
                    gunw_glob="/data/runs/*/products/*.h5",
                    mintpy_config=str(cfg),
                    dem_path=str(dem),
                    conda_env="mintpy",
                )

    def test_job_json_written_on_launch(self, tmp_path):
        (tmp_path / ".insar_logs").mkdir()
        cfg = tmp_path / "mintpy.cfg"
        cfg.write_text("")
        dem = tmp_path / "dem.tif"
        dem.write_bytes(b"")

        fake_script = tmp_path / "run_mintpy_nisar_stack.sh"
        fake_script.write_text("#!/bin/bash\nsleep 0\n")

        mock_proc = MagicMock()
        mock_proc.pid = 99999

        with patch("insar_agent.engines.isce3.mintpy._SCRIPT", fake_script), \
             patch("subprocess.Popen", return_value=mock_proc):
            result = run_mintpy(
                mintpy_work_dir=str(tmp_path / "work"),
                gunw_glob="/data/runs/*/products/*.h5",
                mintpy_config=str(cfg),
                dem_path=str(dem),
                conda_env="mintpy",
            )

        job_id = result["job_id"]
        assert result["status"] == "running"
        assert result["pid"] == 99999

        # job JSON persisted
        job_file = tmp_path / "work" / ".jobs" / f"{job_id}.json"
        assert job_file.exists()
        data = json.loads(job_file.read_text())
        assert data["job_id"] == job_id
        assert data["pid"] == 99999

        # log file created
        assert Path(result["log_path"]).parent == tmp_path / ".insar_logs"
        assert Path(result["log_path"]).parent.exists()

    def test_command_includes_dem_as_4th_arg(self, tmp_path):
        cfg = tmp_path / "mintpy.cfg"
        cfg.write_text("")
        dem = tmp_path / "dem.tif"
        dem.write_bytes(b"")

        fake_script = tmp_path / "run_mintpy_nisar_stack.sh"
        fake_script.write_text("#!/bin/bash\n")

        mock_proc = MagicMock()
        mock_proc.pid = 1

        with patch("insar_agent.engines.isce3.mintpy._SCRIPT", fake_script), \
             patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            run_mintpy(
                mintpy_work_dir=str(tmp_path / "work"),
                gunw_glob="/data/*.h5",
                mintpy_config=str(cfg),
                dem_path=str(dem),
                conda_env="myenv",
            )

        call_args = mock_popen.call_args[0][0]  # positional command list
        # DEM must be last positional arg to the bash script
        assert str(dem) in call_args
        assert "myenv" in call_args

    def test_command_includes_env_overrides(self, tmp_path):
        cfg = tmp_path / "mintpy.cfg"
        cfg.write_text("")
        dem = tmp_path / "dem.tif"
        dem.write_bytes(b"")

        fake_script = tmp_path / "run_mintpy_nisar_stack.sh"
        fake_script.write_text("#!/bin/bash\n")

        mock_proc = MagicMock()
        mock_proc.pid = 7

        with patch("insar_agent.engines.isce3.mintpy._SCRIPT", fake_script), \
             patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            run_mintpy(
                mintpy_work_dir=str(tmp_path / "work"),
                gunw_glob="/data/*.h5",
                mintpy_config=str(cfg),
                dem_path=str(dem),
                conda_env="myenv",
                python_bin="/opt/py",
                smallbaseline_bin="/opt/smallbaselineApp.py",
            )

        _, kwargs = mock_popen.call_args
        assert kwargs["env"]["PYTHON_BIN"] == "/opt/py"
        assert kwargs["env"]["SMALLBASELINE_BIN"] == "/opt/smallbaselineApp.py"


# ── get_mintpy_status engine tests ───────────────────────────────────────────

class TestGetMintpyStatus:
    def _write_job(self, jobs_dir: Path, job_id: str, pid: int, status: str = "running") -> None:
        jobs_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "job_id": job_id,
            "pid": pid,
            "status": status,
            "log_path": "",
            "submitted_at": "2026-01-01T00:00:00+00:00",
            "finished_at": None,
        }
        (jobs_dir / f"{job_id}.json").write_text(json.dumps(data))

    def test_job_not_found_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            get_mintpy_status("no-such-id", str(tmp_path))

    def test_running_pid_alive_returns_running(self, tmp_path):
        self._write_job(tmp_path / ".jobs", "job1", pid=os.getpid())
        result = get_mintpy_status("job1", str(tmp_path))
        assert result["status"] == "running"

    def test_dead_pid_success_returns_done(self, tmp_path):
        log = tmp_path / "ok.log"
        log.write_text("Resuming MintPy from correct_unwrap_error\nDone.\n")
        jobs_dir = tmp_path / ".jobs"
        jobs_dir.mkdir()
        data = {
            "job_id": "job2", "pid": 99999999,
            "status": "running", "log_path": str(log),
            "submitted_at": "2026-01-01T00:00:00+00:00", "finished_at": None,
        }
        (jobs_dir / "job2.json").write_text(json.dumps(data))

        with patch("os.kill", side_effect=ProcessLookupError):
            result = get_mintpy_status("job2", str(tmp_path))

        assert result["status"] == "done"
        assert result["finished_at"] is not None

    def test_dead_pid_error_in_log_returns_failed(self, tmp_path):
        log = tmp_path / "fail.log"
        log.write_text("Running MintPy...\nError: something went wrong\nTraceback: foo\n")
        jobs_dir = tmp_path / ".jobs"
        jobs_dir.mkdir()
        data = {
            "job_id": "job3", "pid": 99999999,
            "status": "running", "log_path": str(log),
            "submitted_at": "2026-01-01T00:00:00+00:00", "finished_at": None,
        }
        (jobs_dir / "job3.json").write_text(json.dumps(data))

        with patch("os.kill", side_effect=ProcessLookupError):
            result = get_mintpy_status("job3", str(tmp_path))

        assert result["status"] == "failed"

    def test_already_done_not_reprocessed(self, tmp_path):
        self._write_job(tmp_path / ".jobs", "job4", pid=1, status="done")
        # os.kill should NOT be called
        with patch("os.kill") as mock_kill:
            result = get_mintpy_status("job4", str(tmp_path))
        mock_kill.assert_not_called()
        assert result["status"] == "done"


# ── insar_run_mintpy MCP tool tests ──────────────────────────────────────────

class TestInsarRunMintpy:
    def test_empty_glob_returns_invalid_input(self, tmp_path):
        cfg = tmp_path / "mintpy.cfg"
        cfg.write_text("")
        dem = tmp_path / "dem.tif"
        dem.write_bytes(b"")
        result = insar_run_mintpy(
            mintpy_work_dir=str(tmp_path / "work"),
            gunw_glob="   ",
            mintpy_config=str(cfg),
            dem_path=str(dem),
            conda_env="mintpy",
        )
        assert result["error"] == "invalid_input"

    def test_missing_config_returns_path_not_found(self, tmp_path):
        dem = tmp_path / "dem.tif"
        dem.write_bytes(b"")
        result = insar_run_mintpy(
            mintpy_work_dir=str(tmp_path / "work"),
            gunw_glob="/data/*.h5",
            mintpy_config=str(tmp_path / "no.cfg"),
            dem_path=str(dem),
            conda_env="mintpy",
        )
        assert result["error"] == "path_not_found"

    def test_missing_dem_returns_path_not_found(self, tmp_path):
        cfg = tmp_path / "mintpy.cfg"
        cfg.write_text("")
        result = insar_run_mintpy(
            mintpy_work_dir=str(tmp_path / "work"),
            gunw_glob="/data/*.h5",
            mintpy_config=str(cfg),
            dem_path=str(tmp_path / "no_dem.tif"),
            conda_env="mintpy",
        )
        assert result["error"] == "path_not_found"

    def test_launch_failure_returns_launch_failed(self, tmp_path):
        cfg = tmp_path / "mintpy.cfg"
        cfg.write_text("")
        dem = tmp_path / "dem.tif"
        dem.write_bytes(b"")
        with patch("insar_agent.mcp.server.run_mintpy", side_effect=RuntimeError("boom")):
            result = insar_run_mintpy(
                mintpy_work_dir=str(tmp_path / "work"),
                gunw_glob="/data/*.h5",
                mintpy_config=str(cfg),
                dem_path=str(dem),
                conda_env="mintpy",
            )
        assert result["error"] == "launch_failed"

    def test_success_returns_job_id_and_poll(self, tmp_path):
        cfg = tmp_path / "mintpy.cfg"
        cfg.write_text("")
        dem = tmp_path / "dem.tif"
        dem.write_bytes(b"")
        fake_result = {
            "job_id": "abc-123",
            "pid": 42,
            "status": "running",
            "log_path": "/work/logs/abc-123.log",
            "submitted_at": "2026-01-01T00:00:00+00:00",
        }
        with patch("insar_agent.mcp.server.run_mintpy", return_value=fake_result):
            result = insar_run_mintpy(
                mintpy_work_dir=str(tmp_path / "work"),
                gunw_glob="/data/*.h5",
                mintpy_config=str(cfg),
                dem_path=str(dem),
                conda_env="mintpy",
            )
        assert "error" not in result
        assert result["job_id"] == "abc-123"
        assert "insar_get_job" in result["poll"]
        assert "abc-123" in result["poll"]
        assert result["interaction_mode"] == "interactive"
        assert "progress_hint" in result

    def test_success_passes_overrides_and_mode_to_engine(self, tmp_path):
        cfg = tmp_path / "mintpy.cfg"
        cfg.write_text("")
        dem = tmp_path / "dem.tif"
        dem.write_bytes(b"")
        fake_result = {
            "job_id": "abc-123",
            "pid": 42,
            "status": "running",
            "log_path": "/work/logs/abc-123.log",
            "submitted_at": "2026-01-01T00:00:00+00:00",
        }
        with patch("insar_agent.mcp.server.run_mintpy", return_value=fake_result) as mock_run:
            result = insar_run_mintpy(
                mintpy_work_dir=str(tmp_path / "work"),
                gunw_glob="/data/*.h5",
                mintpy_config=str(cfg),
                dem_path=str(dem),
                conda_env="mintpy",
                python_bin="/opt/python",
                smallbaseline_bin="/opt/smallbaselineApp.py",
                interaction_mode="auto",
            )

        _, kwargs = mock_run.call_args
        assert kwargs["python_bin"] == "/opt/python"
        assert kwargs["smallbaseline_bin"] == "/opt/smallbaselineApp.py"
        assert result["interaction_mode"] == "auto"


# ── insar_get_mintpy_status MCP tool tests ───────────────────────────────────

class TestInsarGetMintpyStatus:
    def test_missing_work_dir_returns_path_not_found(self, tmp_path):
        result = insar_get_mintpy_status(
            job_id="some-id",
            mintpy_work_dir=str(tmp_path / "no_such_dir"),
        )
        assert result["error"] == "path_not_found"

    def test_missing_job_returns_job_not_found(self, tmp_path):
        tmp_path.mkdir(exist_ok=True)
        result = insar_get_mintpy_status(
            job_id="no-such-job",
            mintpy_work_dir=str(tmp_path),
        )
        assert result["error"] == "job_not_found"

    def test_running_job_returns_status(self, tmp_path):
        jobs_dir = tmp_path / ".jobs"
        jobs_dir.mkdir()
        data = {
            "job_id": "j1", "pid": os.getpid(),
            "status": "running", "log_path": "",
            "submitted_at": "2026-01-01T00:00:00+00:00", "finished_at": None,
        }
        (jobs_dir / "j1.json").write_text(json.dumps(data))

        result = insar_get_mintpy_status(job_id="j1", mintpy_work_dir=str(tmp_path))
        assert "error" not in result
        assert result["status"] == "running"
        assert result["job_id"] == "j1"


# ── insar_plot_baseline MCP tool tests ───────────────────────────────────────

class TestInsarPlotBaseline:
    def test_missing_network_dir_returns_path_not_found(self, tmp_path):
        result = insar_plot_baseline(
            network_dir=str(tmp_path / "no_such_dir"),
        )
        assert result["error"] == "path_not_found"

    def test_explicit_missing_pair_list_returns_path_not_found(self, tmp_path):
        tmp_path.mkdir(exist_ok=True)
        result = insar_plot_baseline(
            network_dir=str(tmp_path),
            pair_list=str(tmp_path / "no_such.txt"),
        )
        assert result["error"] == "path_not_found"

    def test_dependency_missing_returns_error(self, tmp_path):
        tmp_path.mkdir(exist_ok=True)
        with patch(
            "insar_agent.mcp.server.plot_baseline_network",
            side_effect=RuntimeError("matplotlib not available"),
        ):
            result = insar_plot_baseline(network_dir=str(tmp_path))
        assert result["error"] == "dependency_missing"

    def test_general_exception_returns_plot_failed(self, tmp_path):
        tmp_path.mkdir(exist_ok=True)
        with patch(
            "insar_agent.mcp.server.plot_baseline_network",
            side_effect=ValueError("bad data"),
        ):
            result = insar_plot_baseline(network_dir=str(tmp_path))
        assert result["error"] == "plot_failed"

    def test_success_returns_output_paths(self, tmp_path):
        tmp_path.mkdir(exist_ok=True)
        fake_result = {
            "png_path": "/net/pair_lists/baseline_network.png",
            "pdf_path": "/net/pair_lists/baseline_network.pdf",
            "pair_csv": "/net/pair_lists/pair_baselines.csv",
            "scene_csv": "/net/pair_lists/scene_baselines.csv",
            "n_pairs": 5,
        }
        with patch(
            "insar_agent.mcp.server.plot_baseline_network",
            return_value=fake_result,
        ):
            result = insar_plot_baseline(network_dir=str(tmp_path))

        assert "error" not in result
        assert result["n_pairs"] == 5
        assert result["png_path"].endswith(".png")
        assert result["pair_csv"].endswith(".csv")
        assert result["interaction_mode"] == "interactive"
        assert result["handoff_required"] is True
        assert any(path.endswith(".png") for path in result["review_artifacts"])
        assert "insar_run_mintpy" in result["next_recommended_action"]

    def test_empty_pair_list_uses_default(self, tmp_path):
        """pair_list='' should pass None to the engine (use default path)."""
        tmp_path.mkdir(exist_ok=True)
        with patch("insar_agent.mcp.server.plot_baseline_network") as mock_fn:
            mock_fn.return_value = {
                "png_path": "a.png", "pdf_path": "a.pdf",
                "pair_csv": "a.csv", "scene_csv": "b.csv", "n_pairs": 3,
            }
            insar_plot_baseline(network_dir=str(tmp_path), pair_list="")

        _, kwargs = mock_fn.call_args
        assert kwargs.get("pair_list") is None

    def test_auto_mode_skips_handoff(self, tmp_path):
        tmp_path.mkdir(exist_ok=True)
        fake_result = {
            "png_path": "/net/pair_lists/baseline_network.png",
            "pdf_path": "/net/pair_lists/baseline_network.pdf",
            "pair_csv": "/net/pair_lists/pair_baselines.csv",
            "scene_csv": "/net/pair_lists/scene_baselines.csv",
            "n_pairs": 5,
        }
        with patch("insar_agent.mcp.server.plot_baseline_network", return_value=fake_result):
            result = insar_plot_baseline(
                network_dir=str(tmp_path),
                interaction_mode="auto",
            )

        assert result["interaction_mode"] == "auto"
        assert result["handoff_required"] is False
