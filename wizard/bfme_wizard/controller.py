"""Connects the model to the setup's jobs. No GTK: the UI calls these methods and re-renders on `on_change`."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from functools import partial

from .apps import AppLauncher
from .engine.events import Event
from .engine.jobs import Engine, PrepareJob
from .engine.programs import program
from .model import ALL_PROGRAMS, TOOLS, SetupModel
from .runner import JobRunner


class Controller:
    def __init__(
        self,
        runner: JobRunner,
        on_change: Callable[[], None],
        offer: str | None = None,
        jobs: Engine | None = None,
    ) -> None:
        self.runner = runner
        self.jobs = jobs or Engine()  # the tests give a stand-in
        self.model = SetupModel()
        self._on_change = on_change
        self.apps = AppLauncher(self.jobs.open_program, on_change)
        self._offer = offer  # what the shortcut that opened the wizard wanted, used once (see start)

    def start(self) -> None:
        """Check what is installed. The old plan is dropped, the choice stays."""
        if self.runner.busy:
            return
        self.model.begin_check()
        self.model.status = None  # what the status job reports now replaces what was known before (a reset, say)
        self._on_change()
        self.runner.run(self.jobs.status, self._event, self._status_done)

    def install(self, programs: Iterable[str]) -> None:
        """Install the choice. After a stop, the same choice resumes and a different one starts over."""
        if self.runner.busy:
            return
        if self.model.resumes(programs):
            self.resume()
            return
        if not self.model.begin_plan(programs):
            return
        self._run_job(self.model.first_unfinished_job())

    def resume(self) -> None:
        """Continue the plan after Cancel or a fixed system check."""
        if self.runner.busy:
            return
        self._run_job(self.model.first_unfinished_job())

    def retry(self) -> None:
        """Run the failed job again."""
        if self.runner.busy:
            return
        self._run_job(self.model.job)

    def back_home(self) -> None:
        """Leave the plan: home screen, or start page when nothing is installed."""
        self.start()

    def recheck(self) -> None:
        """Recheck after a fix. Continues the plan if the checks pass."""
        if self.runner.busy:
            return
        self.model.begin_check()
        self._on_change()
        self.runner.run(self.jobs.check, self._event, self._recheck_done)

    def cancel(self) -> None:
        self.model.request_cancel()
        self.runner.request_cancel()
        self._on_change()

    def stop_now(self) -> None:
        self.runner.terminate()

    def open_app(self, name: str) -> None:
        """Start a program."""
        self.apps.start(name)

    def run_checks(self) -> bool:
        """Rerun system checks in place. False while another job runs."""
        if self.runner.busy:
            return False
        self.model.begin_quiet_check()
        self._on_change()
        self.runner.run(self.jobs.check, self._event, self._checks_done)
        return True

    @property
    def checking(self) -> bool:
        """Return True if system checks are currently running, False otherwise."""
        return self.runner.busy

    def blocked_reason(self) -> str | None:
        """Why Reset or Remove cannot run now, or None. Shortcut-started programs are not tracked, so their dialogs ask to close them."""
        if self.model.state == "running":
            return "The setup is running."
        if self.model.state == "removing":
            return "A program is being removed."
        if self.apps.any_running:
            return "A program is still running."
        if self.runner.busy:
            return "Something else is still running. Try again in a moment."
        return None

    def reset(self, on_done: Callable[[bool], None]) -> bool:
        """Delete the game environment, then check the setup again. False if it cannot start now."""
        if self.blocked_reason() is not None:
            return False

        def finished(code: int) -> None:
            on_done(code == 0)
            self.start()  # show the setup from the beginning (or the error, if the reset failed)

        self.model.begin_check()
        self._on_change()
        self.runner.run(self.jobs.reset, self._event, finished)
        return True

    def set_graphics(self, backend: str, on_done: Callable[[bool], None] | None = None) -> bool:
        """Switch between the Vulkan and OpenGL backends, then look at the setup again. False if it cannot start now."""
        if backend not in ("vulkan", "opengl") or self.runner.busy or self.blocked_reason() is not None:
            return False

        def finished(code: int) -> None:
            if on_done is not None:
                on_done(code == 0)
            self.start()  # the saved backend, and the checks that may depend on it

        self.runner.run(partial(self.jobs.switch_graphics, backend), self._event, finished)
        return True

    def set_option(self, option: str, value: str | int, on_done: Callable[[bool], None] | None = None) -> bool:
        """Save the graphics card or the FPS counter, then look at the setup again.
        False if it cannot start now."""
        if self.runner.busy or self.blocked_reason() is not None:
            return False

        def finished(code: int) -> None:
            if on_done is not None:
                on_done(code == 0)
            self.start()  # the saved settings

        self.runner.run(partial(self.jobs.change_option, option, value), self._event, finished)
        return True

    def remove(self, program: str, on_done: Callable[[bool], None]) -> bool:
        """Remove a program (its files and its shortcut), then check the setup again. False if it cannot start now."""
        if program not in (*ALL_PROGRAMS, *TOOLS) or self.blocked_reason() is not None:
            return False

        def finished(code: int) -> None:
            on_done(code == 0)
            self.start()  # the home screen without it, or the start page when it was the last one

        self.model.begin_remove(program)
        self._on_change()
        self.runner.run(partial(self.jobs.remove, program), self._event, finished)
        return True

    def _run_job(self, name: str | None) -> None:
        """Run a job, or wait for the player when the file is not chosen yet."""
        if name is None:
            self.start()
            return
        self.model.begin_job(name)
        self._on_change()
        if name == PrepareJob.KEY:
            job = self.jobs.prepare
        else:
            job = partial(self.jobs.install, name)
        self.runner.run(job, self._event, self._job_done)

    def _event(self, event: Event) -> None:
        """Handle an event from a running job."""
        self.model.feed_event(event)
        self._on_change()

    def _status_done(self, code: int) -> None:
        """Handle the completion of the status job."""
        self.model.finish_status(code)
        done = self.model.state == "done"
        # The shortcut of a program that is gone: install it again, by the job that installs it (the Arena comes with
        # the AIO Launcher). A shortcut is answered once, not every time the player comes back to the home screen.
        missing = None
        if code == 0 and self._offer and not self.model.is_installed(self._offer):
            missing = program(self._offer).job
        self._offer = None
        self._sync_shortcuts(lambda: self._after_status(done, missing))

    def _after_status(self, done: bool, missing: str | None) -> None:
        """Handle the state after the status job has completed."""
        if missing is not None:
            self.install([missing])
            return
        self._on_change()
        if done:
            self.run_checks()  # quietly: a failed check shows a banner on the home screen

    def _sync_shortcuts(self, then: Callable[[], None]) -> None:
        """Sync shortcuts with what is installed, then continue. Call `then` when done."""
        self.runner.run(self.jobs.sync_shortcuts, lambda _event: None, lambda _code: then())

    def _checks_done(self, code: int) -> None:
        """Handle the completion of the checks job."""
        self.model.error = None  # a failing check job ends with an error; it is not a setup error
        self._on_change()

    def _job_done(self, code: int) -> None:
        """Handle the completion of an installation job."""
        # Every job ends with STATUS lines, so no second status question is needed.
        following = self.model.finish_install(code)
        self._on_change()
        if following is not None:
            self._run_job(following)

    def _recheck_done(self, code: int) -> None:
        """Handle the completion of a recheck job."""
        self.model.finish_check(code)
        if code == 0:
            self.resume()
        else:
            self._on_change()
