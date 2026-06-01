from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from insar_agent.mcp.server import insar_download_dem, insar_prepare_sentinel_data


def test_download_dem_default_path_stays_under_outputs(tmp_path):
    workspace = tmp_path / "workspace"

    def fake_download_dem(*, output_path, bbox, source, margin_deg: float, on_progress, proxy):
        _ = (margin_deg, on_progress, proxy)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("dem", encoding="utf-8")
        return {"output_path": str(path), "source": source, "bbox": list(bbox)}

    with (
        patch("insar_agent.mcp.server.download_dem", side_effect=fake_download_dem),
        patch("insar_agent.mcp.server._ensure_isce2_dem_xml", return_value=None),
    ):
        result = insar_download_dem(
            workspace_root=str(workspace),
            task_id="d-insar-isce3",
            run_id="dem-run",
            bbox=[40.0, 10.0, 41.0, 11.0],
        )

    output_path = Path(result["output_path"])
    log_path = Path(result["log_path"])
    run_root = workspace / "d-insar-isce3" / "outputs" / "dem-run"
    assert output_path.is_relative_to(run_root)
    assert log_path.is_relative_to(run_root)
    assert not (workspace / "d-insar-isce3" / "dem").exists()
    assert not (workspace / "d-insar-isce3" / ".insar_logs").exists()


def test_download_dem_task_root_output_path_is_honored(tmp_path):
    # Flexible-input policy: an explicit user output path is honored as-given,
    # even when it points at a task root and no workspace context is supplied.
    workspace = tmp_path / "workspace"
    task_root = workspace / "stack-insar-isce2"
    requested_path = task_root / "dem" / "copernicus_30.tif"

    def fake_download_dem(*, output_path, bbox, source, margin_deg: float, on_progress, proxy):
        _ = (margin_deg, on_progress, proxy)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("dem", encoding="utf-8")
        return {"output_path": str(path), "source": source, "bbox": list(bbox)}

    with (
        patch("insar_agent.mcp.server.download_dem", side_effect=fake_download_dem),
        patch("insar_agent.mcp.server._ensure_isce2_dem_xml", return_value=None),
    ):
        result = insar_download_dem(
            output_path=str(requested_path),
            run_id="dem-run",
            bbox=[12.0, 39.0, 14.0, 42.0],
        )

    output_path = Path(result["output_path"])
    log_path = Path(result["log_path"])
    assert output_path == requested_path.resolve()
    # Log sits beside the honored output (no run root to host it).
    assert log_path.is_relative_to(requested_path.parent.resolve())


def test_download_dem_reports_task_root_pollution(tmp_path):
    workspace = tmp_path / "workspace"
    task_id = "stack-insar-isce2"
    task_root = workspace / task_id
    requested_path = task_root / "outputs" / "dem-run" / "dem" / "copernicus_30.tif"
    pollution_dir = task_root / "dem"

    def fake_download_dem(*, output_path, bbox, source, margin_deg: float, on_progress, proxy):
        _ = (bbox, source, margin_deg, on_progress, proxy)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("dem", encoding="utf-8")
        pollution_dir.mkdir(parents=True)
        (pollution_dir / "copernicus_30.tif").write_text("pollution", encoding="utf-8")
        return {"output_path": str(path), "source": source, "bbox": [12.0, 39.0, 14.0, 42.0]}

    with (
        patch("insar_agent.mcp.server.download_dem", side_effect=fake_download_dem),
        patch("insar_agent.mcp.server._ensure_isce2_dem_xml", return_value=None),
    ):
        result = insar_download_dem(
            output_path=str(requested_path),
            workspace_root=str(workspace),
            task_id=task_id,
            run_id="dem-run",
            bbox=[12.0, 39.0, 14.0, 42.0],
        )

    assert result["error"] == "task_root_pollution"
    assert str(pollution_dir) in result["polluting_paths"]
    assert result["tool_result"]["output_path"] == str(requested_path)


def test_download_dem_preserves_custom_path_named_like_task_id(tmp_path):
    custom_path = tmp_path / "custom" / "stack-insar-isce2" / "dem" / "copernicus_30.tif"

    def fake_download_dem(*, output_path, bbox, source, margin_deg: float, on_progress, proxy):
        _ = (margin_deg, on_progress, proxy)
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("dem", encoding="utf-8")
        return {"output_path": str(path), "source": source, "bbox": list(bbox)}

    with (
        patch("insar_agent.mcp.server.download_dem", side_effect=fake_download_dem),
        patch("insar_agent.mcp.server._ensure_isce2_dem_xml", return_value=None),
    ):
        result = insar_download_dem(
            output_path=str(custom_path),
            run_id="dem-run",
            bbox=[12.0, 39.0, 14.0, 42.0],
        )

    assert Path(result["output_path"]) == custom_path
    assert not (tmp_path / "custom" / "stack-insar-isce2" / "outputs").exists()


def test_background_download_dem_returns_pollable_job_under_outputs(tmp_path):
    workspace = tmp_path / "workspace"
    mock_proc = MagicMock()
    mock_proc.pid = 43434

    with patch("insar_agent.mcp.server.subprocess.Popen", return_value=mock_proc) as mock_popen:
        result = insar_download_dem(
            workspace_root=str(workspace),
            task_id="d-insar-isce3",
            run_id="dem-run",
            bbox=[40.0, 10.0, 41.0, 11.0],
            proxy="https://user:secret@example.invalid:8443",
            background=True,
        )

    run_root = workspace / "d-insar-isce3" / "outputs" / "dem-run"
    task_jobs_dir = workspace / "d-insar-isce3" / ".insar_agent" / "jobs"
    assert result["status"] == "running"
    assert Path(result["output_path"]).is_relative_to(run_root)
    assert Path(result["output_dir"]) == run_root
    assert Path(result["log_path"]).is_relative_to(run_root / "logs")
    assert (task_jobs_dir / f"{result['job_id']}.json").exists()
    assert not (run_root / ".insar_agent" / "jobs").exists()
    job_text = (task_jobs_dir / f"{result['job_id']}.json").read_text(encoding="utf-8")
    assert "insar_download_dem" in job_text
    assert "dem_download" in job_text
    params_text = Path(result["params_path"]).read_text(encoding="utf-8")
    assert "background" in params_text
    assert "secret" not in params_text
    _, kwargs = mock_popen.call_args
    assert kwargs["env"]["INSAR_AGENT_DEM_PROXY"] == "https://user:secret@example.invalid:8443"
    assert not (workspace / "d-insar-isce3" / ".insar_logs").exists()


def test_background_download_dem_preserves_empty_proxy_override(tmp_path):
    workspace = tmp_path / "workspace"
    mock_proc = MagicMock()
    mock_proc.pid = 43435

    with patch("insar_agent.mcp.server.subprocess.Popen", return_value=mock_proc) as mock_popen:
        result = insar_download_dem(
            workspace_root=str(workspace),
            task_id="d-insar-isce3",
            run_id="dem-run",
            bbox=[40.0, 10.0, 41.0, 11.0],
            proxy="",
            background=True,
        )

    assert result["status"] == "running"
    params = json.loads(Path(result["params_path"]).read_text(encoding="utf-8"))
    assert params["proxy"] is None
    _, kwargs = mock_popen.call_args
    assert kwargs["env"]["INSAR_AGENT_DEM_PROXY"] == ""


def test_background_download_dem_validates_bbox_before_launch(tmp_path):
    workspace = tmp_path / "workspace"

    with patch("insar_agent.mcp.server.subprocess.Popen") as mock_popen:
        result = insar_download_dem(
            workspace_root=str(workspace),
            task_id="d-insar-isce3",
            run_id="dem-run",
            background=True,
        )

    run_root = workspace / "d-insar-isce3" / "outputs" / "dem-run"
    task_jobs_dir = workspace / "d-insar-isce3" / ".insar_agent" / "jobs"
    assert result == {"error": "invalid_input", "message": "Provide exactly one of bbox or aoi_path"}
    mock_popen.assert_not_called()
    assert not (run_root / ".insar_agent" / "jobs").exists()
    assert not task_jobs_dir.exists()


def test_prepare_sentinel_default_project_root_stays_under_outputs(tmp_path):
    workspace = tmp_path / "workspace"

    result = insar_prepare_sentinel_data(
        workspace_root=str(workspace),
        task_id="d-insar-isce2",
        run_id="prep-run",
        source_paths=[],
    )

    output_dir = Path(result["project_root"])
    log_path = Path(result["prep_log_path"])
    run_root = workspace / "d-insar-isce2" / "outputs" / "prep-run"
    assert output_dir.is_relative_to(run_root)
    assert log_path.is_relative_to(run_root)
    assert not (workspace / "d-insar-isce2" / "prep").exists()
    assert not (workspace / "d-insar-isce2" / ".insar_logs").exists()


def test_prepare_sentinel_run_root_logs_win_over_task_markers(tmp_path):
    workspace = tmp_path / "workspace"
    task_id = "stack-insar-isce2"
    task_root = workspace / task_id
    (task_root / ".insar_agent").mkdir(parents=True)
    run_root = task_root / "outputs" / "prep-run"

    result = insar_prepare_sentinel_data(
        project_root=str(run_root / "prep"),
        workspace_root=str(workspace),
        task_id=task_id,
        source_paths=[],
    )

    assert "error" not in result
    assert Path(result["prep_log_path"]).parent == run_root / "logs"
    assert not (task_root / ".insar_logs").exists()


def test_prepare_sentinel_task_root_output_is_honored(tmp_path):
    # Flexible-input policy: an explicit project_root is honored as-given.
    # No workspace context is supplied, so the task-root guard does not fire.
    workspace = tmp_path / "workspace"
    task_root = workspace / "d-insar-isce2"

    result = insar_prepare_sentinel_data(
        project_root=str(task_root),
        source_paths=[],
    )

    output_dir = Path(result["project_root"])
    log_path = Path(result["prep_log_path"])
    assert "error" not in result
    assert output_dir == task_root.resolve()
    assert log_path.parent == (task_root / "logs").resolve()
    # The prep workspace is built under the honored root, not relocated.
    assert (task_root / "safe").exists()


def test_prepare_sentinel_task_root_dem_output_is_honored(tmp_path):
    # Flexible-input policy: an explicit dem_output_path is honored as-given and
    # passed through to prepare_sentinel_data unchanged (no relocation).
    workspace = tmp_path / "workspace"
    task_root = workspace / "stack-insar-isce2"
    requested_dem = task_root / "dem" / "copernicus_30.tif"

    def fake_prepare_sentinel_data(**kwargs):
        return {
            "project_root": kwargs["project_root"],
            "safe_root": str(Path(kwargs["project_root"]) / "safe"),
            "grouped_safe_paths": {},
            "dem_path": kwargs["dem_output_path"],
            "orbit_dir": kwargs["orbit_dir"],
            "scene_count": 0,
            "prep_log_path": str(Path(kwargs["project_root"]) / "logs" / "prep.log"),
        }

    with patch("insar_agent.mcp.server.prepare_sentinel_data", side_effect=fake_prepare_sentinel_data) as mock_prepare:
        result = insar_prepare_sentinel_data(
            project_root=str(task_root),
            source_paths=[],
            download_dem=True,
            dem_output_path=str(requested_dem),
        )

    honored_dem = Path(mock_prepare.call_args.kwargs["dem_output_path"])
    assert honored_dem == requested_dem.resolve()
    assert Path(result["dem_path"]) == honored_dem
    assert Path(mock_prepare.call_args.kwargs["project_root"]) == task_root.resolve()


def test_prepare_sentinel_reports_task_root_pollution(tmp_path):
    workspace = tmp_path / "workspace"
    task_id = "stack-insar-isce2"
    task_root = workspace / task_id
    pollution_dir = task_root / "dem"

    def fake_prepare_sentinel_data(**kwargs):
        pollution_dir.mkdir(parents=True)
        (pollution_dir / "copernicus_30.tif").write_text("dem", encoding="utf-8")
        return {
            "project_root": kwargs["project_root"],
            "safe_root": str(Path(kwargs["project_root"]) / "safe"),
            "grouped_safe_paths": {},
            "dem_path": kwargs["dem_output_path"],
            "orbit_dir": kwargs["orbit_dir"],
            "scene_count": 0,
            "prep_log_path": str(Path(kwargs["project_root"]) / "logs" / "prep.log"),
        }

    with patch("insar_agent.mcp.server.prepare_sentinel_data", side_effect=fake_prepare_sentinel_data):
        result = insar_prepare_sentinel_data(
            workspace_root=str(workspace),
            task_id=task_id,
            run_id="prep-run",
            source_paths=[],
            download_dem=True,
            dem_output_path=str(task_root / "outputs" / "prep-run" / "dem" / "copernicus_30.tif"),
        )

    assert result["error"] == "task_root_pollution"
    assert result["task_id"] == task_id
    assert str(pollution_dir) in result["polluting_paths"]


def test_prepare_sentinel_allows_task_root_management_dir(tmp_path):
    workspace = tmp_path / "workspace"
    task_id = "stack-insar-isce2"
    task_root = workspace / task_id
    (task_root / ".insar_agent").mkdir(parents=True)

    def fake_prepare_sentinel_data(**kwargs):
        return {
            "project_root": kwargs["project_root"],
            "safe_root": str(Path(kwargs["project_root"]) / "safe"),
            "grouped_safe_paths": {},
            "dem_path": kwargs["dem_output_path"],
            "orbit_dir": kwargs["orbit_dir"],
            "scene_count": 0,
            "prep_log_path": str(Path(kwargs["project_root"]) / "logs" / "prep.log"),
        }

    with patch("insar_agent.mcp.server.prepare_sentinel_data", side_effect=fake_prepare_sentinel_data):
        result = insar_prepare_sentinel_data(
            workspace_root=str(workspace),
            task_id=task_id,
            run_id="prep-run",
            source_paths=[],
            download_dem=True,
            dem_output_path=str(task_root / "outputs" / "prep-run" / "dem" / "copernicus_30.tif"),
        )

    assert "error" not in result
    assert result["project_root"] == str(task_root / "outputs" / "prep-run" / "prep")


def test_prepare_sentinel_custom_output_keeps_task_root_clean(tmp_path):
    workspace = tmp_path / "workspace"
    task_id = "d-insar-isce2"
    custom_output = tmp_path / "custom" / "e2-output"

    result = insar_prepare_sentinel_data(
        project_root=str(custom_output),
        workspace_root=str(workspace),
        task_id=task_id,
        source_paths=[],
    )

    task_root = workspace / task_id
    assert Path(result["project_root"]) == custom_output.resolve()
    assert Path(result["prep_log_path"]).is_relative_to(custom_output)
    assert not task_root.exists() or set(path.name for path in task_root.iterdir()) <= {".insar_agent", "sessions", "outputs"}
    assert not (task_root / "safe").exists()
    assert not (task_root / "dem").exists()
    assert not (task_root / ".insar_logs").exists()


def test_task_root_pollution_downgraded_to_warning_when_not_strict(tmp_path, monkeypatch):
    """When INSAR_STRICT_OUTPUT=0, task_root_pollution is downgraded to a warning
    and the tool result is returned (no 'error' key)."""
    monkeypatch.setenv("INSAR_STRICT_OUTPUT", "0")
    workspace = tmp_path / "workspace"
    task_id = "stack-insar-isce2"
    task_root = workspace / task_id
    pollution_dir = task_root / "dem"

    def fake_prepare_sentinel_data(**kwargs):
        pollution_dir.mkdir(parents=True)
        (pollution_dir / "copernicus_30.tif").write_text("dem", encoding="utf-8")
        return {
            "project_root": kwargs["project_root"],
            "safe_root": str(Path(kwargs["project_root"]) / "safe"),
            "grouped_safe_paths": {},
            "dem_path": kwargs["dem_output_path"],
            "orbit_dir": kwargs["orbit_dir"],
            "scene_count": 0,
            "prep_log_path": str(Path(kwargs["project_root"]) / "logs" / "prep.log"),
        }

    with patch("insar_agent.mcp.server.prepare_sentinel_data", side_effect=fake_prepare_sentinel_data):
        result = insar_prepare_sentinel_data(
            workspace_root=str(workspace),
            task_id=task_id,
            run_id="prep-run",
            source_paths=[],
            download_dem=True,
            dem_output_path=str(task_root / "outputs" / "prep-run" / "dem" / "copernicus_30.tif"),
        )

    assert "error" not in result, f"Expected no error key, got: {result}"
    assert result.get("warning") == "task_root_pollution"
    assert str(pollution_dir) in result["polluting_paths"]


def test_background_sentinel_prepare_does_not_persist_orbit_password(tmp_path):
    mock_proc = MagicMock()
    mock_proc.pid = 42424

    with patch("insar_agent.mcp.server.subprocess.Popen", return_value=mock_proc) as mock_popen:
        workspace = tmp_path / "workspace"
        task_id = "d-insar-isce2"
        run_root = workspace / task_id / "outputs" / "prep-run"
        result = insar_prepare_sentinel_data(
            project_root=str(run_root / "prep"),
            workspace_root=str(workspace),
            task_id=task_id,
            source_paths=[],
            download_orbits=True,
            orbit_username="user@example.invalid",
            orbit_password="secret-password",
            background=True,
        )

    assert result["status"] == "running"
    task_jobs_dir = workspace / task_id / ".insar_agent" / "jobs"
    assert (task_jobs_dir / f"{result['job_id']}.json").exists()
    assert not (run_root / ".insar_agent" / "jobs").exists()
    params_path = Path(result["params_path"])
    params = json.loads(params_path.read_text(encoding="utf-8"))
    assert "orbit_password" not in params
    assert "secret-password" not in params_path.read_text(encoding="utf-8")

    _, kwargs = mock_popen.call_args
    assert kwargs["env"]["INSAR_AGENT_ORBIT_PASSWORD"] == "secret-password"
