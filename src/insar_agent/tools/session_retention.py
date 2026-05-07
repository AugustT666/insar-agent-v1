from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

SESSION_ID_RE = re.compile(r"\b(ses_[A-Za-z0-9]+)\b")
DONE_STATUSES = {"completed", "done", "success", "succeeded"}
FAILED_STATUSES = {"failed", "error", "cancelled", "canceled"}
JOB_FIELDS = {
    "job_id",
    "id",
    "project_id",
    "status",
    "state",
    "log_path",
    "started_at",
    "finished_at",
    "created_at",
    "updated_at",
    "exit_code",
    "work_dir",
    "output_dir",
}


def discover_session_dirs(sessions_root: Path) -> list[Path]:
    if not sessions_root.exists():
        return []
    return sorted(
        (
            path
            for path in sessions_root.iterdir()
            if path.is_dir() and path.name.startswith("exp-")
        ),
        key=lambda path: path.name,
    )


def extract_session_ids_from_log(log_path: Path) -> list[str]:
    if not log_path.exists():
        return []
    ids: list[str] = []
    for match in SESSION_ID_RE.finditer(log_path.read_text(encoding="utf-8", errors="ignore")):
        session_id = match.group(1)
        if session_id not in ids:
            ids.append(session_id)
    return ids


def extract_session_ids_from_db(db_path: Path) -> list[str]:
    if not db_path.exists():
        return []
    try:
        with sqlite3.connect(str(db_path)) as conn:
            table_names = [
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            ]
            ids: list[str] = []
            for table in table_names:
                columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]
                if "id" not in columns:
                    continue
                for (value,) in conn.execute(f'SELECT id FROM "{table}"'):
                    if isinstance(value, str) and SESSION_ID_RE.fullmatch(value):
                        if value not in ids:
                            ids.append(value)
            return ids
    except sqlite3.Error:
        return []


def extract_json_objects(text: str) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    start: int | None = None
    depth = 0
    in_string = False
    escaped = False

    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                candidate = text[start : index + 1]
                try:
                    parsed = json.loads(candidate)
                except json.JSONDecodeError:
                    start = None
                    continue
                if isinstance(parsed, dict):
                    objects.append(parsed)
                start = None
    return objects


def parse_job_json(job_path: Path) -> dict[str, Any]:
    try:
        parsed = json.loads(job_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {key: value for key, value in parsed.items() if key in JOB_FIELDS}


def load_manifest(manifest_path: Path) -> list[dict[str, Any]]:
    if not manifest_path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    return records


def write_manifest(manifest_path: Path, records: list[dict[str, Any]]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    content = "\n".join(json.dumps(record, sort_keys=True) for record in records)
    if content:
        content += "\n"
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(manifest_path)


def deduplicate_records(
    existing: list[dict[str, Any]], incoming: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    records_by_key: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for record in [*existing, *incoming]:
        session_id = str(record.get("opencode_session_id", ""))
        if session_id not in records_by_key:
            order.append(session_id)
        records_by_key[session_id] = dict(record)
    return [records_by_key[session_id] for session_id in order]


def build_retention_records(session_dir: Path) -> list[dict[str, Any]]:
    session_log = session_dir / "session.log"
    monitor_log = session_dir / "monitor.log"
    opencode_db = session_dir / "oc-data" / "opencode" / "opencode.db"

    session_ids = extract_session_ids_from_log(session_log)
    for session_id in extract_session_ids_from_db(opencode_db):
        if session_id not in session_ids:
            session_ids.append(session_id)
    if not session_ids:
        session_ids = [""]

    job_objects: list[dict[str, Any]] = []
    for job_path in sorted(session_dir.rglob("*.json")):
        if ".insar_agent/jobs" in str(job_path) or "/.jobs/" in str(job_path):
            parsed = parse_job_json(job_path)
            if parsed:
                job_objects.append(parsed)

    if monitor_log.exists():
        job_objects.extend(
            extract_json_objects(monitor_log.read_text(encoding="utf-8", errors="ignore"))
        )

    job_ids = _unique_strings(
        _job_id(job) for job in job_objects if _job_id(job) is not None
    )
    project_ids = _unique_strings(
        job.get("project_id") for job in job_objects if job.get("project_id")
    )
    job_log_paths = _unique_strings(
        job.get("log_path") for job in job_objects if job.get("log_path")
    )
    job_statuses = {
        job_id: status
        for job in job_objects
        if (job_id := _job_id(job)) is not None
        if (status := _job_status(job)) is not None
    }

    records: list[dict[str, Any]] = []
    for session_id in session_ids:
        record = {
            "experiment": _experiment_name(session_dir.name),
            "attempt_name": session_dir.name,
            "opencode_session_id": session_id,
            "opencode_db": str(opencode_db),
            "session_log": str(session_log),
            "monitor_log": str(monitor_log),
            "job_ids": job_ids,
            "project_ids": project_ids,
            "job_statuses": job_statuses,
            "job_log_paths": job_log_paths,
            "success": _is_success(job_statuses),
            "notes": "retained from local OpenCode session artifacts",
        }
        records.append(record)
    return records


def collect_session_records(sessions_root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for session_dir in discover_session_dirs(sessions_root):
        records.extend(build_retention_records(session_dir))
    return records


def update_manifest(sessions_root: Path, manifest_path: Path) -> list[dict[str, Any]]:
    records = deduplicate_records(load_manifest(manifest_path), collect_session_records(sessions_root))
    write_manifest(manifest_path, records)
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect OpenCode InSAR session IDs")
    parser.add_argument(
        "--sessions-root",
        type=Path,
        default=Path(".opencode-test/sessions"),
        help="Directory containing per-experiment OpenCode sessions",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(".opencode-test/session-retention.jsonl"),
        help="JSONL manifest to update",
    )
    args = parser.parse_args(argv)
    records = update_manifest(args.sessions_root, args.manifest)
    print(f"retained {len(records)} OpenCode session record(s) in {args.manifest}")
    return 0


def _job_id(job: dict[str, Any]) -> str | None:
    value = job.get("job_id") or job.get("id")
    return str(value) if value else None


def _job_status(job: dict[str, Any]) -> str | None:
    value = job.get("status") or job.get("state")
    return str(value) if value else None


def _unique_strings(values: Any) -> list[str]:
    unique: list[str] = []
    for value in values:
        text = str(value)
        if text not in unique:
            unique.append(text)
    return unique


def _is_success(job_statuses: dict[str, str]) -> bool:
    if not job_statuses:
        return False
    statuses = {status.lower() for status in job_statuses.values()}
    return statuses <= DONE_STATUSES and not statuses & FAILED_STATUSES


def _experiment_name(attempt_name: str) -> str:
    match = re.match(r"(exp-\d+)", attempt_name)
    return match.group(1) if match else attempt_name


if __name__ == "__main__":
    raise SystemExit(main())
