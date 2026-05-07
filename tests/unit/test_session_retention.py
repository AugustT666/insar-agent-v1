import json

from insar_agent.tools.session_retention import (
    build_retention_records,
    deduplicate_records,
    discover_session_dirs,
    extract_json_objects,
    extract_session_ids_from_log,
    load_manifest,
    parse_job_json,
    write_manifest,
)


def test_extract_session_ids_from_log_deduplicates_in_order(tmp_path):
    log = tmp_path / "session.log"
    log.write_text(
        "INFO id=ses_abc123 created\nINFO id=ses_def456 next\nINFO id=ses_abc123 repeat\n",
        encoding="utf-8",
    )

    assert extract_session_ids_from_log(log) == ["ses_abc123", "ses_def456"]


def test_extract_session_ids_from_log_returns_empty_for_missing_file(tmp_path):
    assert extract_session_ids_from_log(tmp_path / "missing.log") == []


def test_extract_json_objects_reads_pretty_printed_monitor_objects():
    text = """
=== 2026-05-06 ===
{
  "job_id": "stack-1",
  "status": "done"
}
noise
{"job_id": "mintpy-1", "status": "completed"}
"""

    assert extract_json_objects(text) == [
        {"job_id": "stack-1", "status": "done"},
        {"job_id": "mintpy-1", "status": "completed"},
    ]


def test_parse_job_json_filters_known_fields(tmp_path):
    job = tmp_path / "job.json"
    job.write_text(
        json.dumps(
            {
                "job_id": "job-1",
                "project_id": "project-1",
                "status": "done",
                "log_path": "/tmp/job.log",
                "extra": "ignored",
            }
        ),
        encoding="utf-8",
    )

    assert parse_job_json(job) == {
        "job_id": "job-1",
        "project_id": "project-1",
        "status": "done",
        "log_path": "/tmp/job.log",
    }


def test_parse_job_json_returns_empty_for_malformed_json(tmp_path):
    job = tmp_path / "job.json"
    job.write_text("{", encoding="utf-8")

    assert parse_job_json(job) == {}


def test_discover_session_dirs_finds_exp_directories(tmp_path):
    sessions = tmp_path / "sessions"
    (sessions / "exp-1").mkdir(parents=True)
    (sessions / "exp-4-prev-20260506").mkdir()
    (sessions / "not-exp").mkdir()
    (sessions / "file").write_text("x", encoding="utf-8")

    assert [p.name for p in discover_session_dirs(sessions)] == [
        "exp-1",
        "exp-4-prev-20260506",
    ]


def test_build_retention_records_combines_session_logs_monitor_and_jobs(tmp_path):
    session_dir = tmp_path / "sessions" / "exp-4"
    job_dir = session_dir / "workspace" / "outputs" / "sentinel-stack" / ".insar_agent" / "jobs"
    job_dir.mkdir(parents=True)
    (session_dir / "session.log").write_text("INFO id=ses_exp4abc start\n", encoding="utf-8")
    (session_dir / "monitor.log").write_text(
        '{"job_id": "monitor-job", "status": "running"}\n', encoding="utf-8"
    )
    (job_dir / "stack.json").write_text(
        json.dumps(
            {
                "job_id": "stack-job",
                "project_id": "project-1",
                "status": "done",
                "log_path": "/logs/stack.log",
            }
        ),
        encoding="utf-8",
    )

    records = build_retention_records(session_dir)

    assert records == [
        {
            "experiment": "exp-4",
            "attempt_name": "exp-4",
            "opencode_session_id": "ses_exp4abc",
            "opencode_db": str(session_dir / "oc-data" / "opencode" / "opencode.db"),
            "session_log": str(session_dir / "session.log"),
            "monitor_log": str(session_dir / "monitor.log"),
            "job_ids": ["stack-job", "monitor-job"],
            "project_ids": ["project-1"],
            "job_statuses": {"stack-job": "done", "monitor-job": "running"},
            "job_log_paths": ["/logs/stack.log"],
            "success": False,
            "notes": "retained from local OpenCode session artifacts",
        }
    ]


def test_build_retention_records_marks_success_when_all_jobs_are_done(tmp_path):
    session_dir = tmp_path / "sessions" / "exp-1"
    job_dir = session_dir / "workspace" / ".insar_agent" / "jobs"
    job_dir.mkdir(parents=True)
    (session_dir / "session.log").write_text("INFO id=ses_success start\n", encoding="utf-8")
    (job_dir / "job.json").write_text(
        json.dumps({"job_id": "job-1", "status": "completed"}), encoding="utf-8"
    )

    records = build_retention_records(session_dir)

    assert records[0]["success"] is True


def test_deduplicate_records_uses_composite_key_and_incoming_wins():
    existing = [
        {
            "opencode_session_id": "ses_1",
            "job_ids": ["old-job"],
            "success": False,
        }
    ]
    incoming = [
        {
            "opencode_session_id": "ses_1",
            "job_ids": ["new-job"],
            "success": True,
        },
        {
            "opencode_session_id": "ses_2",
            "job_ids": [],
            "success": False,
        },
    ]

    assert deduplicate_records(existing, incoming) == incoming
    assert existing[0]["job_ids"] == ["old-job"]


def test_manifest_round_trip_and_skips_bad_lines(tmp_path):
    manifest = tmp_path / "session-retention.jsonl"
    records = [{"opencode_session_id": "ses_1"}, {"opencode_session_id": "ses_2"}]

    write_manifest(manifest, records)
    with manifest.open("a", encoding="utf-8") as fh:
        fh.write("not-json\n")

    assert load_manifest(manifest) == records
