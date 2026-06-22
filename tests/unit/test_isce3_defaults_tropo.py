"""Tests that troposphere weather-model file paths are whitelisted in ISCE3 defaults."""
from __future__ import annotations

from insar_agent.engines.isce3.defaults import ALLOWED_SET_FIELDS


def test_troposphere_file_fields_whitelisted():
    fields = ALLOWED_SET_FIELDS["insar"]
    base = "runconfig.groups.dynamic_ancillary_file_group.troposphere_weather_model_files"
    assert f"{base}.reference_troposphere_file" in fields
    assert f"{base}.secondary_troposphere_file" in fields
