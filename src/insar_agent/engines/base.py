from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class WorkflowInfo:
    engine: str
    workflow: str
    supports_gpu: bool
    description: str


class EngineAdapter(Protocol):
    name: str

    def list_workflows(self) -> list[WorkflowInfo]:
        ...
