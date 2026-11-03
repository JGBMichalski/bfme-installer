"""A stand-in for engine/jobs.py's Engine, for the tests of the controller and the window.

What is installed lives in flag files in `dir`; every job that runs is added to `calls`. Flags:
  prefix, aio-launcher, arena, aotr, workshop, mission-control, bfme2   what is installed
  checks-pass             the system check passes (without it `prepare` stops at its check)
  broken                  the system check also finds the 32-bit extensions missing
  flaky                   `prepare` fails once, in the runner step
  aio-launcher-flaky      `install aio-launcher` fails once, in the aio-launcher step
  cancel-once             `install aio-launcher` is stopped once, before the arena step
  aotr-bad                `install aotr` fails once, in the check
  moddb-down              `install aotr` without a file cannot download it: the player must choose it
  shortcuts-fails         `sync_shortcuts` fails (the permission is gone, say)
  remove-fails            `remove` fails and deletes nothing
  reset-fails             `reset` fails and deletes nothing
  two-cards               the computer has two graphics cards
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from bfme_wizard.controller import Controller
from bfme_wizard.engine.events import (
    Cancelled,
    Check,
    Done,
    Error,
    Fix,
    Log,
    Progress,
    Step,
)
from tests.helpers import status

PROGRAMS = ("aio-launcher", "arena", "aotr")


class FakeJobs:
    def __init__(self, dir):
        self.dir = Path(dir)
        self.calls: list[str] = []
        self.app_seconds = 0.0  # how long a program opened by open_program runs

    # The flags

    def flag(self, *names):
        for name in names:
            (self.dir / name).touch()

    def unflag(self, *names):
        for name in names:
            (self.dir / name).unlink(missing_ok=True)

    def has(self, name):
        return (self.dir / name).exists()

    def once(self, name):
        """True the first time it is asked while the flag is there."""
        if self.has(name) and not self.has(name + "-used"):
            self.flag(name + "-used")
            return True

        return False

    # What every job ends with

    def report(self, emit):
        installed = []

        for key in (*PROGRAMS, "workshop", "mission-control", "bfme2"):
            if self.has(key):
                installed.append(key)

        emit(
            status(
                *installed,
                prefix_ready=self.has("prefix"),
                graphics=self.saved("graphics", "vulkan"),
                gpu=self.saved("option-gpu", "auto"),
                fps_counter=self.saved("option-fps-counter", "0") == "1",
                graphics_cards=2 if self.has("two-cards") else 1,
            )
        )

    def saved(self, name, default):
        """What a job saved in the file `name`, or `default`."""
        if self.has(name):
            return (self.dir / name).read_text()

        return default

    def fail(self, emit, step, message, code=1):
        emit(Log(f"ERROR: {message}"))
        emit(Error(step, message))
        return code

    # The jobs

    def status(self, emit, cancel=None):
        self.calls.append("status")
        self.report(emit)
        return 0

    def check(self, emit, cancel=None):
        self.calls.append("check")
        return self._checks(emit)

    def _checks(self, emit):
        emit(Check("cpu", "ok", "x86_64 processor"))

        if self.has("broken"):
            emit(Check("flatpak-32bit", "fail", "the 32-bit Flatpak extensions are not installed"))
            emit(Fix("flatpak-32bit", "flatpak install X"))
            return 1

        if not self.has("checks-pass"):
            emit(Check("disk", "fail", "not enough room"))
            emit(Fix("disk", "free some space"))
            return 1

        emit(Check("disk", "ok", "free disk space: 100 GB"))
        return 0

    def sync_shortcuts(self, emit, cancel=None):
        self.calls.append("sync_shortcuts")
        emit(Log("Shortcuts are up to date in /fake"))

        if self.has("shortcuts-fails"):
            return self.fail(emit, None, "The shortcuts could not be updated.")

        return 0

    def prepare(self, emit, cancel=None):
        self.calls.append("prepare")
        emit(Step("doctor", "start"))

        if self._checks(emit) != 0:
            return self.fail(
                emit, "doctor", "Your system needs a change first. Fix the problems above, then try again."
            )

        emit(Step("doctor", "done"))
        emit(Step("runner", "start"))

        if self.once("flaky"):
            return self.fail(emit, "runner", "Failed (exit 22).", 22)

        emit(Progress(50))
        emit(Step("runner", "done"))
        emit(Step("prefix", "start"))
        emit(Step("prefix", "done"))
        self.flag("prefix")
        self.report(emit)
        emit(Done())
        return 0

    def install(self, key, zip_path, emit, cancel=None):
        if key == "aotr":
            return self._aotr_install(zip_path, emit)

        if key != "aio-launcher":
            return self._tool_install(key, emit)

        self.calls.append("install aio-launcher")
        emit(Step("aio-launcher", "start"))

        if self.once("aio-launcher-flaky"):
            return self.fail(emit, "aio-launcher", "Failed (exit 22).", 22)

        emit(Step("aio-launcher", "done"))
        emit(Step("arena", "start"))

        if self.once("cancel-once"):
            emit(Cancelled())
            return 130

        emit(Step("arena", "done"))
        emit(Step("shortcuts", "skip"))
        self.flag("aio-launcher", "arena")
        self.report(emit)
        emit(Done())
        return 0

    NEEDS_FILE = 2

    def _aotr_install(self, zip_path, emit):
        self.calls.append(f"install aotr {zip_path}")

        if zip_path is None:
            emit(Step("aotr-download", "start"))

            if self.has("moddb-down"):
                return self.fail(emit, "aotr-download", "ModDB did not offer a download link.", self.NEEDS_FILE)

            emit(Progress(30))
            emit(Step("aotr-download", "done"))
        else:
            emit(Step("aotr-download", "done"))

        emit(Step("aotr-check", "start"))

        if self.once("aotr-bad"):
            return self.fail(emit, "aotr-check", "This file is incomplete.")

        emit(Step("aotr-check", "done"))
        emit(Progress(40))
        emit(Step("aotr-install", "start"))
        emit(Step("aotr-install", "done"))
        self.flag("aotr")
        self.report(emit)
        emit(Done())
        return 0

    def _tool_install(self, tool, emit):
        self.calls.append(f"install {tool}")
        emit(Step(tool, "start"))
        emit(Step(tool, "done"))
        self.flag(tool)
        self.report(emit)
        emit(Done())
        return 0

    def change_option(self, option, value, emit, cancel=None):
        self.calls.append(f"change_option {option} {value}")
        (self.dir / f"option-{option}").write_text(str(value))
        self.report(emit)
        emit(Done())
        return 0

    def remove(self, program, emit, cancel=None):
        self.calls.append(f"remove {program}")

        if self.has("remove-fails"):
            return self.fail(emit, None, "Could not remove it")

        self.unflag(program)
        self.report(emit)
        emit(Done())
        return 0

    def switch_graphics(self, backend, emit, cancel=None):
        self.calls.append(f"switch_graphics {backend}")

        if backend not in ("vulkan", "opengl"):
            return self.fail(emit, None, "Unknown graphics backend: direct3d.")

        (self.dir / "graphics").write_text(backend)
        self.report(emit)
        emit(Done())
        return 0

    def reset(self, emit, cancel=None):
        self.calls.append("reset")

        if self.has("reset-fails"):
            return self.fail(emit, None, "nope")

        time.sleep(0.3)
        self.unflag("prefix", "bfme2", *PROGRAMS)
        emit(Log("Prefix deleted."))
        return 0

    def open_program(self, program, emit, cancel=None):
        self.calls.append(f"open_program {program}")

        if program == "bad-exit":
            return 3

        time.sleep(self.app_seconds)
        return 0


def idle_controller(on_change=lambda: None):
    """A controller for a page that only needs one: nothing is installed and nothing runs until asked."""
    from bfme_wizard.runner import JobRunner

    return Controller(JobRunner(), on_change, jobs=FakeJobs(tempfile.mkdtemp()))
