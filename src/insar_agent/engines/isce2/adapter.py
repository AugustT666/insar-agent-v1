from __future__ import annotations

from insar_agent.engines.base import WorkflowInfo
from insar_agent.engines.isce2.defaults import SUPPORTED_WORKFLOWS


class ISCE2Adapter:
    name = "isce2"

    def list_workflows(self) -> list[WorkflowInfo]:
        return list(SUPPORTED_WORKFLOWS)
