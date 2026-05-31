from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class WorkflowInfo:
    engine: str
    workflow: str
    supports_gpu: bool
    description: str


@runtime_checkable
class EngineAdapter(Protocol):
    """Capability contract a processing engine implements to plug into the plugin.

    Kept deliberately minimal — only what both built-in engines share cleanly — so
    a new engine (e.g. GAMMA/GMTSAR) never has to stub awkward methods. See
    ``docs/engine-onboarding.md`` for the onboarding model and checklist.
    """

    name: str

    def list_workflows(self) -> list[WorkflowInfo]:
        """Workflows this engine exposes."""
        ...

    def task_id_for(self, workflow: str) -> str:
        """Canonical task_id for a workflow, e.g. ``"d-insar-isce2"``."""
        ...

    def allowed_set_fields(self, workflow: str) -> set[str]:
        """Config field keys a caller may set for this workflow."""
        ...

    def required_fields(self, workflow: str) -> list[str]:
        """Field keys that must be present before the workflow can run."""
        ...
