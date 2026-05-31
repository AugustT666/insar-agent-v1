"""Engine adapters and registry.

A new engine plugs in by implementing :class:`~insar_agent.engines.base.EngineAdapter`
and registering it here (or at runtime via :func:`register_adapter`). Callers
resolve the active engine through :func:`get_adapter` instead of branching on
``engine ==``. The registry is populated lazily to avoid import cycles.
"""
from __future__ import annotations

from insar_agent.engines.base import EngineAdapter, WorkflowInfo

__all__ = [
    "EngineAdapter",
    "WorkflowInfo",
    "get_adapter",
    "register_adapter",
    "available_engines",
]

_REGISTRY: dict[str, EngineAdapter] = {}


def _ensure_builtin() -> None:
    if _REGISTRY:
        return
    from insar_agent.engines.isce2.adapter import ISCE2Adapter
    from insar_agent.engines.isce3.adapter import ISCE3Adapter

    _REGISTRY["isce2"] = ISCE2Adapter()
    _REGISTRY["isce3"] = ISCE3Adapter()


def get_adapter(name: str) -> EngineAdapter:
    """Return the registered adapter for *name* (e.g. ``"isce2"``)."""
    _ensure_builtin()
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(
            f"Unknown engine {name!r}; registered engines: {sorted(_REGISTRY)}"
        ) from None


def register_adapter(adapter: EngineAdapter) -> None:
    """Register (or replace) an engine adapter by its ``name``."""
    _ensure_builtin()
    _REGISTRY[adapter.name] = adapter


def available_engines() -> dict[str, EngineAdapter]:
    """Return a copy of the engine registry."""
    _ensure_builtin()
    return dict(_REGISTRY)
