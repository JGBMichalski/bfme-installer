"""The jobs the wizard runs. Each wraps the setup's steps with what a whole job needs: the setup lock, the steps it reports,
where things stand when it ends, and its errors.

`Engine` is what the window calls. Every job takes (emit, cancel) and returns an exit status: 0 done, 1 failed, 2 the
player must choose the Age of the Ring file, 130 stopped by the player.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod

from .config import Config, ConfigError, ConfigFile
from .doctor import SystemCheck
from .errors import JobCancelled, SetupError
from .events import Cancelled, Done, Emit, Error, Log, Progress, SetupStatus, Step
from .lock import SetupLock
from .moddb import ModdbUnavailable
from .paths import Paths
from .prefix import GameEnvironment
from .programs import EVERY_PROGRAM, program
from .proton import Proton
from .shortcuts import MenuShortcuts

OK = 0
FAILED = 1
NEEDS_FILE = 2  # the app cannot download Age of the Ring itself: the player downloads it and chooses the file
STOPPED = 130
SET_UP_FIRST = "Set up the game environment first."
# Each game's program, under drive_c. A game counts as installed once it is there.
GAME_EXES = {"bfme1": "BFME1/lotrbfme.exe", "bfme2": "BFME2/lotrbfme2.exe", "rotwk": "RotWK/lotrbfme2ep1.exe"}


class Job(ABC):
    """One run of a job: what it works with, the step it is on (an error names it), and how it ends."""

    def __init__(
        self, emit: Emit, cancel: threading.Event | None = None, environ: dict[str, str] | None = None
    ) -> None:
        self.emit = emit
        self.cancel = cancel or threading.Event()
        self.environ = environ
        self.paths = Paths.of(environ)
        self.environment = GameEnvironment(self.paths)
        self.config = Config()
        self.step: str | None = None

    @abstractmethod
    def body(self) -> None:
        """What the job does. Raises SetupError when it fails."""

    def run(self) -> int:
        """Run the body and turn how it ended into events and an exit status."""
        try:
            self.config = ConfigFile(self.paths.config).load(self.environ)
        except ConfigError as error:
            self.emit(Error(None, str(error)))
            return FAILED

        try:
            self.body()
        except JobCancelled:
            self.emit(Cancelled())
            self.emit(Log("Stopped before the next step."))
            return STOPPED
        except SetupError as error:
            self.emit(Log(f"ERROR: {error}"))
            self.emit(Error(self.step, str(error)))
            return FAILED
        except ModdbUnavailable as error:
            self.emit(Log(f"The app cannot download it itself: {error}"))
            self.emit(Error(self.step, str(error)))
            return NEEDS_FILE

        return OK

    # Steps

    def stop_if_asked(self) -> None:
        """Stop the job if the player asked for it."""
        if self.cancel.is_set():
            raise JobCancelled()

    def start(self, step: str) -> None:
        """Begin a step. A stop the player asked for takes effect here, between steps."""
        self.stop_if_asked()
        self.step = step
        self.emit(Step(step, "start"))

    def done(self, step: str) -> None:
        self.emit(Step(step, "done"))
        self.step = None

    def skip(self, step: str) -> None:
        self.stop_if_asked()
        self.emit(Step(step, "skip"))

    def lock(self):
        """Only one setup changes the game environment at a time."""
        return SetupLock(self.paths, self.environ)

    # Where things stand

    def setup_status(self) -> SetupStatus:
        """Where the setup stands."""
        ready = self.environment.ready()
        programs = set()
        games = set()
        any_program = False

        for each in EVERY_PROGRAM:
            if each.installed(self.paths):
                programs.add(each.key)

                if not each.is_tool:
                    any_program = True

        for game, exe in GAME_EXES.items():
            if (self.paths.drive_c / exe).is_file():
                games.add(game)

        return SetupStatus(
            prefix_ready=ready,
            programs=frozenset(programs),
            games=frozenset(games),
            complete=ready and any_program,
            graphics=self.config.graphics,
            gpu=self.config.gpu,
            fps_counter=GameEnvironment.fps_counter_on(self.config),
            graphics_cards=len(Proton.graphics_cards()),
        )

    def report_status(self) -> None:
        self.emit(self.setup_status())

    def finish(self, *lines: str) -> None:
        """End with where things stand, then any last words for the player."""
        self.report_status()
        self.emit(Done())

        for line in lines:
            self.emit(Log(line))

    # The game environment

    def ensure_runner(self) -> Proton:
        """Proton, ready to run programs."""
        for folder in (self.paths.base, self.paths.downloads, self.paths.logs):
            folder.mkdir(parents=True, exist_ok=True)

        # Without the 32-bit extensions Proton's container fails silently, so stop here with the fix.
        check = SystemCheck(self.paths, self.config)

        if check.flatpak_32bit_missing():
            for line in check.FLATPAK_32BIT_HELP.splitlines():
                self.emit(Log(line))

            raise SetupError("The 32-bit Flatpak extensions are not installed.")

        def progress(percent: int) -> None:
            self.emit(Progress(percent))

        proton = Proton(self.paths, self.config)
        proton.ensure(progress, self.cancel, self.emit)
        return proton

    def ensure_prefix(self) -> Proton:
        """Proton and a ready game environment with the current settings."""
        proton = self.ensure_runner()
        self.environment.prepare(proton, self.emit)
        return proton

    def need_prefix(self) -> None:
        if not self.environment.ready():
            raise SetupError(SET_UP_FIRST)


class StatusJob(Job):
    def body(self) -> None:
        self.report_status()


class CheckJob(Job):
    """The system check alone."""

    def body(self) -> None:
        if not SystemCheck(self.paths, self.config).run(self.emit):
            raise SetupError("The system check found a problem.")


class SyncShortcutsJob(Job):
    def body(self) -> None:
        if not MenuShortcuts(self.paths, self.environ).sync(self.emit):
            raise SetupError("The shortcuts could not be updated.")


class PrepareJob(Job):
    """The game environment: the system check, Proton, and the prefix."""

    # The plan's name for it, beside the programs' keys.
    KEY = "environment"
    # (step id, title, description) of each step, as the install page shows them
    STEPS = (
        ("doctor", "Check your system", "Making sure your computer has what the games need."),
        ("runner", "Get Proton", "Downloading the compatibility layer that runs Windows games."),
        ("prefix", "Create the game environment", "Setting up a private folder for the launchers and games."),
    )

    def body(self) -> None:
        self.start("doctor")

        if not SystemCheck(self.paths, self.config).run(self.emit):
            raise SetupError("Your system needs a change first. Fix the problems above, then try again.")

        self.done("doctor")

        with self.lock():
            self.start("runner")
            self.ensure_runner()
            self.done("runner")
            self.start("prefix")

            if not self.environment.ready():
                self.config = self.environment.detect_graphics(self.config, self.emit)

            # A new choice of graphics changes how Proton runs the programs.
            self.environment.prepare(Proton(self.paths, self.config), self.emit)
            self.done("prefix")
            self.finish("The game environment is ready.")


class InstallJob(Job):
    """Install one program, by its own steps (Program.run_install). Needs the game environment. `zip_path` is the Age of
    the Ring file the player chose; the other programs ignore it."""

    def __init__(self, key: str, zip_path: str | None, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.key = key
        self.zip_path = zip_path

    def body(self) -> None:
        chosen = program(self.key)
        self.need_prefix()

        with self.lock():
            for folder in (self.paths.downloads, self.paths.logs):
                folder.mkdir(parents=True, exist_ok=True)

            chosen.run_install(self)


class RemoveJob(Job):
    """Remove one program from the game environment, with its shortcut."""

    def __init__(self, key: str, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.key = key

    def body(self) -> None:
        with self.lock():
            program(self.key).remove(self.paths, self.config, self.emit)
            MenuShortcuts(self.paths, self.environ).sync(self.emit)
            self.finish()


class SwitchGraphicsJob(Job):
    def __init__(self, backend: str, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.backend = backend

    def body(self) -> None:
        with self.lock():
            self.config = self.environment.set_graphics(self.config, self.backend, self.emit)
            self.report_status()
            self.emit(Done())


class ChangeOptionJob(Job):
    """Save the graphics card or the FPS counter."""

    def __init__(self, option: str, value: str | int, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.option = option
        self.value = value

    def body(self) -> None:
        with self.lock():
            self.config = self.environment.set_option(self.config, self.option, self.value, self.emit)
            self.report_status()
            self.emit(Done())


class ResetJob(Job):
    """Delete the game environment, with every game and program in it."""

    def body(self) -> None:
        with self.lock():
            self.environment.reset(self.config, self.emit)
            MenuShortcuts(self.paths, self.environ).sync(self.emit)


class OpenJob(Job):
    """Open a program and wait until it ends. What it needs first is done before: the AIO Launcher is installed if it is
    missing, and the Arena updated. The lock is held only while the game environment is got ready, not while the program
    runs."""

    def __init__(self, key: str, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.key = key

    def body(self) -> None:
        chosen = program(self.key)

        # The AIO Launcher and the Arena install themselves when they are opened.
        if not chosen.prepare_installs and not chosen.installed(self.paths):
            raise SetupError(f"{chosen.title} is not installed.")

        with self.lock():
            proton = self.ensure_prefix()
            chosen.prepare_to_open(self.paths, proton, self.emit, self.cancel)

        chosen.open(self.paths, proton, self.emit)


class Engine:
    """The jobs the window runs, each as (emit, cancel) -> exit status. The tests give the window a stand-in with the same
    methods (tests/fake_jobs.py)."""

    OK = OK
    FAILED = FAILED
    NEEDS_FILE = NEEDS_FILE
    STOPPED = STOPPED

    def __init__(self, environ: dict[str, str] | None = None) -> None:
        self.environ = environ

    def status(self, emit: Emit, cancel: threading.Event | None = None) -> int:
        return StatusJob(emit, cancel, self.environ).run()

    def check(self, emit: Emit, cancel: threading.Event | None = None) -> int:
        return CheckJob(emit, cancel, self.environ).run()

    def sync_shortcuts(self, emit: Emit, cancel: threading.Event | None = None) -> int:
        return SyncShortcutsJob(emit, cancel, self.environ).run()

    def prepare(self, emit: Emit, cancel: threading.Event | None = None) -> int:
        return PrepareJob(emit, cancel, self.environ).run()

    def install(self, key: str, zip_path: str | None, emit: Emit, cancel: threading.Event | None = None) -> int:
        return InstallJob(key, zip_path, emit, cancel, self.environ).run()

    def remove(self, key: str, emit: Emit, cancel: threading.Event | None = None) -> int:
        return RemoveJob(key, emit, cancel, self.environ).run()

    def switch_graphics(self, backend: str, emit: Emit, cancel: threading.Event | None = None) -> int:
        return SwitchGraphicsJob(backend, emit, cancel, self.environ).run()

    def change_option(self, option: str, value: str | int, emit: Emit, cancel: threading.Event | None = None) -> int:
        return ChangeOptionJob(option, value, emit, cancel, self.environ).run()

    def reset(self, emit: Emit, cancel: threading.Event | None = None) -> int:
        return ResetJob(emit, cancel, self.environ).run()

    def open_program(self, key: str, emit: Emit, cancel: threading.Event | None = None) -> int:
        return OpenJob(key, emit, cancel, self.environ).run()

    def ready_to_open(self, key: str) -> bool:
        """Whether a shortcut can start this program without the wizard: the game environment is ready and the program is
        in it."""
        paths = Paths.of(self.environ)
        return GameEnvironment(paths).ready() and program(key).installed(paths)

    def setup_complete(self) -> bool:
        job = StatusJob(lambda _event: None, None, self.environ)

        try:
            job.config = ConfigFile(job.paths.config).load(self.environ)
        except ConfigError:
            pass

        return job.setup_status().complete
