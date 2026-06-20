"""Tests for Task 5.1: conditional auto-background dispatch + monitor field.

Heuristic: background is auto-triggered when scene_count > 1 OR download_dem
OR download_orbits. Quick (organize-only, single scene, no downloads) runs
synchronously and returns inline result with no job_id.

The `monitor` field on background returns must point at the Layer-1 progress
log: ``tail -f <run_root>/.insar_agent/progress.log``.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers: fake bg-launch return with monitor pointing at progress.log
# ---------------------------------------------------------------------------

def _fake_bg_result(run_root: str) -> dict:
    progress_log = str(Path(run_root) / ".insar_agent" / "progress.log")
    return {
        "job_id": "abc123",
        "status": "running",
        "pid": 55001,
        "output_dir": run_root,
        "n_files": 2,
        "log_path": str(Path(run_root) / "logs" / "sentinel_prepare_abc123.log"),
        "monitor": f"tail -f {progress_log}",
        "params_path": str(Path(run_root) / "logs" / "sentinel_prepare_abc123_params.json"),
        "workspace_root": "/ws",
        "task_id": "stack-insar-isce2",
        "run_id": "prep-multi",
        "run_root": run_root,
        "poll": 'insar_get_job(job_id="abc123", workspace_root="/ws", task_id="stack-insar-isce2")',
    }


# ---------------------------------------------------------------------------
# Tests: auto-background heuristic triggers
# ---------------------------------------------------------------------------

def test_multiscene_prepare_autobackgrounds(tmp_path):
    """2+ scenes + download_dem → auto-background: status running + job_id + monitor + poll."""
    workspace = tmp_path / "workspace"
    run_root = str(workspace / "stack-insar-isce2_prep-multi")

    from insar_agent.mcp.server import insar_prepare_sentinel_data

    with patch(
        "insar_agent.mcp.server._launch_sentinel_prepare_background",
        return_value=_fake_bg_result(run_root),
    ) as mock_launch:
        result = insar_prepare_sentinel_data(
            workspace_root=str(workspace),
            task_id="stack-insar-isce2",
            run_id="prep-multi",
            source_paths=[
                "/data/scene1.SAFE",
                "/data/scene2.SAFE",
            ],
            download_dem=True,
        )

    # Must have auto-dispatched to background
    mock_launch.assert_called_once(), "Expected _launch_sentinel_prepare_background to be called"

    assert result.get("status") == "running", f"Expected status=running, got: {result}"
    assert "job_id" in result, f"Expected job_id in result: {result}"
    assert "poll" in result, f"Expected poll in result: {result}"
    assert "monitor" in result, f"Expected monitor in result: {result}"
    # monitor must point at Layer-1 progress.log, not raw job log
    assert "progress.log" in result["monitor"], (
        f"monitor must reference progress.log, got: {result['monitor']!r}"
    )
    assert "tail -f" in result["monitor"], (
        f"monitor should be a tail -f command, got: {result['monitor']!r}"
    )
    assert ".insar_agent" in result["monitor"], (
        f"monitor must point inside .insar_agent/, got: {result['monitor']!r}"
    )
    # log_path still points at raw Layer-2 log (different from monitor target)
    assert "log_path" in result
    monitor_target = result["monitor"].removeprefix("tail -f ")
    assert result["log_path"] != monitor_target, (
        "log_path and monitor target must refer to different files"
    )


def test_single_download_dem_autobackgrounds(tmp_path):
    """Single scene + download_dem → auto-background (download_dem alone is a long op)."""
    workspace = tmp_path / "workspace"
    run_root = str(workspace / "d-insar-isce2_prep-dem")

    from insar_agent.mcp.server import insar_prepare_sentinel_data

    with patch(
        "insar_agent.mcp.server._launch_sentinel_prepare_background",
        return_value=_fake_bg_result(run_root),
    ) as mock_launch:
        result = insar_prepare_sentinel_data(
            workspace_root=str(workspace),
            task_id="d-insar-isce2",
            run_id="prep-dem",
            source_paths=["/data/scene1.SAFE"],
            download_dem=True,
        )

    mock_launch.assert_called_once()
    assert result.get("status") == "running", f"Expected auto-background, got: {result}"
    assert "job_id" in result
    assert "monitor" in result
    assert "progress.log" in result["monitor"]


def test_single_download_orbits_autobackgrounds(tmp_path):
    """Single scene + download_orbits → auto-background (orbit download is a long op)."""
    workspace = tmp_path / "workspace"
    run_root = str(workspace / "d-insar-isce2_prep-orbits")

    from insar_agent.mcp.server import insar_prepare_sentinel_data

    with patch(
        "insar_agent.mcp.server._launch_sentinel_prepare_background",
        return_value=_fake_bg_result(run_root),
    ) as mock_launch:
        result = insar_prepare_sentinel_data(
            workspace_root=str(workspace),
            task_id="d-insar-isce2",
            run_id="prep-orbits",
            source_paths=["/data/scene1.SAFE"],
            download_orbits=True,
            orbit_username="user@example.invalid",
            orbit_password="secret",
        )

    mock_launch.assert_called_once()
    assert result.get("status") == "running", f"Expected auto-background, got: {result}"
    assert "job_id" in result
    assert "monitor" in result
    assert "progress.log" in result["monitor"]


# ---------------------------------------------------------------------------
# Tests: sync path (no auto-background)
# ---------------------------------------------------------------------------

def test_single_quick_prepare_sync(tmp_path):
    """Organize-only single scene (no downloads) → synchronous inline result, no job_id."""
    workspace = tmp_path / "workspace"

    fake_result = {
        "project_root": str(workspace / "prepare" / "safe"),
        "safe_root": str(workspace / "prepare" / "safe" / "safe"),
        "grouped_safe_paths": {"scene1": ["/data/scene1.SAFE"]},
        "dem_path": None,
        "orbit_dir": None,
        "scene_count": 1,
        "prep_log_path": str(workspace / "prepare" / "safe" / "logs" / "prep.log"),
    }

    from insar_agent.mcp.server import insar_prepare_sentinel_data

    with patch("insar_agent.mcp.server.prepare_sentinel_data", return_value=fake_result):
        result = insar_prepare_sentinel_data(
            workspace_root=str(workspace),
            task_id="d-insar-isce2",
            run_id="prep-quick",
            source_paths=["/data/scene1.SAFE"],
            download_dem=False,
            download_orbits=False,
        )

    # Must be synchronous: no job_id, no status="running"
    assert "job_id" not in result, f"Quick sync must not have job_id: {result}"
    assert result.get("status") != "running", f"Quick sync must not be status=running: {result}"
    # Must have inline result fields
    assert "project_root" in result or "error" in result


def test_zero_scenes_quick_prepare_sync(tmp_path):
    """Zero source_paths and no downloads → synchronous (organize phase only)."""
    workspace = tmp_path / "workspace"

    from insar_agent.mcp.server import insar_prepare_sentinel_data

    result = insar_prepare_sentinel_data(
        workspace_root=str(workspace),
        task_id="d-insar-isce2",
        run_id="prep-empty",
        source_paths=[],
        download_dem=False,
        download_orbits=False,
    )

    # Must be synchronous: no job_id, no status="running"
    assert "job_id" not in result, f"Zero-scene sync must not have job_id: {result}"
    assert result.get("status") != "running", f"Zero-scene sync must not be status=running: {result}"


def test_explicit_background_false_overrides_heuristic(tmp_path):
    """background=False explicitly disables auto-dispatch even for multi-scene + downloads."""
    workspace = tmp_path / "workspace"

    fake_result = {
        "project_root": str(workspace / "prepare" / "safe"),
        "safe_root": str(workspace / "prepare" / "safe" / "safe"),
        "grouped_safe_paths": {},
        "dem_path": None,
        "orbit_dir": None,
        "scene_count": 3,
        "prep_log_path": str(workspace / "prepare" / "safe" / "logs" / "prep.log"),
    }

    from insar_agent.mcp.server import insar_prepare_sentinel_data

    with patch("insar_agent.mcp.server.prepare_sentinel_data", return_value=fake_result):
        result = insar_prepare_sentinel_data(
            workspace_root=str(workspace),
            task_id="stack-insar-isce2",
            run_id="prep-forced-sync",
            source_paths=["/data/s1.SAFE", "/data/s2.SAFE", "/data/s3.SAFE"],
            download_dem=True,
            background=False,  # explicit override: caller forces sync
        )

    # Caller explicitly requested sync; we honor it (no job_id)
    assert "job_id" not in result, f"background=False must not produce job_id: {result}"


# ---------------------------------------------------------------------------
# Tests: monitor field format on real background launch
# ---------------------------------------------------------------------------

def test_monitor_command_format_in_background_launch(tmp_path):
    """monitor field from real _launch_sentinel_prepare_background must be:
    tail -f <run_root>/.insar_agent/progress.log"""
    workspace = tmp_path / "workspace"
    mock_proc = MagicMock()
    mock_proc.pid = 55010

    from insar_agent.mcp._helpers import _launch_sentinel_prepare_background

    # Build minimal params that give a valid job_context (workspace + task_id)
    params = {
        "project_root": str(workspace / "prepare" / "safe"),
        "project_id": "",
        "workspace_root": str(workspace),
        "task_id": "stack-insar-isce2",
        "run_id": "prep-monitor",
        "source_paths": ["/data/s1.SAFE", "/data/s2.SAFE"],
        "download_dem": True,
        "download_orbits": False,
        "orbit_username": None,
        "orbit_password": None,
        "orbit_token_file": None,
        "orbit_dir": None,
        "dem_path": None,
        "dem_output_path": None,
        "dem_backend": "general",
        "dem_type": None,
        "aoi_path": None,
        "bbox": None,
        "mode": "auto",
        "burst_manifest": None,
        "include_pair": True,
        "include_stack": True,
        "resume": True,
        "validate_isce2_import": False,
    }

    with patch("insar_agent.mcp._helpers.subprocess.Popen", return_value=mock_proc):
        result = _launch_sentinel_prepare_background(params)

    assert result.get("status") == "running", f"Expected running, got: {result}"
    monitor = result.get("monitor", "")
    # Format must be: tail -f <some_run_root>/.insar_agent/progress.log
    assert monitor.startswith("tail -f "), f"monitor must start with 'tail -f': {monitor!r}"
    assert monitor.endswith("/.insar_agent/progress.log"), (
        f"monitor must end with /.insar_agent/progress.log: {monitor!r}"
    )
    # Must NOT point at the raw log (which is job-named sentinel_prepare_*.log)
    assert "sentinel_prepare_" not in monitor, (
        f"monitor must not point at raw layer-2 log, got: {monitor!r}"
    )
