"""Import every tool module so @mcp.tool decorators register on import."""
from insar_agent.mcp.tools import project_tools  # noqa: F401
from insar_agent.mcp.tools import param_tools  # noqa: F401
from insar_agent.mcp.tools import job_tools  # noqa: F401
from insar_agent.mcp.tools import prepare_tools  # noqa: F401
from insar_agent.mcp.tools import product_tools  # noqa: F401
from insar_agent.mcp.tools import env_tools  # noqa: F401
from insar_agent.mcp.tools import search_tools  # noqa: F401
