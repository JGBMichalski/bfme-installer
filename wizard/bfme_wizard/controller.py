"""Connects the model to the setup's jobs. No GTK: the UI calls these methods and re-renders on `on_change`."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from functools import partial
from types import ModuleType

from .apps import AppLauncher
from .engine import jobs as engine_jobs
from .engine.events import Event
from .model import ALL_PROGRAMS, TOOLS, SetupModel
from .runner import JobRunner

# Shortcut target to the program that provides it.
PROGRAM_OF = {
    "aio-launcher": "aio-launcher",
    "arena": "aio-launcher",
    "aotr": "aotr",
    **{tool: tool for tool in TOOLS},
}


class Controller:
    def __init__(self, runner: JobRunner, on_change: Callable[[], None], offer: str | None = None,
                 jobs: ModuleType | object = engine_jobs) -> None:
        self.runner = runner
        self.jobs = jobs   # engine/jobs.py; the tests give a stand-in
        self.model = SetupModel()
        self._on_change = on_change
        self.apps = AppLauncher(jobs.open_program, on_change)
        self._aotr_zip: str | None = None   # the file the player chose for Age of the Ring, kept for Retry and Resume
        self._offer = offer                 # what the shortcut that opened the wizard wanted, used once (see start)

    def start(self) -> None:
        """Check what is installed. The old plan is dropped, the choice stays."""
        if self.runner.busy:
            return
        self._aotr_zip = None
        self.model.begin_check()
        self.model.installed.clear()   # what the status job reports now replaces what was known before (a reset, say)
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
        self._aotr_zip = None   # a new choice asks for the file again
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

    def choose_aotr_file(self, zip_path: str) -> None:
        """Install the Age of the Ring file the player chose."""
        if self.runner.busy:
            return
        self._aotr_zip = zip_path
        self._run_job("aotr")

    def choose_another_aotr_file(self) -> None:
        """Ask the player for the Age of the Ring file, instead of the app downloading it."""
        if self.runner.busy:
            return
        self._aotr_zip = None
        self.model.wait_for_file()
        self._on_change()

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
            self.start()   # show the setup from the beginning (or the error, if the reset failed)

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
            self.start()   # the saved backend, and the checks that may depend on it

        self.runner.run(partial(self.jobs.switch_graphics, backend), self._event, finished)
        return True

    def remove(self, program: str, on_done: Callable[[bool], None]) -> bool:
        """Remove a program (its files and its shortcut), then check the setup again. False if it cannot start now."""
        if program not in (*ALL_PROGRAMS, *TOOLS) or self.blocked_reason() is not None:
            return False

        def finished(code: int) -> None:
            on_done(code == 0)
            self.start()   # the home screen without it, or the start page when it was the last one

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
        if name in TOOLS:
            job = partial(self.jobs.tool_install, name)
        elif name == "aotr":
            job = partial(self.jobs.aotr_install, self._aotr_zip)
        elif name == "aio-launcher":
            job = self.jobs.aio_launcher_install
        else:
            job = self.jobs.prepare
        self.runner.run(job, self._event, self._job_done)

    def _event(self, event: Event) -> None:
        """Handle an event from a running job."""
        self.model.feed_event(event)
        self._on_change()

    def _status_done(self, code: int) -> None:
        """Handle the completion of the status job."""
        self.model.finish_status(code)
        offered = PROGRAM_OF.get(self._offer or "")
        self._offer = None   # a shortcut is answered once, not every time the player comes back to the home screen
        done = self.model.state == "done"
        wants_aotr = done and offered == "aotr" and not self.model.aotr_installed
        if offered and not done:
            self.model.choose([offered])
        self._sync_shortcuts(lambda: self._after_status(done, wants_aotr))

    def _after_status(self, done: bool, wants_aotr: bool) -> None:
        """Handle the state after the status job has completed."""
        if wants_aotr:
            self.install(["aotr"])   # the shortcut of a mod that is not installed: go and install it
            return
        self._on_change()
        if done:
            self.run_checks()        # quietly: a failed check shows a banner on the home screen

    def _sync_shortcuts(self, then: Callable[[], None]) -> None:
        """Sync shortcuts with what is installed, then continue. Call `then` when done."""
        self.runner.run(self.jobs.sync_shortcuts, lambda _event: None, lambda _code: then())

    def _checks_done(self, code: int) -> None:
        """Handle the completion of the checks job."""
        self.model.error = None   # a failing check job ends with an error; it is not a setup error
        self._on_change()

    def _job_done(self, code: int) -> None:
        """Handle the completion of an installation job."""
        # The app could not download Age of the Ring itself: the player downloads it and chooses the file.
        if code == self.jobs.NEEDS_FILE and self.model.job == "aotr":
            why = self.model.error.message if self.model.error else None
            self.model.wait_for_file(why)
            self._on_change()
            return

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
