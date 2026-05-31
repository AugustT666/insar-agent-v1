from __future__ import annotations

from insar_agent.engines.base import WorkflowInfo
from insar_agent.engines.isce2.defaults import (
    ALLOWED_SET_FIELDS,
    REQUIRED_PARAM_FIELDS,
    SUPPORTED_WORKFLOWS,
)

_TASK_IDS = {
    "tops": "d-insar-isce2",
    "stack": "stack-insar-isce2",
}


class ISCE2Adapter:
    """ISCE2 reference adapter — thin delegations to isce2 modules.

    A new engine follows this same pattern over its own modules. See
    ``docs/engine-onboarding.md``.
    """

    name = "isce2"

    def list_workflows(self) -> list[WorkflowInfo]:
        return list(SUPPORTED_WORKFLOWS)

    def task_id_for(self, workflow: str) -> str:
        return _TASK_IDS.get(workflow, "d-insar-isce2")

    def allowed_set_fields(self, workflow: str) -> set[str]:
        return set(ALLOWED_SET_FIELDS.get(workflow, []))

    def required_fields(self, workflow: str) -> list[str]:
        return list(REQUIRED_PARAM_FIELDS.get(workflow, []))
