from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import h5py
import numpy as np
import pytest

from insar_agent.engines.isce3 import download


def _build_source_h5(path: Path) -> None:
    with h5py.File(path, "w") as hf:
        swaths = hf.require_group("science/LSAR/RSLC/swaths")
        swaths.create_dataset("zeroDopplerTime", data=np.array([0.0, 1.0], dtype=np.float32))
        swaths.create_dataset("validSamplesSubSwath1", data=np.array([[0, 2], [0, 2]], dtype=np.uint32))

        freq_a = swaths.require_group("frequencyA")
        freq_a.create_dataset("slantRange", data=np.array([10.0, 11.0], dtype=np.float32))
        freq_a.create_dataset("HH", data=np.ones((2, 2), dtype=np.complex64))


def _build_complete_output(path: Path) -> None:
    with h5py.File(path, "w") as hf:
        swaths = hf.require_group("science/LSAR/RSLC/swaths")
        swaths.create_dataset("zeroDopplerTime", data=np.array([0.0, 1.0], dtype=np.float32))
        swaths.create_dataset("validSamplesSubSwath1", data=np.array([[0, 2], [0, 2]], dtype=np.uint32))

        freq_a = swaths.require_group("frequencyA")
        freq_a.create_dataset("slantRange", data=np.array([10.0, 11.0], dtype=np.float32))
        freq_a.create_dataset("HH", data=np.ones((2, 2), dtype=np.complex64))


class TestOpenRemote:
    def test_open_remote_uses_finite_timeout(self, tmp_path: Path):
        remote_path = tmp_path / "remote.h5"
        _build_source_h5(remote_path)
        captured: dict[str, object] = {}

        class FakeFS:
            def open(self, url: str, mode: str):
                assert url == "https://example.test/file.h5"
                assert mode == "rb"
                return open(remote_path, mode)

        fake_module = ModuleType("fsspec")

        def fake_filesystem(protocol: str, **kwargs):
            captured["protocol"] = protocol
            captured.update(kwargs)
            return FakeFS()

        fake_module.filesystem = fake_filesystem  # type: ignore[attr-defined]

        with patch.dict(sys.modules, {"fsspec": fake_module}):
            fobj, h5f = download._open_remote("https://example.test/file.h5")

        try:
            assert captured["protocol"] == "https"
            assert captured["client_kwargs"]["trust_env"] is True  # type: ignore[index]
            assert captured["client_kwargs"]["timeout"] is not None  # type: ignore[index]
            assert not isinstance(captured["client_kwargs"]["timeout"], int)  # type: ignore[index]
            assert h5f["science/LSAR/RSLC/swaths/frequencyA/HH"].shape == (2, 2)
        finally:
            h5f.close()
            fobj.close()


class TestParallelDownloadSlc:
    def test_parallel_download_raises_when_any_chunk_exhausts_retries(self):
        class FakeFuture:
            def __init__(self, value: bool):
                self._value = value

            def result(self) -> bool:
                return self._value

        class FakeExecutor:
            def __init__(self, max_workers: int):
                self.max_workers = max_workers

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def submit(self, fn, idx: int, c_az_start: int, c_az_end: int):
                return FakeFuture(idx != 1)

        with (
            patch.object(download, "ThreadPoolExecutor", FakeExecutor),
            patch.object(download, "as_completed", lambda futures: list(futures)),
        ):
            with pytest.raises(RuntimeError, match="chunk"):
                download._parallel_download_slc(
                    url="https://example.test/file.h5",
                    dataset_path="science/LSAR/RSLC/swaths/frequencyA/HH",
                    az_start=0,
                    az_end=512,
                    rg_start=0,
                    rg_end=1,
                    n_workers=2,
                    chunk_rows=256,
                )


class TestDownloadCroppedRslc:
    def test_download_cropped_rslc_skips_existing_complete_output(self, tmp_path: Path):
        source_path = tmp_path / "source.h5"
        output_path = tmp_path / "existing_cropped.h5"
        _build_source_h5(source_path)
        _build_complete_output(output_path)

        freq_info = {
            "A": {
                "az_start": 0,
                "az_end": 2,
                "rg_start": 0,
                "rg_end": 2,
                "n_az_orig": 2,
                "n_rg_orig": 2,
            }
        }
        progress: list[str] = []

        with h5py.File(source_path, "r") as h5f:
            with patch.object(download, "_parallel_download_slc", side_effect=AssertionError("should not redownload")):
                result = download.download_cropped_rslc(
                    h5f=h5f,
                    output_path=str(output_path),
                    freq_info=freq_info,
                    url="https://example.test/file.h5",
                    on_progress=progress.append,
                )

        assert result == str(output_path)
        assert any("skip" in msg.lower() for msg in progress)
