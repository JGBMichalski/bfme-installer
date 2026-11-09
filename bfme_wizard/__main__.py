"""Entry point: `python3 -m bfme_wizard` (the Flatpak runs this as `bfme-installer`).

  bfme-installer                       the wizard
  bfme-installer --open aio-launcher   the "BFME All-in-One Launcher" shortcut
  bfme-installer --open arena          the "BFME Online Arena" shortcut
  bfme-installer --open aotr           the "Age of the Ring" shortcut

A shortcut starts its program without a window. If the program is gone, the wizard opens and installs it again.
"""

from __future__ import annotations

import os
import sys
import threading

from .engine.events import Error, Event, Log
from .engine.jobs import Engine
from .engine.programs import PROGRAMS


class CommandLine:
    """What the app was started with: the wizard, or `--open <program>` from a menu shortcut."""

    def __init__(self, argv: list[str]) -> None:
        self.argv = argv
        self.jobs = Engine()

    @staticmethod
    def openable() -> dict[str, str]:
        """What a shortcut passes to --open, and the program it means: the key of each program with a shortcut, and its
        older names."""
        names = {}

        for program in PROGRAMS:
            if program.shortcut is None:
                continue

            names[program.key] = program.key

            for alias in program.aliases:
                names[alias] = program.key

        return names

    @property
    def offer(self) -> str | None:
        """The program named by --open, or None. GTK has its own options, so others are ignored."""
        names = self.openable()
        args = self.argv[1:]

        for i, arg in enumerate(args):
            if arg == "--open" and i + 1 < len(args) and args[i + 1] in names:
                return names[args[i + 1]]

        return None

    @staticmethod
    def has_display() -> bool:
        return bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"))

    @staticmethod
    def print_event(event: Event) -> None:
        """What a program started from a shortcut reports, for whoever reads the output."""
        if isinstance(event, Log):
            print(event.text, flush=True)

        if isinstance(event, Error):
            print(f"ERROR: {event.message}", file=sys.stderr, flush=True)

    def run(self) -> int:
        offer = self.offer
        jobs = self.jobs

        # A shortcut whose program is there starts it without a window. The shortcuts are brought in line first, so a
        # player who only uses the menu still gets them renamed or removed. A failed sync is no reason not to open the
        # program.
        if offer and jobs.ready_to_open(offer):
            jobs.sync_shortcuts(self.print_event, threading.Event())
            return jobs.open_program(offer, self.print_event, threading.Event())

        if not self.has_display():
            print("No display found, so the setup wizard cannot open.", file=sys.stderr)
            return 1

        from .control.runner import JobRunner
        from .ui.app import WizardApp  # late, so a shortcut that opens a program needs no GTK

        return WizardApp(JobRunner(), offer=offer).run(self.argv[:1])


def main() -> int:
    return CommandLine(sys.argv).run()


if __name__ == "__main__":
    sys.exit(main())
