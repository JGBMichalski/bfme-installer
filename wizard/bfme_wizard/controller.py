"""Connects the model to the script. No GTK: the UI calls these methods and re-renders on `on_change`."""
from __future__ import annotations

from collections.abc import Callable

from .apps import AppLauncher
from .model import SetupModel
from .runner import ScriptRunner


class Controller:
    def __init__(self, runner: ScriptRunner, on_change: Callable[[], None]) -> None:
        self.runner = runner
        self.model = SetupModel()
        self._on_change = on_change
        self.apps = AppLauncher(runner.script, on_change)

    # ---------------------------------------------------------------- actions
    def start(self) -> None:
        """Find out what is already installed."""
        if self.runner.busy:
            return
        self.model.begin_check()
        self.model.installed.clear()   # what the script reports now replaces what was known before (a reset, say)
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

    def open_app(self, name: str) -> None:
        """Start the Launcher or the Arena. The window keeps showing whether it is still running."""
        self.apps.start(name)

    def run_checks(self) -> bool:
        """Run the system checks again without leaving the current screen. False if the script is busy."""
        if self.runner.busy:
            return False
        self.model.begin_quiet_check()
        self._on_change()
        self.runner.run(["doctor"], self._line, self._checks_done)
        return True

    @property
    def checking(self) -> bool:
        return self.runner.busy

    def blocked_reason(self) -> str | None:
        """Why Reset must not run right now, or None. A program started from a menu entry is not tracked, so the
        Reset dialog also asks the player to close it; the script ends the Wine session before deleting anything."""
        if self.model.state == "running":
            return "The setup is running."
        if self.apps.any_running:
            return "The Launcher or the Arena is still running."
        if self.runner.busy:
            return "Something else is still running. Try again in a moment."
        return None

    def reset(self, on_done: Callable[[bool], None]) -> bool:
        """Delete the game environment (every installed game with it), then look at the setup again."""
        if self.blocked_reason() is not None:
            return False

        def finished(code: int) -> None:
            on_done(code == 0)
            self.start()   # show the setup from the beginning (or the error, if the reset failed)

        self.model.begin_check()
        self._on_change()
        self.runner.run(["reset-prefix", "--yes"], self._line, finished)
        return True

    # -------------------------------------------------------------- callbacks
    def _line(self, line: str) -> None:
        self.model.feed_line(line)
        self._on_change()

    def _status_done(self, code: int) -> None:
        self.model.finish_status(code)
        self._on_change()
        if self.model.state == "done":
            self.run_checks()   # quietly: a failed check shows a banner on the home screen

    def _checks_done(self, code: int) -> None:
        self.model.error = None   # the script ends a failing check with an ERROR line; it is not a setup error
        self._on_change()

    def _install_done(self, code: int) -> None:
        self.model.finish_install(code)
        self._on_change()
        if self.model.state == "done":
            # Learn which games exist now, without leaving the screen.
            self.runner.run(["status"], self._line, lambda _code: self._on_change())

    def _recheck_done(self, code: int) -> None:
        self.model.finish_check(code)
        if code == 0:
            self.install()
        else:
            self._on_change()
