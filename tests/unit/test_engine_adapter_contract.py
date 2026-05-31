"""Contract tests for the engine adapter standard.

Verifies that:
1. Both built-in adapters satisfy the EngineAdapter Protocol.
2. The registry exposes them via get_adapter / available_engines.
3. A throwaway THIRD adapter (a stand-in for a future GAMMA/GMTSAR engine) can be
   registered and used with ZERO changes to mcp/ — proving the standard works.
"""
from __future__ import annotations

import pytest

from insar_agent.engines import (
    available_engines,
    get_adapter,
    register_adapter,
)
from insar_agent.engines.base import EngineAdapter, WorkflowInfo

_REQUIRED_METHODS = (
    "list_workflows",
    "task_id_for",
    "allowed_set_fields",
    "required_fields",
)


@pytest.mark.parametrize("engine", ["isce2", "isce3"])
def test_builtin_adapter_satisfies_protocol(engine):
    adapter = get_adapter(engine)
    assert isinstance(adapter, EngineAdapter)
    assert adapter.name == engine
    for method in _REQUIRED_METHODS:
        assert callable(getattr(adapter, method)), f"{engine} missing {method}"


@pytest.mark.parametrize("engine", ["isce2", "isce3"])
def test_builtin_adapter_lists_workflows(engine):
    adapter = get_adapter(engine)
    workflows = adapter.list_workflows()
    assert workflows
    assert all(isinstance(w, WorkflowInfo) for w in workflows)
    assert all(w.engine == engine for w in workflows)
    for w in workflows:
        assert adapter.task_id_for(w.workflow)


def test_available_engines_contains_builtins():
    engines = available_engines()
    assert {"isce2", "isce3"} <= set(engines)


def test_get_adapter_unknown_raises():
    with pytest.raises(KeyError):
        get_adapter("does-not-exist")


def test_third_party_engine_plugs_in_with_no_mcp_changes():
    """A future engine (a GAMMA stand-in) registers and is usable immediately."""

    class GammaAdapter:
        name = "gamma-stub"

        def list_workflows(self):
            return [
                WorkflowInfo(
                    engine="gamma-stub",
                    workflow="diff",
                    supports_gpu=False,
                    description="GAMMA DIFF",
                )
            ]

        def task_id_for(self, workflow):
            return "d-insar-gamma"

        def allowed_set_fields(self, workflow):
            return {"ref_slc", "sec_slc", "dem"}

        def required_fields(self, workflow):
            return ["ref_slc", "sec_slc", "dem"]

    register_adapter(GammaAdapter())
    try:
        adapter = get_adapter("gamma-stub")
        assert isinstance(adapter, EngineAdapter)
        assert adapter.task_id_for("diff") == "d-insar-gamma"
        assert [w.workflow for w in adapter.list_workflows()] == ["diff"]
        assert "gamma-stub" in available_engines()
    finally:
        from insar_agent.engines import _REGISTRY
        _REGISTRY.pop("gamma-stub", None)
