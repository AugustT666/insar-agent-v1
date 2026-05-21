from pathlib import Path

from insar_agent.engines.isce3.defaults import SUPPORTED_WORKFLOWS
from insar_agent.mcp.server import build_server_description


def test_server_description_mentions_isce3():
    description = build_server_description()
    assert description["server_name"] == "insar-mcp-server"
    assert "isce3" in description["engines"]
    assert "insar_discover" in description["tools"]
    assert "insar_run_batch" in description["tools"]
    assert "insar_describe_rslc" in description["tools"]
    assert "insar_download_rslc" in description["tools"]
    assert "insar_download_dem" in description["tools"]
    assert "insar_extract_bbox" not in description["tools"]
    assert "insar_validate_runconfig" not in description["tools"]
    assert "insar_export_runconfig" in description["tools"]
    assert "insar_run_mintpy_isce2" in description["tools"]
    assert "insar_get_mintpy_status" not in description["tools"]
    assert "insar_task_done" not in description["tools"]


def test_supported_workflows_include_insar():
    workflow_names = {item.workflow for item in SUPPORTED_WORKFLOWS}
    assert "insar" in workflow_names


def test_server_has_no_obsolete_test_harness_signal_tool():
    server_source = Path(__file__).resolve().parents[2] / "src" / "insar_agent" / "mcp" / "server.py"
    text = server_source.read_text(encoding="utf-8")

    assert "def insar_task_done" not in text
    assert "done.signal" not in text
