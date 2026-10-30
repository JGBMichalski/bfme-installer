"""Entry point: `python3 -m bfme_wizard` (the Flatpak runs this as `bfme-installer`).

  bfme-installer                       the wizard
  bfme-installer --open aio-launcher   the "BFME All-in-One Launcher" shortcut
  bfme-installer --open arena          the "BFME Online Arena" shortcut
  bfme-installer --open aotr           the "Age of the Ring" shortcut

A shortcut starts its program without a window. If the program is gone, the wizard opens and removes the shortcut.
"""
from __future__ import annotations

import os
import sys
import threading

from .engine import jobs
from .engine.events import Error, Event, Log

# What a shortcut passes to --open, and the program it means. Shortcuts made before the AIO Launcher was called
# "aio-launcher" pass "launcher".
OPENABLE = {"aio-launcher": "aio-launcher", "launcher": "aio-launcher", "arena": "arena", "aotr": "aotr"}


def has_display() -> bool:
    """Return True if a display is available, False otherwise."""
    return bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"))


def parse_args(argv: list[str]) -> str | None:
    """The program named by --open, or None. GTK has its own options, so others are ignored."""
    for i, arg in enumerate(argv):
        if arg == "--open" and i + 1 < len(argv) and argv[i + 1] in OPENABLE:
            return OPENABLE[argv[i + 1]]
    return None


def print_event(event: Event) -> None:
    """What a program started from a shortcut reports, for whoever reads the output."""
    if isinstance(event, Log):
        print(event.text, flush=True)

    if isinstance(event, Error):
        print(f"ERROR: {event.message}", file=sys.stderr, flush=True)


def main() -> int:
    offer = parse_args(sys.argv[1:])

    # A shortcut whose program is there starts it without a window.
    if offer and jobs.ready_to_open(offer):
        return jobs.open_program(offer, print_event, threading.Event())

    if not has_display():
        print("No display found, so the setup wizard cannot open.", file=sys.stderr)
        return 1

    from .runner import JobRunner
    from .ui import WizardApp  # late, so a shortcut that opens a program needs no GTK

    return WizardApp(JobRunner(), offer=offer).run(sys.argv[:1])


if __name__ == "__main__":
    sys.exit(main())
