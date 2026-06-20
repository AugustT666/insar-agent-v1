"""Layer-1 progress logging: timestamped, one-line-per-entry progress tracking."""
from __future__ import annotations

from datetime import datetime, UTC
from pathlib import Path


def append_progress(
    run_root: str | Path,
    message: str,
    *,
    step: int | None = None,
    total: int | None = None,
) -> None:
    """Append a timestamped progress entry to the progress log.

    Creates the .insar_agent directory if needed.

    Parameters
    ----------
    run_root : str | Path
        Root directory of the run (contains .insar_agent/).
    message : str
        Progress message to log.
    step : int, optional
        Current step number (displays as [step/total] if provided).
    total : int, optional
        Total number of steps (used with step to display progress fraction).
    """
    run_root = Path(run_root)
    agent_state_dir = run_root / ".insar_agent"
    agent_state_dir.mkdir(parents=True, exist_ok=True)

    progress_path = agent_state_dir / "progress.log"

    # Build the progress entry line
    timestamp = datetime.now(UTC).isoformat()
    if step is not None and total is not None:
        entry = f"{timestamp}\t[{step}/{total}] {message}"
    else:
        entry = f"{timestamp}\t{message}"

    # Append to log file
    with open(progress_path, "a", encoding="utf-8") as f:
        f.write(entry + "\n")


def read_progress_tail(
    run_root: str | Path,
    n: int = 20,
) -> str:
    """Read the last n lines from the progress log.

    Parameters
    ----------
    run_root : str | Path
        Root directory of the run (contains .insar_agent/).
    n : int, optional
        Number of lines to read from the end (default 20).

    Returns
    -------
    str
        The last n lines as a single string (one line per entry, no trailing newline).
        Returns empty string if the log file does not exist.
    """
    run_root = Path(run_root)
    progress_path = run_root / ".insar_agent" / "progress.log"

    if not progress_path.exists():
        return ""

    with open(progress_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # Get the last n lines
    tail_lines = lines[-n:] if len(lines) > n else lines
    # Strip trailing newlines and rejoin
    return "".join(tail_lines).rstrip("\n")
