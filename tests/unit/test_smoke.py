from insar_agent.engines.isce3.defaults import SUPPORTED_WORKFLOWS
from insar_agent.mcp.server import build_server_description


def test_server_description_mentions_isce3():
    description = build_server_description()
    assert description["server_name"] == "insar-mcp-server"
    assert "isce3" in description["engines"]


def test_supported_workflows_include_insar():
    workflow_names = {item.workflow for item in SUPPORTED_WORKFLOWS}
    assert "insar" in workflow_names
