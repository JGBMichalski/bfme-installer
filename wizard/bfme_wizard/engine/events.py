"""What a job reports while it runs. The wizard shows each event as it arrives."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


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
class Speed:
    """How fast a download goes."""

    bytes_per_second: int


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
class SetupStatus:
    """Where the setup stands. Every job that changes it ends by reporting it."""

    prefix_ready: bool = False
    programs: frozenset[str] = field(default_factory=frozenset)  # the keys of the installed programs and tools
    games: frozenset[str] = field(default_factory=frozenset)  # the keys of the installed games
    # The game environment is ready and holds at least one program; the tools do not count.
    complete: bool = False
    graphics: str = "vulkan"
    gpu: str = "auto"
    fps_counter: bool = False
    graphics_cards: int = 1  # the window offers the choice of card only on a computer that has more than one


Event = Log | Step | Progress | Speed | Check | Fix | Warn | Error | Cancelled | Done | SetupStatus
Emit = Callable[[Event], None]


def report_speed(emit: Emit) -> Callable[[int], None]:
    """A download's on_speed that reports each measurement as a Speed event."""

    def on_speed(bytes_per_second: int) -> None:
        emit(Speed(bytes_per_second))

    return on_speed
