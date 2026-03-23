from __future__ import annotations

from insar_agent.engines.base import WorkflowInfo
from insar_agent.engines.isce3.defaults import SUPPORTED_WORKFLOWS


class ISCE3Adapter:
    name = "isce3"

    def list_workflows(self) -> list[WorkflowInfo]:
        return list(SUPPORTED_WORKFLOWS)
