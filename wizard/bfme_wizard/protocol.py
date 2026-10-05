"""Parse the status lines printed by `bfme-linux-setup.sh --machine` (see docs/status-lines.md).

Pure Python, no GTK. Every status line starts with "@bfme ". Anything else is ordinary text for the log.
"""
from __future__ import annotations

from dataclasses import dataclass

PREFIX = "@bfme "


@dataclass(frozen=True)
class Step:
    id: str
    status: str  # start | done | skip


@dataclass(frozen=True)
class Progress:
    percent: int


@dataclass(frozen=True)
class Check:
    id: str
    level: str  # ok | warn | fail
    message: str


@dataclass(frozen=True)
class Fix:
    check_id: str
    command: str


@dataclass(frozen=True)
class Warn:
    message: str


@dataclass(frozen=True)
class Error:
    step: str | None
    message: str


@dataclass(frozen=True)
class Cancelled:
    pass


@dataclass(frozen=True)
class Done:
    pass


@dataclass(frozen=True)
class Status:
    key: str
    value: str


Event = Step | Progress | Check | Fix | Warn | Error | Cancelled | Done | Status


def parse_line(line: str) -> Event | None:
    """Return the event for a status line, or None for ordinary text or a line we do not understand."""
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
