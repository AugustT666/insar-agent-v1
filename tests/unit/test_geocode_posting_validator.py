"""Unit tests for the geocode output_posting unit-safety guardrail.

Regression for the failure where geocode.output_posting.A = 30 (intended as
metres) was applied under a geographic output grid (output_epsg null -> EPSG:4326),
so 30 was read as 30 degrees and collapsed the geocoded GUNW grid to 1x1 pixel.
"""
from __future__ import annotations

import pytest

from insar_agent.engines.isce3.validator import validate_runconfig


def _runconfig(*, x_posting, y_posting=None, output_epsg=None) -> dict:
    return {
        "runconfig": {
            "groups": {
                "processing": {
                    "geocode": {
                        "output_epsg": output_epsg,
                        "output_posting": {
                            "A": {
                                "x_posting": x_posting,
                                "y_posting": y_posting if y_posting is not None else x_posting,
                            }
                        },
                    }
                }
            }
        }
    }


def _posting_errors(rc: dict) -> list[dict]:
    return [e for e in validate_runconfig(rc, "d-insar-isce3") if "output_posting" in e["key"]]


def test_metric_posting_under_null_epsg_is_rejected():
    errors = _posting_errors(_runconfig(x_posting=30, output_epsg=None))
    assert errors, "metric posting under geographic grid must be flagged"
    assert any("1x1" in e["message"] for e in errors)
    assert any("UTM" in e["suggestion"] for e in errors)


def test_metric_posting_under_4326_is_rejected():
    errors = _posting_errors(_runconfig(x_posting=30.0, output_epsg=4326))
    assert errors


def test_degree_posting_under_null_epsg_is_allowed():
    errors = _posting_errors(_runconfig(x_posting=0.000277, output_epsg=None))
    assert errors == []


def test_metric_posting_with_utm_epsg_is_allowed():
    errors = _posting_errors(_runconfig(x_posting=30, output_epsg=32637))
    assert errors == []


def test_null_posting_is_allowed():
    errors = _posting_errors(_runconfig(x_posting=None, output_epsg=None))
    assert errors == []


@pytest.mark.parametrize("bad", [30, 30.0, "30", 100])
def test_various_metric_values_rejected(bad):
    assert _posting_errors(_runconfig(x_posting=bad, output_epsg=None))
