from __future__ import annotations

import pytest

from insar_agent.core.jobs import BatchJob, DownloadJob, Job


@pytest.mark.parametrize("bad_job_id", ["", " ../evil", "../evil", "evil/next", "evil\\next", "safe..evil"])
def test_job_load_rejects_path_components(tmp_path, bad_job_id):
    with pytest.raises(ValueError):
        Job.load(bad_job_id, tmp_path / "jobs")


@pytest.mark.parametrize("bad_job_id", ["", "../evil", "evil/next", "evil\\next", "safe..evil"])
def test_batch_job_load_rejects_path_components(tmp_path, bad_job_id):
    with pytest.raises(ValueError):
        BatchJob.load(bad_job_id, tmp_path / "batch")


@pytest.mark.parametrize("bad_job_id", ["", "../evil", "evil/next", "evil\\next", "safe..evil"])
def test_download_job_load_rejects_path_components(tmp_path, bad_job_id):
    with pytest.raises(ValueError):
        DownloadJob.load(bad_job_id, tmp_path / "downloads")


def test_job_load_still_reports_missing_safe_id(tmp_path):
    with pytest.raises(FileNotFoundError):
        Job.load("missing-job", tmp_path / "jobs")
