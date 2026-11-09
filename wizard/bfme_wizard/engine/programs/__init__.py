"""The programs a player can install, open and remove, one object each. The setup's jobs, the shortcuts and the window all
get what they say and do about a program from here."""

from __future__ import annotations

from ..errors import SetupError
from .aio_launcher import AioLauncher
from .aotr import AgeOfTheRing
from .arena import Arena
from .base import Program, Shortcut
from .tools import MissionControl, Tool, WorkshopStudio

AIO_LAUNCHER = AioLauncher()
ARENA = Arena()
AOTR = AgeOfTheRing()

# The programs of the setup, in install order. The home screen has a card for each.
PROGRAMS: tuple[Program, ...] = (AIO_LAUNCHER, ARENA, AOTR)
# Extra programs, listed on the Tools part of the Programs page. They are not part of the setup.
TOOLS: tuple[Tool, ...] = (WorkshopStudio(), MissionControl())
EVERY_PROGRAM: tuple[Program, ...] = (*PROGRAMS, *TOOLS)


def program(key: str) -> Program:
    """The program with this key."""
    for each in EVERY_PROGRAM:
        if each.key == key:
            return each

    raise SetupError(f"Unknown program: {key}.")


__all__ = [
    "AIO_LAUNCHER",
    "AOTR",
    "ARENA",
    "EVERY_PROGRAM",
    "PROGRAMS",
    "TOOLS",
    "AgeOfTheRing",
    "AioLauncher",
    "Arena",
    "MissionControl",
    "Program",
    "Shortcut",
    "Tool",
    "WorkshopStudio",
    "program",
]
