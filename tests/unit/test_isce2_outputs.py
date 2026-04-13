from __future__ import annotations

from pathlib import Path

from insar_agent.core.jobs import Job
from insar_agent.mcp.server import insar_create_project, insar_list_outputs


def test_insar_list_outputs_includes_isce2_merged_artifacts(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "registry"))

    workspace = tmp_path / "isce2-dinsar"
    created = insar_create_project(
        engine="isce2",
        workflow="tops",
        workspace_root=str(workspace),
        name="isce2-out-test",
        conda_env="isce2",
    )
    project_id = created["project_id"]

    merged = workspace / "merged"
    merged.mkdir(parents=True, exist_ok=True)
    (merged / "filt_topophase.unw.geo").write_bytes(b"geo")
    (merged / "phsig.cor.geo").write_bytes(b"cor")

    job = Job(project_id=project_id, engine="isce2", workflow="tops", status="done")
    job.save(workspace / ".insar_agent" / "jobs")

    result = insar_list_outputs(job_id=job.job_id, project_id=project_id)
    paths = {item["path"] for item in result["outputs"]}

    assert str(merged / "filt_topophase.unw.geo") in paths
    assert str(merged / "phsig.cor.geo") in paths
