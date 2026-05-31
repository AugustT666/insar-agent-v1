"""Shared param-advisor primitives.

Both the ISCE2 and ISCE3 advisors are largely engine-specific, but two evidence
helpers are byte-for-byte identical. They live here once; each engine imports
them and keeps its own engine-specific evidence/recommendation logic. See
``engines/isce2/param_advisor.py`` and ``engines/isce3/param_advisor.py``.
"""
from __future__ import annotations


def _field(value: object, source: str, inferred_from: list[str] | None = None) -> dict:
    """Wrap a value with provenance for an evidence profile."""
    return {"value": value, "source": source, "inferred_from": inferred_from or []}


def _pick_context(user_context: dict, key: str, *, default: object = None) -> dict:
    """Return a provenance-tagged field from user context, or a 'missing' marker."""
    if key in user_context and user_context[key] not in (None, ""):
        return _field(user_context[key], "user_provided")
    return _field(default, "missing")
