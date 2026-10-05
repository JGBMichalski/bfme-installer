"""Connects the model to the script. No GTK: the UI calls these methods and re-renders on `on_change`."""
from __future__ import annotations

from collections.abc import Callable

from .model import SetupModel
from .runner import ScriptRunner


class Controller:
    def __init__(self, runner: ScriptRunner, on_change: Callable[[], None]) -> None:
        self.runner = runner
        self.model = SetupModel()
        self._on_change = on_change

    # ---------------------------------------------------------------- actions
    def start(self) -> None:
        """Find out what is already installed."""
        if self.runner.busy:
            return
        self.model.begin_check()
        self._on_change()
        self.runner.run(["status"], self._line, self._status_done)

    def install(self) -> None:
        """Run (or resume) the install. Safe to call again after a failure or a cancel."""
        if self.runner.busy:
            return
        self.model.begin_install()
        self._on_change()
        self.runner.run(["install"], self._line, self._install_done)

    retry = install

    def recheck(self) -> None:
        """Run the system checks again after the user fixed something. Continues the install if they now pass."""
        if self.runner.busy:
            return
        self.model.begin_check()
        self._on_change()
        self.runner.run(["doctor"], self._line, self._recheck_done)

    def cancel(self) -> None:
        self.model.request_cancel()
        self.runner.request_cancel()
        self._on_change()

    def stop_now(self) -> None:
        self.runner.terminate()

    def open_launcher(self) -> None:
        self.runner.spawn_detached(["launcher"])

    def open_arena(self) -> None:
        self.runner.spawn_detached(["arena"])

    # -------------------------------------------------------------- callbacks
    def _line(self, line: str) -> None:
        self.model.feed_line(line)
        self._on_change()

    def _status_done(self, code: int) -> None:
        self.model.finish_status(code)
        self._on_change()

    def _install_done(self, code: int) -> None:
        self.model.finish_install(code)
        self._on_change()

    def _recheck_done(self, code: int) -> None:
        self.model.finish_check(code)
        if code == 0:
            self.install()
        else:
            self._on_change()
