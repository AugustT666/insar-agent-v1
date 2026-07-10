from __future__ import annotations

import pytest

from insar_agent.core.config import get_path
from insar_agent.engines.isce3.adapter import ISCE3Adapter
from insar_agent.engines.isce3.defaults import ALLOWED_SET_FIELDS, load_default_runconfig

STAGE_ENABLE_KEYS = [
    "runconfig.groups.processing.dense_offsets.enabled",
    "runconfig.groups.processing.offsets_product.enabled",
    "runconfig.groups.processing.rubbersheet.enabled",
    "runconfig.groups.processing.fine_resample.enabled",
    "runconfig.groups.processing.ionosphere_phase_correction.enabled",
    "runconfig.groups.processing.troposphere_delay.enabled",
]


@pytest.mark.parametrize("key", STAGE_ENABLE_KEYS)
def test_stage_enable_key_in_allowed_set_fields(key: str) -> None:
    assert key in ALLOWED_SET_FIELDS["insar"]


@pytest.mark.parametrize("key", STAGE_ENABLE_KEYS)
def test_stage_enable_key_is_a_real_bool_path_in_default_template(key: str) -> None:
    """Guard against typos: every whitelisted stage toggle must resolve to a
    boolean in the shipped default insar runconfig template."""
    rc = load_default_runconfig("insar")
    value = get_path(rc, key)
    assert isinstance(value, bool)


@pytest.mark.parametrize("key", STAGE_ENABLE_KEYS)
def test_adapter_reports_stage_enable_keys_as_allowed(key: str) -> None:
    assert key in ISCE3Adapter().allowed_set_fields("insar")


def test_path_fields_still_present_after_extension() -> None:
    """Extending the whitelist must not drop the original path fields."""
    allowed = ALLOWED_SET_FIELDS["insar"]
    assert "runconfig.groups.input_file_group.reference_rslc_file" in allowed
    assert "runconfig.groups.product_path_group.product_path" in allowed
