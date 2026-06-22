"""Tests for the velocity before/after/residual comparison figure (T8)."""
from __future__ import annotations

import numpy as np
import pytest
from pathlib import Path
from insar_agent.engines import raster_export as rx

h5py = pytest.importorskip("h5py")


def _vel_h5(path, arr):
    with h5py.File(path, "w") as f:
        d = f.create_dataset("velocity", data=arr.astype("float32"))  # noqa: F841
        f.attrs.update({"X_FIRST": 116.0, "Y_FIRST": 40.0, "X_STEP": 0.01,
                        "Y_STEP": -0.01, "WIDTH": arr.shape[1], "LENGTH": arr.shape[0],
                        "EPSG": 4326})


def test_velocity_residual_style_present():
    assert "velocity_residual" in rx._BROWSE_STYLE


def test_plot_velocity_comparison_makes_png_and_residual(tmp_path):
    a = np.random.RandomState(0).rand(8, 10) * 0.1 - 0.05
    b = a - 0.01
    _vel_h5(tmp_path / "velocity.h5", a)
    _vel_h5(tmp_path / "velocity_ERA5.h5", b)
    res = rx.plot_velocity_comparison(tmp_path, tmp_path / "out", tag="E")
    assert res["png"] and (tmp_path / "out" / "browse" / res["png"]).exists()
    assert res["residual_tif"] and (tmp_path / "out" / res["residual_tif"]).exists()


def test_plot_velocity_comparison_noop_without_after(tmp_path):
    _vel_h5(tmp_path / "velocity.h5", np.zeros((4, 4)))
    res = rx.plot_velocity_comparison(tmp_path, tmp_path / "out", tag="E")
    assert res == {"png": None, "residual_tif": None}
