"""What a job reports while it runs. The wizard shows each event as it arrives."""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable


@dataclass(frozen=True)
class Log:
    """A line for the log the player can copy."""
    text: str


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


Event = Log | Step | Progress | Check | Fix | Warn | Error | Cancelled | Done | Status
Emit = Callable[[Event], None]
