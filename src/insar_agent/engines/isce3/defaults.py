from __future__ import annotations

from insar_agent.engines.base import WorkflowInfo


SUPPORTED_WORKFLOWS = [
    WorkflowInfo(
        engine="isce3",
        workflow="gslc",
        supports_gpu=True,
        description="Geocode SLC products from RSLC inputs.",
    ),
    WorkflowInfo(
        engine="isce3",
        workflow="insar",
        supports_gpu=True,
        description="Generate interferometric products from reference/secondary RSLC inputs.",
    ),
]
