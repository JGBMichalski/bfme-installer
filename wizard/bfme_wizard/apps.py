"""Starting the Launcher and the Arena, and knowing whether they are still running. No GTK.

A program the wizard starts keeps running after the wizard closes, so this only watches it for the window's sake:
a button shows "running" until the program ends. The script returns 0 whether or not the program worked, so the only
sign of trouble is a program that ends within seconds. That is reported softly ("closed after a few seconds"), because
a player may also close it that fast on purpose.
"""
from __future__ import annotations

import time
from collections.abc import Callable

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

QUICK_EXIT_SECONDS = 15
APPS = ("launcher", "arena")


class AppLauncher:
    """state per app: idle | running | quick (it ended within QUICK_EXIT_SECONDS of starting)"""

    def __init__(self, script: str, on_change: Callable[[], None], quick_seconds: float = QUICK_EXIT_SECONDS,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.script = script
        self.on_change = on_change
        self.quick_seconds = quick_seconds
        self._clock = clock
        self.state = {name: "idle" for name in APPS}

    @property
    def any_running(self) -> bool:
        return any(v == "running" for v in self.state.values())

    def start(self, name: str) -> None:
        if name not in APPS or self.state[name] == "running":
            return
        try:
            proc = Gio.Subprocess.new(
                [self.script, name], Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE,
            )
        except GLib.Error:
            self.state[name] = "quick"
            self.on_change()
            return
        started = self._clock()
        self.state[name] = "running"
        self.on_change()

        def ended(source: Gio.Subprocess, result: Gio.AsyncResult) -> None:
            try:
                source.wait_finish(result)
            except GLib.Error:
                pass
            self.state[name] = "quick" if self._clock() - started < self.quick_seconds else "idle"
            self.on_change()

        proc.wait_async(None, ended)
