"""Tests for Layer-1 progress logging module."""
from pathlib import Path
import pytest


def test_append_and_tail(tmp_path):
    """Test appending progress entries and reading tail."""
    from insar_agent.core.progress import append_progress, read_progress_tail

    rr = tmp_path / "run"
    (rr / ".insar_agent").mkdir(parents=True)

    append_progress(rr, "下载 DEM")
    append_progress(rr, "SYNTHESIZE", step=12, total=31)

    t = read_progress_tail(rr, n=5)
    assert "下载 DEM" in t
    assert "[12/31] SYNTHESIZE" in t
