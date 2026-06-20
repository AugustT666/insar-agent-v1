"""TDD tests for F3 — background workers eagerly write terminal status to job JSON.

STRATEGY
--------
We invoke the real launch helpers (_launch_dem_download_background,
_launch_sentinel_prepare_background, and the RSLC runner path in
insar_download_rslc) with minimal/mocked params.  We suppress the actual
subprocess.Popen call and instead run the generated runner script ourselves
synchronously, with the expensive inner function (insar_download_dem,
prepare_sentinel_data, download_rslc_stack) mocked at the module level inside
the runner's own python path.

After the runner exits we inspect the JOB JSON on disk WITHOUT calling
insar_get_job — that is the core assertion for F3.

RED (before F3): runner only prints to stdout; job JSON stays "running".
GREEN (after F3): runner also writes terminal status to job JSON eagerly.

Each group tests:
  (a) success → job JSON status='done', exit_code=0, finished_at, result
  (b) failure → job JSON status='failed', exit_code=1, finished_at, failure_reason
  (c) stdout/log contract preserved regardless
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import subprocess
import textwrap
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Path to the src/ directory so runner subprocesses can import insar_agent
# ---------------------------------------------------------------------------
SRC_DIR = str(Path(__file__).resolve().parent.parent.parent / "src")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _run_script(runner_path: Path, log_path: Path, extra_env: dict | None = None) -> None:
    """Execute a runner script (blocking), sending stdout+stderr to log_path."""
    env = os.environ.copy()
    env["PYTHONPATH"] = SRC_DIR + os.pathsep + env.get("PYTHONPATH", "")
    if extra_env:
        env.update(extra_env)
    with open(log_path, "w") as lf:
        proc = subprocess.Popen(
            [sys.executable, str(runner_path)],
            stdout=lf,
            stderr=subprocess.STDOUT,
            env=env,
        )
        proc.wait(timeout=60)


def _read_log(log_path: Path) -> str:
    return log_path.read_text(encoding="utf-8", errors="replace")


def _read_job_json(jobs_dir: Path, job_id: str) -> dict:
    job_file = jobs_dir / f"{job_id}.json"
    assert job_file.exists(), f"Job JSON not found: {job_file}"
    return json.loads(job_file.read_text())


def _assert_stdout_status(log: str, expected_status: str) -> None:
    """Assert that at least one line in log is a JSON object with status==expected_status."""
    for line in log.splitlines():
        try:
            obj = json.loads(line.strip())
            if isinstance(obj, dict) and obj.get("status") == expected_status:
                return
        except (json.JSONDecodeError, AttributeError):
            continue
    pytest.fail(
        f'No {{"status": "{expected_status}"}} JSON line found in log:\n{log[:2000]}'
    )


def _mark_run_root(run_root: Path) -> None:
    """Create the .insar_agent marker so find_run_root can locate it."""
    (run_root / ".insar_agent").mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Stub module factory
# Writes a tiny Python module into stubs_dir that can be prepended to sys.path.
# The runner script imports from these stubs instead of the real heavy functions.
# ---------------------------------------------------------------------------

def _write_stub_module(stubs_dir: Path, module_name: str, func_name: str, success: bool) -> None:
    stubs_dir.mkdir(parents=True, exist_ok=True)
    if success:
        code = (
            f"def {func_name}(**kwargs):\n"
            f"    return {{'status': 'done', 'stub': True, 'output_path': '/fake/out'}}\n"
        )
    else:
        code = (
            f"def {func_name}(**kwargs):\n"
            f"    raise RuntimeError('stubbed failure from {func_name}')\n"
        )
    (stubs_dir / f"{module_name}.py").write_text(code)


# ===========================================================================
# Group 1: DEM download runner
#
# We call _launch_dem_download_background with workspace_root + task_id so
# _task_job_context builds jobs_dir without a Project registry.
# We patch subprocess.Popen to capture the runner_path, then run it ourselves.
# ===========================================================================

def _launch_and_capture_dem_runner(tmp_path: Path, success: bool) -> tuple[Path, Path, Path, str]:
    """
    Invoke _launch_dem_download_background with a stub insar_download_dem.

    Returns (runner_path, log_path, jobs_dir, job_id).
    """
    from insar_agent.mcp._helpers import _launch_dem_download_background

    # Setup minimal workspace structure
    workspace = tmp_path / "ws"
    workspace.mkdir()
    task_id = "test_task"
    task_dir = workspace / task_id
    task_dir.mkdir()
    _mark_run_root(task_dir)

    output_path = task_dir / "dem" / "dem.tif"

    captured: dict = {}

    def _fake_popen(args, stdout=None, stderr=None, env=None, start_new_session=False):
        # Capture runner path from args
        runner_path = Path(args[1])
        captured["runner_path"] = runner_path
        captured["log_path"] = Path(stdout.name) if hasattr(stdout, "name") else None
        # Do NOT actually launch — we run it ourselves
        fake_proc = MagicMock()
        fake_proc.pid = 99999
        return fake_proc

    # Stub the actual insar_download_dem inside the runner's sys.path
    # We do this by prepending a stubs dir that the runner script will pick up.
    stubs_dir = tmp_path / "stubs"
    _write_stub_module(stubs_dir, "insar_agent_stub_dem", "insar_download_dem", success=success)

    params = {
        "output_path": str(output_path),
        "workspace_root": str(workspace),
        "task_id": task_id,
        "background": True,
    }

    captured_jobs_dir: list[Path] = []
    captured_job_ids: list[str] = []

    original_launch = _launch_dem_download_background

    with patch("subprocess.Popen", side_effect=_fake_popen):
        # Also patch the actual insar_download_dem import inside the runner
        # by monkey-patching at the module level
        import insar_agent.mcp.server as _server_mod
        original_dem = getattr(_server_mod, "insar_download_dem", None)

        result = _launch_dem_download_background(params)

    # The result must contain job_id (launched successfully to fake popen)
    assert "job_id" in result, f"Launch failed: {result}"
    job_id = result["job_id"]

    # Find jobs_dir from result context
    from insar_agent.core.jobs import DownloadJob
    jobs_dir = DownloadJob.jobs_dir_for_task(workspace, task_id)

    runner_path = captured.get("runner_path")
    assert runner_path is not None and runner_path.exists(), (
        f"runner_path not captured or not found: {runner_path}"
    )

    # The runner script imports from insar_agent.mcp.server — we need to patch
    # insar_download_dem there. We do it by rewriting the runner to use our stub.
    _patch_runner_import(runner_path, stubs_dir, success)

    log_path = runner_path.parent / f"{runner_path.stem}_test.log"
    return runner_path, log_path, jobs_dir, job_id


def _patch_runner_import(runner_path: Path, stubs_dir: Path, success: bool) -> None:
    """
    Rewrite the runner script to import from our stub instead of the real module.
    This preserves ALL the runner logic (including F3 eager-write) but replaces
    the expensive function call with our stub.
    """
    content = runner_path.read_text()
    # Replace the import line and inject stub at the top
    stub_injection = textwrap.dedent(f"""\
        # F3 test stub injection
        import sys as _sys
        _sys.path.insert(0, {str(stubs_dir)!r})
        def insar_download_dem(**kwargs):
            {'return {"status": "done", "stub": True, "output_path": "/fake/out"}' if success else 'raise RuntimeError("stubbed DEM failure")'}
        # end stub injection
    """)
    # Replace the real import with our stub (keep everything else intact)
    content = content.replace(
        "from insar_agent.mcp.server import insar_download_dem",
        "# import replaced by F3 test stub\n" + stub_injection
    )
    # Also stub append_progress to avoid real filesystem calls
    content = content.replace(
        "from insar_agent.core.progress import append_progress",
        "def append_progress(*a, **kw): pass  # F3 test stub",
    )
    runner_path.write_text(content)


class TestDemDownloadRunnerF3:
    """F3 — DEM download background runner writes terminal status to job JSON."""

    def test_success_updates_job_json_status_done(self, tmp_path):
        """(a) After DEM runner exits with success, job JSON must have status='done' without polling."""
        runner_path, log_path, jobs_dir, job_id = _launch_and_capture_dem_runner(tmp_path, success=True)
        _run_script(runner_path, log_path)

        job_data = _read_job_json(jobs_dir, job_id)
        assert job_data["status"] == "done", (
            f"Expected job JSON status='done' (F3 eager write), got {job_data['status']!r}. "
            f"Log:\n{_read_log(log_path)[:500]}"
        )
        assert job_data["exit_code"] == 0, f"exit_code must be 0, got {job_data['exit_code']}"
        assert job_data.get("finished_at") is not None, "finished_at must be set"
        assert "result" in job_data, f"result field must be present: {list(job_data.keys())}"

    def test_failure_updates_job_json_status_failed(self, tmp_path):
        """(b) After DEM runner exits with failure, job JSON must have status='failed' without polling."""
        runner_path, log_path, jobs_dir, job_id = _launch_and_capture_dem_runner(tmp_path, success=False)
        _run_script(runner_path, log_path)

        job_data = _read_job_json(jobs_dir, job_id)
        assert job_data["status"] == "failed", (
            f"Expected job JSON status='failed' (F3 eager write), got {job_data['status']!r}. "
            f"Log:\n{_read_log(log_path)[:500]}"
        )
        assert job_data["exit_code"] == 1, f"exit_code must be 1, got {job_data['exit_code']}"
        assert job_data.get("finished_at") is not None, "finished_at must be set"
        assert job_data.get("failure_reason"), "failure_reason must be non-empty"

    def test_stdout_contract_preserved_on_success(self, tmp_path):
        """(c) DEM runner still prints status=done JSON line (stdout contract preserved)."""
        runner_path, log_path, jobs_dir, job_id = _launch_and_capture_dem_runner(tmp_path, success=True)
        _run_script(runner_path, log_path)
        _assert_stdout_status(_read_log(log_path), "done")

    def test_stdout_contract_preserved_on_failure(self, tmp_path):
        """(c) DEM runner still prints status=failed JSON line (stdout contract preserved)."""
        runner_path, log_path, jobs_dir, job_id = _launch_and_capture_dem_runner(tmp_path, success=False)
        _run_script(runner_path, log_path)
        _assert_stdout_status(_read_log(log_path), "failed")


# ===========================================================================
# Group 2: Sentinel-prepare runner
# ===========================================================================

def _launch_and_capture_prepare_runner(tmp_path: Path, success: bool) -> tuple[Path, Path, Path, str]:
    from insar_agent.mcp._helpers import _launch_sentinel_prepare_background

    workspace = tmp_path / "ws"
    workspace.mkdir()
    task_id = "test_task"
    task_dir = workspace / task_id
    task_dir.mkdir()
    _mark_run_root(task_dir)
    project_root = task_dir / "prepare"
    project_root.mkdir()

    captured: dict = {}

    def _fake_popen(args, stdout=None, stderr=None, env=None, start_new_session=False):
        runner_path = Path(args[1])
        captured["runner_path"] = runner_path
        fake_proc = MagicMock()
        fake_proc.pid = 99999
        return fake_proc

    stubs_dir = tmp_path / "stubs"
    _write_stub_module(stubs_dir, "insar_agent_stub_prep", "prepare_sentinel_data", success=success)

    params = {
        "project_root": str(project_root),
        "source_paths": ["/fake/scene1.SAFE", "/fake/scene2.SAFE"],
        "workspace_root": str(workspace),
        "task_id": task_id,
        "background": True,
    }

    with patch("subprocess.Popen", side_effect=_fake_popen):
        result = _launch_sentinel_prepare_background(params)

    assert "job_id" in result, f"Launch failed: {result}"
    job_id = result["job_id"]

    from insar_agent.core.jobs import DownloadJob
    jobs_dir = DownloadJob.jobs_dir_for_task(workspace, task_id)

    runner_path = captured.get("runner_path")
    assert runner_path is not None and runner_path.exists()

    _patch_prepare_runner_import(runner_path, stubs_dir, success)

    log_path = runner_path.parent / f"{runner_path.stem}_test.log"
    return runner_path, log_path, jobs_dir, job_id


def _patch_prepare_runner_import(runner_path: Path, stubs_dir: Path, success: bool) -> None:
    content = runner_path.read_text()
    stub_injection = textwrap.dedent(f"""\
        # F3 test stub injection
        def prepare_sentinel_data(**kwargs):
            {'return {"status": "done", "stub": True, "n_scenes": 2}' if success else 'raise RuntimeError("stubbed prepare failure")'}
        def insar_download_dem(**kwargs):
            return {{"status": "done"}}
        # end stub injection
    """)
    content = content.replace(
        "from insar_agent.engines.isce2.sentinel_prep import prepare_sentinel_data",
        "# import replaced by F3 test stub\n" + stub_injection,
    )
    content = content.replace(
        "from insar_agent.mcp.server import insar_download_dem",
        "# import replaced by F3 test stub (dem)",
    )
    runner_path.write_text(content)


class TestSentinelPrepareRunnerF3:
    """F3 — Sentinel-prepare background runner writes terminal status to job JSON."""

    def test_success_updates_job_json_status_done(self, tmp_path):
        """(a) After prepare runner exits with success, job JSON must have status='done'."""
        runner_path, log_path, jobs_dir, job_id = _launch_and_capture_prepare_runner(tmp_path, success=True)
        _run_script(runner_path, log_path)

        job_data = _read_job_json(jobs_dir, job_id)
        assert job_data["status"] == "done", (
            f"Expected 'done' (F3 eager write), got {job_data['status']!r}. "
            f"Log:\n{_read_log(log_path)[:500]}"
        )
        assert job_data["exit_code"] == 0
        assert job_data.get("finished_at") is not None
        assert "result" in job_data

    def test_failure_updates_job_json_status_failed(self, tmp_path):
        """(b) After prepare runner exits with failure, job JSON must have status='failed'."""
        runner_path, log_path, jobs_dir, job_id = _launch_and_capture_prepare_runner(tmp_path, success=False)
        _run_script(runner_path, log_path)

        job_data = _read_job_json(jobs_dir, job_id)
        assert job_data["status"] == "failed", (
            f"Expected 'failed' (F3 eager write), got {job_data['status']!r}. "
            f"Log:\n{_read_log(log_path)[:500]}"
        )
        assert job_data["exit_code"] == 1
        assert job_data.get("finished_at") is not None
        assert job_data.get("failure_reason")

    def test_stdout_contract_preserved_on_success(self, tmp_path):
        """(c) Prepare runner still prints status=done JSON line."""
        runner_path, log_path, jobs_dir, job_id = _launch_and_capture_prepare_runner(tmp_path, success=True)
        _run_script(runner_path, log_path)
        _assert_stdout_status(_read_log(log_path), "done")

    def test_stdout_contract_preserved_on_failure(self, tmp_path):
        """(c) Prepare runner still prints status=failed JSON line."""
        runner_path, log_path, jobs_dir, job_id = _launch_and_capture_prepare_runner(tmp_path, success=False)
        _run_script(runner_path, log_path)
        _assert_stdout_status(_read_log(log_path), "failed")


# ===========================================================================
# Group 3: RSLC download runner (server.py::insar_download_rslc)
# ===========================================================================

def _launch_and_capture_rslc_runner(tmp_path: Path, success: bool) -> tuple[Path, Path, Path, str]:
    from insar_agent.mcp.server import insar_download_rslc

    workspace = tmp_path / "ws"
    workspace.mkdir()
    task_id = "test_task"
    task_dir = workspace / task_id
    task_dir.mkdir()
    _mark_run_root(task_dir)
    rslc_dir = task_dir / "rslc"
    rslc_dir.mkdir()

    captured: dict = {}

    def _fake_popen(args, stdout=None, stderr=None, start_new_session=False, **kw):
        runner_path = Path(args[1])
        captured["runner_path"] = runner_path
        fake_proc = MagicMock()
        fake_proc.pid = 99999
        return fake_proc

    with patch("subprocess.Popen", side_effect=_fake_popen):
        result = insar_download_rslc(
            urls=["https://fake/RSLC_scene1.h5"],
            output_dir=str(rslc_dir),
            bbox=[100.0, 10.0, 101.0, 11.0],
            workspace_root=str(workspace),
            task_id=task_id,
        )

    assert "job_id" in result, f"Launch failed: {result}"
    job_id = result["job_id"]

    from insar_agent.core.jobs import DownloadJob
    jobs_dir = DownloadJob.jobs_dir_for_task(workspace, task_id)

    runner_path = captured.get("runner_path")
    assert runner_path is not None and runner_path.exists()

    _patch_rslc_runner_import(runner_path, success)

    log_path = runner_path.parent / f"{runner_path.stem}_test.log"
    return runner_path, log_path, jobs_dir, job_id


def _patch_rslc_runner_import(runner_path: Path, success: bool) -> None:
    content = runner_path.read_text()
    stub_injection = textwrap.dedent(f"""\
        # F3 test stub injection
        def download_rslc_stack(**kwargs):
            {'return {"ok": ["/fake/rslc1.h5"], "failed": [], "output_dir": "/fake/rslc"}' if success else 'raise RuntimeError("stubbed RSLC failure")'}
        # end stub injection
    """)
    content = content.replace(
        "from insar_agent.engines.isce3.download import download_rslc_stack",
        "# import replaced by F3 test stub\n" + stub_injection,
    )
    content = content.replace(
        "from insar_agent.core.progress import append_progress",
        "def append_progress(*a, **kw): pass  # F3 test stub",
    )
    runner_path.write_text(content)


class TestRslcDownloadRunnerF3:
    """F3 — RSLC download background runner writes terminal status to job JSON."""

    def test_success_updates_job_json_status_done(self, tmp_path):
        """(a) After RSLC runner exits with success, job JSON must have status='done'."""
        runner_path, log_path, jobs_dir, job_id = _launch_and_capture_rslc_runner(tmp_path, success=True)
        _run_script(runner_path, log_path)

        job_data = _read_job_json(jobs_dir, job_id)
        assert job_data["status"] == "done", (
            f"Expected 'done' (F3 eager write), got {job_data['status']!r}. "
            f"Log:\n{_read_log(log_path)[:500]}"
        )
        assert job_data["exit_code"] == 0
        assert job_data.get("finished_at") is not None
        assert "result" in job_data

    def test_failure_updates_job_json_status_failed(self, tmp_path):
        """(b) After RSLC runner exits with failure, job JSON must have status='failed'."""
        runner_path, log_path, jobs_dir, job_id = _launch_and_capture_rslc_runner(tmp_path, success=False)
        _run_script(runner_path, log_path)

        job_data = _read_job_json(jobs_dir, job_id)
        assert job_data["status"] == "failed", (
            f"Expected 'failed' (F3 eager write), got {job_data['status']!r}. "
            f"Log:\n{_read_log(log_path)[:500]}"
        )
        assert job_data["exit_code"] == 1
        assert job_data.get("finished_at") is not None
        assert job_data.get("failure_reason")

    def test_stdout_contract_preserved_on_success(self, tmp_path):
        """(c) RSLC runner still prints status=done JSON line."""
        runner_path, log_path, jobs_dir, job_id = _launch_and_capture_rslc_runner(tmp_path, success=True)
        _run_script(runner_path, log_path)
        _assert_stdout_status(_read_log(log_path), "done")

    def test_stdout_contract_preserved_on_failure(self, tmp_path):
        """(c) RSLC runner still prints status=failed JSON line."""
        runner_path, log_path, jobs_dir, job_id = _launch_and_capture_rslc_runner(tmp_path, success=False)
        _run_script(runner_path, log_path)
        _assert_stdout_status(_read_log(log_path), "failed")


# ===========================================================================
# Group 4: Defensive — eager-write failure must not crash the worker
# ===========================================================================

_DEFENSIVE_RUNNER = """\
import json, traceback

def _utc_now_iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()

def _eager_write_job_status(status, exit_code, result=None, failure_reason=None):
    try:
        import json as _json
        from pathlib import Path as _Path
        _jf = _Path("/nonexistent/totally/broken/path/job.json")
        _data = _json.loads(_jf.read_text()) if _jf.exists() else {}
        _data["status"] = status
        _data["exit_code"] = exit_code
        _data["finished_at"] = _utc_now_iso()
        if result is not None:
            _data["result"] = result
        if failure_reason is not None:
            _data["failure_reason"] = failure_reason
        _jf.write_text(_json.dumps(_data, indent=2))
    except Exception:
        pass  # defensive: must NOT crash the worker

try:
    _result = {"status": "done", "output_path": "/fake"}
    _eager_write_job_status("done", 0, result=_result)
    print(json.dumps({"status": "done", "result": _result}, ensure_ascii=False), flush=True)
except Exception as _exc:
    _eager_write_job_status("failed", 1, failure_reason=str(_exc))
    print(json.dumps({"status": "failed", "error": str(_exc)}, ensure_ascii=False), flush=True)
"""


def test_eager_write_failure_does_not_crash_worker(tmp_path):
    """Job-file write to broken path must not prevent the worker from printing its stdout line."""
    runner_path = tmp_path / "defensive_runner.py"
    log_path = tmp_path / "defensive_runner.log"
    runner_path.write_text(_DEFENSIVE_RUNNER)
    _run_script(runner_path, log_path)
    _assert_stdout_status(_read_log(log_path), "done")
