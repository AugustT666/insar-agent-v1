from __future__ import annotations

from insar_agent.engines.isce2.defaults import (
    get_mintpy_processing_param_keys,
    load_mintpy_processing_params,
)

_STARTER_KEYS = [
    "network.tempBaseMax",
    "network.perpBaseMax",
    "network.excludeDate",
    "network.coherenceBased",
    "network.minCoherence",
    "troposphericDelay.method",
    "troposphericDelay.weatherModel",
    "unwrapError.method",
    "deramp",
    "solidEarthTides",
    "ionosphericDelay.method",
    "topographicResidual",
    "networkInversion.minTempCoh",
    "networkInversion.weightFunc",
    "reference.minCoherence",
]


def test_mintpy_registry_contains_starter_science_keys():
    keys = get_mintpy_processing_param_keys()
    for expected in _STARTER_KEYS:
        assert expected in keys, expected


def test_mintpy_registry_entries_have_type_and_risk():
    for p in load_mintpy_processing_params():
        assert "type" in p, p
        assert "risk_level" in p, p
        assert p["type"] in {"str", "int", "float", "bool", "list"}, p
        assert p["risk_level"] in {"low", "medium", "high"}, p


def test_registry_has_new_network_trimming_keys():
    keys = get_mintpy_processing_param_keys()
    assert "network.keepMinSpanTree" in keys
    assert "network.excludeIfgIndex" in keys


def test_registry_has_compute_parallelism_keys():
    keys = get_mintpy_processing_param_keys()
    assert "compute.cluster" in keys
    assert "compute.numWorker" in keys


def test_mintpy_registry_ranges_and_values():
    meta = {p["key"]: p for p in load_mintpy_processing_params()}
    assert meta["reference.minCoherence"]["valid_range"] == [0.0, 1.0]
    assert meta["networkInversion.minTempCoh"]["valid_range"] == [0.0, 1.0]
    assert meta["network.minCoherence"]["valid_range"] == [0.0, 1.0]
    assert "pyaps" in meta["troposphericDelay.method"]["valid_values"]
    assert "ERA5" in meta["troposphericDelay.weatherModel"]["valid_values"]
    assert meta["solidEarthTides"]["type"] == "bool"
    assert meta["topographicResidual"]["type"] == "bool"
