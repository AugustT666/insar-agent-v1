from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from insar_agent.mcp.server import insar_prepare_sentinel_data


def test_background_sentinel_prepare_does_not_persist_orbit_password(tmp_path):
    mock_proc = MagicMock()
    mock_proc.pid = 42424

    with patch("insar_agent.mcp.server.subprocess.Popen", return_value=mock_proc) as mock_popen:
        result = insar_prepare_sentinel_data(
            project_root=str(tmp_path / "project"),
            source_paths=[],
            download_orbits=True,
            orbit_username="user@example.invalid",
            orbit_password="secret-password",
            background=True,
        )

    assert result["status"] == "running"
    params_path = Path(result["params_path"])
    params = json.loads(params_path.read_text(encoding="utf-8"))
    assert "orbit_password" not in params
    assert "secret-password" not in params_path.read_text(encoding="utf-8")

    _, kwargs = mock_popen.call_args
    assert kwargs["env"]["INSAR_AGENT_ORBIT_PASSWORD"] == "secret-password"
