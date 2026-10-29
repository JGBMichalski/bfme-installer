"""Parse the status lines printed by `bfme-linux-setup.sh --machine` (see docs/status-lines.md).

No GTK. Status lines start with "@bfme "; anything else is plain log text.
"""
from __future__ import annotations

from .engine.events import Cancelled, Check, Done, Error, Event, Fix, Progress, Status, Step, Warn  # noqa: F401

PREFIX = "@bfme "


def parse_line(line: str) -> Event | None:
    """The event for a status line; None for plain text or unknown lines."""
    if not line.startswith(PREFIX):
        return None
    parts = line[len(PREFIX):].rstrip("\r\n").split(" ", 1)
    kind, rest = parts[0], (parts[1] if len(parts) > 1 else "")
    try:
        if kind == "STEP":
            step_id, status = rest.split(" ")
            return Step(step_id, status) if status in ("start", "done", "skip") else None
        if kind == "PROGRESS":
            return Progress(max(0, min(100, int(rest))))
        if kind == "CHECK":
            check_id, level, message = rest.split(" ", 2)
            return Check(check_id, level, message) if level in ("ok", "warn", "fail") else None
        if kind == "FIX":
            check_id, command = rest.split(" ", 1)
            return Fix(check_id, command)
        if kind == "WARN":
            return Warn(rest)
        if kind == "ERROR":
            step, message = rest.split(" ", 1)
            return Error(None if step == "-" else step, message)
        if kind == "CANCELLED":
            return Cancelled()
        if kind == "DONE":
            return Done()
        if kind == "STATUS":
            key, value = rest.split(" ", 1)
            return Status(key, value)
    except ValueError:
        return None
    return None
