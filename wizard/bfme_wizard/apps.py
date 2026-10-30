"""Start programs and watch whether they still run. No GTK.

A program that ends within seconds is the only sign that it failed to start, since Wine reports no error. It is reported
softly, since a player may close it that fast on purpose.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib  # noqa: E402

QUICK_EXIT_SECONDS = 15
APPS = ("aio-launcher", "arena", "aotr")
TOOL_APPS = ("workshop", "mission-control")

# engine.jobs.open_program: (program, emit, cancel) -> exit status. It returns when the program ends.
OpenProgram = Callable[..., int]


class AppLauncher:
    """state per app: idle | running | quick (ended within QUICK_EXIT_SECONDS)"""

    def __init__(self, open_program: OpenProgram, on_change: Callable[[], None], quick_seconds: float = QUICK_EXIT_SECONDS,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.open_program = open_program
        self.on_change = on_change
        self.quick_seconds = quick_seconds
        self._clock = clock
        self.state = {name: "idle" for name in (*APPS, *TOOL_APPS)}

    @property
    def any_running(self) -> bool:
        """Return True if any app is currently running, False otherwise."""
        return any(v == "running" for v in self.state.values())

    def start(self, name: str) -> None:
        """Start the app with the given name, if it is not already running."""

        def ended(code: int) -> bool:
            """Handle the end of the app's execution."""
            quick = code != 0 or self._clock() - started < self.quick_seconds
            self.state[name] = "quick" if quick else "idle"
            self.on_change()
            return False   # an idle callback that returns True would run again

        def work() -> None:
            """Run the app and report its exit code."""
            try:
                code = self.open_program(name, lambda _event: None, threading.Event())
            except Exception:
                code = 1

            GLib.idle_add(ended, code)

        if name not in self.state or self.state[name] == "running":
            return

        started = self._clock()
        self.state[name] = "running"
        self.on_change()

        threading.Thread(target=work, daemon=True).start()
