from __future__ import annotations

from insar_agent.engines.base import WorkflowInfo
from insar_agent.engines.isce3.defaults import (
    ALLOWED_SET_FIELDS,
    REQUIRED_PATH_FIELDS,
    SUPPORTED_WORKFLOWS,
)

_TASK_IDS = {
    "insar": "d-insar-isce3",
    "stack": "stack-insar-isce3",
    "network": "stack-insar-isce3",
}


class ISCE3Adapter:
    """ISCE3 reference adapter — thin delegations to isce3 modules.

    A new engine follows this same pattern over its own modules. See
    ``docs/engine-onboarding.md``.
    """

    name = "isce3"

    def list_workflows(self) -> list[WorkflowInfo]:
        return list(SUPPORTED_WORKFLOWS)

    def task_id_for(self, workflow: str) -> str:
        return _TASK_IDS.get(workflow, "d-insar-isce3")

    def allowed_set_fields(self, workflow: str) -> set[str]:
        return set(ALLOWED_SET_FIELDS.get(workflow, []))

    def required_fields(self, workflow: str) -> list[str]:
        return list(REQUIRED_PATH_FIELDS.get(workflow, []))
