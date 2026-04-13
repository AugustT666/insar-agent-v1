from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import yaml

from insar_agent.engines.isce2.defaults import load_default_params, load_processing_params
from insar_agent.engines.isce2.sentinel_prep import _read_safe_metadata

_ASSETS = Path(__file__).parent / "assets"


def load_param_advisor_rules(workflow: str) -> dict:
    path = _ASSETS / f"param_advisor_rules_{workflow}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No parameter advisor rules for ISCE2 workflow: {workflow!r}")
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_param_template(workflow: str) -> dict:
    path = _ASSETS / f"param_template_{workflow}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No parameter template for ISCE2 workflow: {workflow!r}")
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _field(value: object, source: str, inferred_from: list[str] | None = None) -> dict:
    return {"value": value, "source": source, "inferred_from": inferred_from or []}


def _pick_context(user_context: dict, key: str, *, default: object = None) -> dict:
    if key in user_context and user_context[key] not in (None, ""):
        return _field(user_context[key], "user_provided")
    return _field(default, "missing")


def _safe_scene_summary(path: str | None) -> dict:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    try:
        scene_id, info = _read_safe_metadata(p)
    except Exception:
        return {}
    return {"scene_id": scene_id, **info}


def _sample_stack_summaries(slc_dir: str | None, limit: int = 3) -> list[dict]:
    if not slc_dir:
        return []
    root = Path(slc_dir)
    if not root.exists() or not root.is_dir():
        return []
    paths = sorted(list(root.glob("*.SAFE")) + list(root.glob("*.zip")))[:limit]
    summaries: list[dict] = []
    for path in paths:
        summary = _safe_scene_summary(str(path))
        if summary:
            summaries.append(summary)
    return summaries


def build_evidence_profile(
    params: dict,
    workflow: str,
    user_context: dict | None = None,
) -> dict:
    user_context = user_context or {}
    template = load_param_template(workflow)
    registry = load_processing_params(workflow)

    profile: dict = {
        "workflow": workflow,
        "template_summary": {
            "name": template.get("template_name"),
            "description": template.get("description"),
            "shared_defaults": template.get("shared_defaults", {}),
            "workflow_defaults": template.get("workflow_defaults", {}),
            "stack_only": template.get("stack_only", []),
            "single_pair_only": template.get("single_pair_only", []),
            "sources": template.get("sources", []),
        },
        "current_config": {item["key"]: deepcopy(params.get(item["key"])) for item in registry},
        "missing_information": [],
    }

    if workflow == "tops":
        ref = _safe_scene_summary(params.get("reference_safe"))
        sec = _safe_scene_summary(params.get("secondary_safe"))
        profile["data"] = {
            "sensor": _field("Sentinel-1", "template_inferred", ["SAFE metadata"]),
            "reference_scene": _field(ref.get("scene_id"), "metadata_inferred" if ref else "missing", [params.get("reference_safe", "")]),
            "secondary_scene": _field(sec.get("scene_id"), "metadata_inferred" if sec else "missing", [params.get("secondary_safe", "")]),
            "relative_orbit": _field(ref.get("relative_orbit") if ref else None, "metadata_inferred" if ref else "missing", [params.get("reference_safe", "")]),
            "pass_direction": _field(ref.get("pass_direction") if ref else None, "metadata_inferred" if ref else "missing", [params.get("reference_safe", "")]),
            "polarization": _field((ref.get("polarizations") or [None])[0] if ref else None, "metadata_inferred" if ref else "missing", [params.get("reference_safe", "")]),
            "bbox": _field(ref.get("bbox") if ref else None, "metadata_inferred" if ref else "missing", [params.get("reference_safe", "")]),
        }
    else:
        scenes = _sample_stack_summaries(params.get("slc_dir"))
        first = scenes[0] if scenes else {}
        profile["data"] = {
            "sensor": _field("Sentinel-1", "template_inferred", ["SAFE metadata"]),
            "sample_scene_count": _field(len(scenes), "metadata_inferred" if scenes else "missing", [params.get("slc_dir", "")]),
            "relative_orbit": _field(first.get("relative_orbit") if first else None, "metadata_inferred" if first else "missing", [params.get("slc_dir", "")]),
            "pass_direction": _field(first.get("pass_direction") if first else None, "metadata_inferred" if first else "missing", [params.get("slc_dir", "")]),
            "polarization": _field((first.get("polarizations") or [None])[0] if first else None, "metadata_inferred" if first else "missing", [params.get("slc_dir", "")]),
        }
        profile["sample_scenes"] = scenes

    profile["task"] = {
        "task_type": _pick_context(user_context, "task_type", default="single_pair" if workflow == "tops" else "time_series"),
        "prefer_fast_turnaround": _pick_context(user_context, "prefer_fast_turnaround", default=False),
        "prefer_stable_coherence": _pick_context(user_context, "prefer_stable_coherence", default=workflow == "stack"),
    }

    missing: list[str] = []
    for section in ("data", "task"):
        for key, item in profile[section].items():
            if isinstance(item, dict) and item.get("source") == "missing":
                missing.append(key)
    profile["missing_information"] = missing
    return profile


def build_default_param_package(workflow: str) -> dict:
    return {
        "workflow": workflow,
        "defaults": load_default_params(workflow),
        "template": load_param_template(workflow),
        "rules": load_param_advisor_rules(workflow),
        "registry": load_processing_params(workflow),
    }
