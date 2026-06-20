"""Test conda-safe environment configuration."""
import pytest


def test_conda_env_silences_gdal_warning():
    """Test that PYTHONWARNINGS suppresses FutureWarning in subprocess env."""
    from insar_agent.mcp._helpers import _conda_safe_env
    assert "FutureWarning" in _conda_safe_env({}).get("PYTHONWARNINGS", "")
