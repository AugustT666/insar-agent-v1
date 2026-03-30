from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
import re

import yaml

from insar_agent.core.config import get_path
from insar_agent.engines.isce3.defaults import load_default_runconfig, load_processing_params

_ASSETS = Path(__file__).parent / "assets"
_RSLC_TIMESTAMP_RE = re.compile(r"_(\d{8}T\d{6})_")


def load_param_advisor_rules(workflow: str) -> dict:
    """Load evidence and recommendation rules for the parameter advisor."""
    path = _ASSETS / f"param_advisor_rules_{workflow}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No parameter advisor rules for workflow: {workflow!r}")
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _infer_timestamp(path: str | None) -> datetime | None:
    if not path:
        return None
    match = _RSLC_TIMESTAMP_RE.search(path)
    if not match:
        return None
    return datetime.strptime(match.group(1), "%Y%m%dT%H%M%S")


def _field(value: object, source: str, inferred_from: list[str] | None = None) -> dict:
    return {
        "value": value,
        "source": source,
        "inferred_from": inferred_from or [],
    }


def _pick_context(user_context: dict, key: str, *, default: object = None) -> dict:
    if key in user_context and user_context[key] not in (None, ""):
        return _field(user_context[key], "user_provided")
    return _field(default, "missing")


def build_evidence_profile(
    runconfig: dict,
    workflow: str = "insar",
    user_context: dict | None = None,
) -> dict:
    """Build a machine-readable evidence profile from runconfig and user context."""
    del workflow  # reserved for future non-insar support
    user_context = user_context or {}

    reference = get_path(runconfig, "runconfig.groups.input_file_group.reference_rslc_file")
    secondary = get_path(runconfig, "runconfig.groups.input_file_group.secondary_rslc_file")
    polarization_list = get_path(
        runconfig,
        "runconfig.groups.processing.input_subset.list_of_frequencies.A",
    )
    reference_time = _infer_timestamp(reference)
    secondary_time = _infer_timestamp(secondary)
    temporal_baseline = None
    if reference_time and secondary_time:
        temporal_baseline = abs((secondary_time - reference_time).days)

    sensor = "NISAR" if "NISAR" in f"{reference} {secondary}" else None
    band = "L" if "NISAR_L" in f"{reference} {secondary}" else None
    orbit_direction = None
    if reference:
        orbit_match = re.search(r"_([AD])_\d{3}_", reference)
        if orbit_match:
            orbit_direction = "ascending" if orbit_match.group(1) == "A" else "descending"

    current_values = {}
    for param in load_processing_params("insar"):
        try:
            current_values[param["key"]] = get_path(runconfig, param["key"])
        except KeyError:
            current_values[param["key"]] = None

    profile = {
        "data": {
            "sensor": _field(sensor, "metadata_inferred" if sensor else "missing", [reference, secondary]),
            "band": _field(band, "metadata_inferred" if band else "missing", [reference, secondary]),
            "polarization": _field(
                polarization_list[0] if polarization_list else None,
                "runconfig_inferred" if polarization_list else "missing",
                ["runconfig.groups.processing.input_subset.list_of_frequencies.A"],
            ),
            "orbit_direction": _field(
                orbit_direction,
                "metadata_inferred" if orbit_direction else "missing",
                [reference] if reference else [],
            ),
            "temporal_baseline_days": _field(
                temporal_baseline,
                "metadata_inferred" if temporal_baseline is not None else "missing",
                [reference, secondary],
            ),
        },
        "scene": {
            "landcover": _pick_context(user_context, "landcover"),
            "climate": _pick_context(user_context, "climate"),
            "latitude_deg": _pick_context(user_context, "latitude_deg"),
            "coverage_scale_km": _pick_context(user_context, "coverage_scale_km"),
            "topographic_relief_m": _pick_context(user_context, "topographic_relief_m"),
        },
        "task": {
            "task_type": _pick_context(user_context, "task_type"),
            "deformation_magnitude": _pick_context(user_context, "deformation_magnitude"),
            "deformation_scale": _pick_context(user_context, "deformation_scale"),
        },
        "engineering": {
            "prefer_fast_turnaround": _pick_context(user_context, "prefer_fast_turnaround", default=False),
            "allow_high_risk_corrections": _pick_context(user_context, "allow_high_risk_corrections", default=False),
        },
        "current_config": current_values,
        "missing_information": [],
    }

    missing = []
    for section in ("data", "scene", "task"):
        for key, item in profile[section].items():
            if item["source"] == "missing":
                missing.append(key)
    profile["missing_information"] = missing
    return profile


def _rule_recommendation(
    key: str,
    suggested_value: object,
    default_value: object,
    risk_level: str,
    confidence: str,
    rationale: str,
    evidence: list[str],
) -> dict:
    return {
        "key": key,
        "default_value": default_value,
        "suggested_value": suggested_value,
        "risk_level": risk_level,
        "confidence": confidence,
        "rationale": rationale,
        "evidence": evidence,
    }


def generate_parameter_recommendations(
    runconfig: dict,
    workflow: str = "insar",
    user_context: dict | None = None,
) -> dict:
    """Generate evidence-driven parameter recommendations for the advisor skill."""
    profile = build_evidence_profile(runconfig, workflow=workflow, user_context=user_context)
    metadata = {item["key"]: item for item in load_processing_params(workflow)}
    default_runconfig = load_default_runconfig(workflow)
    recommendations: list[dict] = []

    landcover = profile["scene"]["landcover"]["value"]
    band = profile["data"]["band"]["value"]
    temporal_baseline = profile["data"]["temporal_baseline_days"]["value"]
    task_type = profile["task"]["task_type"]["value"]
    deformation_magnitude = profile["task"]["deformation_magnitude"]["value"]
    deformation_scale = profile["task"]["deformation_scale"]["value"]
    coverage_scale_km = profile["scene"]["coverage_scale_km"]["value"]
    topographic_relief_m = profile["scene"]["topographic_relief_m"]["value"]
    climate = profile["scene"]["climate"]["value"]
    latitude_deg = profile["scene"]["latitude_deg"]["value"]

    if landcover == "urban" and band == "L" and temporal_baseline is not None and temporal_baseline < 30:
        for key, value in (
            ("runconfig.groups.processing.crossmul.range_looks", 5),
            ("runconfig.groups.processing.crossmul.azimuth_looks", 5),
        ):
            recommendations.append(
                _rule_recommendation(
                    key,
                    value,
                    get_path(default_runconfig, key),
                    metadata[key]["risk_level"],
                    "high",
                    "城市 L 波段短时间基线通常保持较高相干性，可减小多视数以保留分辨率。",
                    [
                        f"landcover={landcover}",
                        f"band={band}",
                        f"temporal_baseline_days={temporal_baseline}",
                    ],
                )
            )

    if landcover in {"agriculture", "vegetation"} and temporal_baseline is not None and temporal_baseline > 60:
        recommendations.append(
            _rule_recommendation(
                "runconfig.groups.processing.filter_interferogram.filter_type",
                "boxcar",
                get_path(default_runconfig, "runconfig.groups.processing.filter_interferogram.filter_type"),
                metadata["runconfig.groups.processing.filter_interferogram.filter_type"]["risk_level"],
                "medium",
                "植被或农业区长时间基线常出现较强相位噪声，可启用 boxcar 滤波作为保守稳健方案。",
                [
                    f"landcover={landcover}",
                    f"temporal_baseline_days={temporal_baseline}",
                ],
            )
        )

    if deformation_magnitude == "large":
        recommendations.append(
            _rule_recommendation(
                "runconfig.groups.processing.phase_unwrap.snaphu.cost_mode",
                "defo",
                get_path(default_runconfig, "runconfig.groups.processing.phase_unwrap.snaphu.cost_mode"),
                metadata["runconfig.groups.processing.phase_unwrap.snaphu.cost_mode"]["risk_level"],
                "high",
                "大形变场景更适合使用 defo 代价函数以保留真实相位梯度。",
                [f"deformation_magnitude={deformation_magnitude}"],
            )
        )
    if deformation_magnitude == "large" and coverage_scale_km and coverage_scale_km >= 50:
        recommendations.append(
            _rule_recommendation(
                "runconfig.groups.processing.phase_unwrap.snaphu.ntiles",
                [4, 4],
                get_path(default_runconfig, "runconfig.groups.processing.phase_unwrap.snaphu.ntiles"),
                metadata["runconfig.groups.processing.phase_unwrap.snaphu.ntiles"]["risk_level"],
                "medium",
                "大形变且覆盖范围较大时，分块解缠能降低误差跨区传播风险。",
                [
                    f"deformation_magnitude={deformation_magnitude}",
                    f"coverage_scale_km={coverage_scale_km}",
                ],
            )
        )
    if (
        band == "L"
        and latitude_deg is not None
        and abs(latitude_deg) >= 50
    ):
        recommendations.append(
            _rule_recommendation(
                "runconfig.groups.processing.ionosphere_phase_correction.enabled",
                True,
                get_path(default_runconfig, "runconfig.groups.processing.ionosphere_phase_correction.enabled"),
                metadata["runconfig.groups.processing.ionosphere_phase_correction.enabled"]["risk_level"],
                "medium",
                "L 波段高纬度区域更容易受到电离层影响，应优先提示开启校正。",
                [f"band={band}", f"latitude_deg={latitude_deg}"],
            )
        )
    if (
        topographic_relief_m is not None
        and topographic_relief_m >= 500
        and coverage_scale_km is not None
        and coverage_scale_km >= 100
    ) or (
        climate in {"coastal", "monsoon", "humid"}
        and coverage_scale_km is not None
        and coverage_scale_km >= 100
    ):
        evidence = []
        if topographic_relief_m is not None:
            evidence.append(f"topographic_relief_m={topographic_relief_m}")
        if climate:
            evidence.append(f"climate={climate}")
        if coverage_scale_km is not None:
            evidence.append(f"coverage_scale_km={coverage_scale_km}")
        recommendations.append(
            _rule_recommendation(
                "runconfig.groups.processing.troposphere_delay.enabled",
                True,
                get_path(default_runconfig, "runconfig.groups.processing.troposphere_delay.enabled"),
                metadata["runconfig.groups.processing.troposphere_delay.enabled"]["risk_level"],
                "medium",
                "大范围高起伏或湿润沿海场景更可能受对流层延迟影响，建议纳入校正评估。",
                evidence,
            )
        )

    if task_type == "time_series" and not any(
        item["key"] == "runconfig.groups.processing.crossmul.range_looks" for item in recommendations
    ):
        recommendations.append(
            _rule_recommendation(
                "runconfig.groups.processing.crossmul.range_looks",
                13,
                get_path(default_runconfig, "runconfig.groups.processing.crossmul.range_looks"),
                metadata["runconfig.groups.processing.crossmul.range_looks"]["risk_level"],
                "medium",
                "时序分析优先保证稳定相干性，可适度提高多视数。",
                [f"task_type={task_type}"],
            )
        )
        recommendations.append(
            _rule_recommendation(
                "runconfig.groups.processing.crossmul.azimuth_looks",
                13,
                get_path(default_runconfig, "runconfig.groups.processing.crossmul.azimuth_looks"),
                metadata["runconfig.groups.processing.crossmul.azimuth_looks"]["risk_level"],
                "medium",
                "时序分析优先保证稳定相干性，可适度提高多视数。",
                [f"task_type={task_type}"],
            )
        )

    unchanged = []
    recommended_keys = {item["key"] for item in recommendations}
    for param in load_processing_params(workflow):
        if param["key"] in recommended_keys:
            continue
        unchanged.append(
            {
                "key": param["key"],
                "default_value": deepcopy(param["default"]),
                "reason": "当前证据不足以支持偏离模板默认值。",
            }
        )

    return {
        "workflow": workflow,
        "evidence_profile": profile,
        "recommendations": recommendations,
        "unchanged": unchanged,
        "missing_information": profile["missing_information"],
    }
