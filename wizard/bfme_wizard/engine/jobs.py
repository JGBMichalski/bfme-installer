"""The jobs the wizard runs. Each wraps the setup's steps with what a whole job needs: the setup lock, the steps it reports,
where things stand when it ends, and its errors.

Every job takes (emit, cancel) and returns an exit status: 0 done, 1 failed, 130 stopped by the player.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import aotr, doctor, launch, programs, proton, shortcuts
from .config import Config, ConfigError
from .config import load as load_config
from .errors import JobCancelled, SetupError
from .events import Cancelled, Done, Emit, Error, Log, Progress, Status, Step
from .lock import setup_lock
from .moddb import ModdbUnavailable, find_aotr
from .paths import Paths
from .paths import paths as paths_for
from .prefix import (
    detect_graphics,
    prefix_ready,
    prepare_prefix,
    reset_prefix,
    set_graphics,
)

OK = 0
FAILED = 1
NEEDS_FILE = 2      # the app cannot download Age of the Ring itself: the player downloads it and chooses the file
STOPPED = 130
SET_UP_FIRST = "Set up the game environment first. Run: prepare"
AIO_LAUNCHER_DONE = [
    "Done. Start 'BFME All-in-One Launcher' to install the games, and 'BFME Online Arena' to play online.",
    "Do not switch patches in the AIO Launcher after a game is installed. On Wine this once broke the BFME 2 files.",
]

LABELS = {"aio-launcher": "the AIO Launcher", "workshop": "Workshop Studio", "mission-control": "Mission Control"}

@dataclass
class Job:
    """What a running job works with, and the step it is on (an error names it)."""
    paths: Paths
    config: Config
    emit: Emit
    cancel: threading.Event
    environ: dict[str, str] | None
    step: str | None = None

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
        """Mark a step as done."""
        self.emit(Step(step, "done"))
        self.step = None

    def skip(self, step: str) -> None:
        """Skip a step."""
        self.stop_if_asked()
        self.emit(Step(step, "skip"))

    def report_status(self) -> None:
        """Report the current status of all programs."""
        for key, value in programs.status(self.paths, self.config).items():
            self.emit(Status(key, value))

    def lock(self):
        """Acquire a lock for the job's paths and environment."""
        return setup_lock(self.paths, self.environ)


def _run(body: Callable[[Job], None], emit: Emit, cancel: threading.Event | None,
         environ: dict[str, str] | None) -> int:
    """Run a job's body and turn how it ended into events and an exit status."""
    paths = paths_for(environ)

    try:
        config = load_config(paths.config, environ)
    except ConfigError as error:
        emit(Error(None, str(error)))
        return FAILED

    job = Job(paths=paths, config=config, emit=emit, cancel=cancel or threading.Event(), environ=environ)

    try:
        body(job)
    except JobCancelled:
        emit(Cancelled())
        emit(Log("Stopped before the next step."))
        return STOPPED
    except SetupError as error:
        emit(Log(f"ERROR: {error}"))
        emit(Error(job.step, str(error)))
        return FAILED
    except ModdbUnavailable as error:
        emit(Log(f"The app cannot download it itself: {error}"))
        emit(Error(job.step, str(error)))
        return NEEDS_FILE

    return OK


def _ensure_runner(job: Job) -> str:
    """Proton, ready to run programs. Returns PROTONPATH for umu."""
    for folder in (job.paths.base, job.paths.downloads, job.paths.logs):
        folder.mkdir(parents=True, exist_ok=True)

    # Without the 32-bit extensions Proton's container fails silently, so stop here with the fix.
    if doctor.flatpak_32bit_missing():
        for line in doctor.FLATPAK_32BIT_HELP.splitlines():
            job.emit(Log(line))

        raise SetupError("The 32-bit Flatpak extensions are not installed.")

    def progress(percent: int) -> None:
        job.emit(Progress(percent))

    return proton.ensure_proton(job.paths, job.config, progress, job.cancel)


def _ensure_prefix(job: Job) -> str:
    """Proton and a ready game environment with the current settings. Returns PROTONPATH for umu."""
    proton_path = _ensure_runner(job)
    prepare_prefix(job.paths, job.config, proton_path, job.emit)
    return proton_path


def _finish(job: Job, *lines: str) -> None:
    """Finish the job, reporting its status and any final messages."""
    job.report_status()
    job.emit(Done())

    for line in lines:
        job.emit(Log(line))


def status(emit: Emit, cancel: threading.Event | None = None, environ: dict[str, str] | None = None) -> int:
    """Report the current status of the system."""
    return _run(Job.report_status, emit, cancel, environ)


def check(emit: Emit, cancel: threading.Event | None = None, environ: dict[str, str] | None = None) -> int:
    """Run the system check alone."""
    def body(job: Job) -> None:
        if not doctor.run_checks(job.paths, job.config, job.emit):
            raise SetupError(f"Failed (exit 1). See the logs in {job.paths.logs}")

    return _run(body, emit, cancel, environ)


def sync_shortcuts(emit: Emit, cancel: threading.Event | None = None, environ: dict[str, str] | None = None) -> int:
    """Synchronize the game shortcuts."""
    def body(job: Job) -> None:
        if not shortcuts.sync(job.paths, job.emit, job.environ):
            raise SetupError("The shortcuts could not be updated.")

    return _run(body, emit, cancel, environ)


def prepare(emit: Emit, cancel: threading.Event | None = None, environ: dict[str, str] | None = None) -> int:
    """Prepare the game environment: the system check, Proton, and the prefix."""
    def body(job: Job) -> None:
        job.start("doctor")

        if not doctor.run_checks(job.paths, job.config, job.emit):
            raise SetupError("Fix the problems above, then run prepare again.")

        job.done("doctor")

        with job.lock():
            job.start("runner")
            proton_path = _ensure_runner(job)
            job.done("runner")
            job.start("prefix")

            if not prefix_ready(job.paths):
                job.config = detect_graphics(job.paths, job.config, job.emit)

            prepare_prefix(job.paths, job.config, proton_path, job.emit)
            job.done("prefix")
            _finish(job, "The game environment is ready.")

    return _run(body, emit, cancel, environ)


def aio_launcher_install(emit: Emit, cancel: threading.Event | None = None, environ: dict[str, str] | None = None) -> int:
    """Install the AIO Launcher and the Arena, with their shortcuts. Needs the game environment."""
    def body(job: Job) -> None:
        if not prefix_ready(job.paths):
            raise SetupError(SET_UP_FIRST)

        with job.lock():
            if programs.aio_launcher_installed(job.paths):
                job.skip("aio-launcher")
            else:
                job.start("aio-launcher")
                proton_path = _ensure_prefix(job)
                programs.install_aio_launcher(job.paths, job.config, proton_path, job.emit, job.cancel)
                job.done("aio-launcher")

            job.start("arena")
            _ensure_prefix(job)
            programs.install_or_update_arena(job.paths, job.emit, job.cancel)
            job.done("arena")

            # The programs are installed whatever happens here, and sync says what went wrong.
            job.start("shortcuts")
            shortcuts.sync(job.paths, job.emit, job.environ)
            job.done("shortcuts")
            _finish(job, *AIO_LAUNCHER_DONE)

    return _run(body, emit, cancel, environ)


def aotr_install(zip_path: str | None, emit: Emit, cancel: threading.Event | None = None,
                 environ: dict[str, str] | None = None) -> int:
    """Install Age of the Ring. Without a zip from the player, the app downloads it from ModDB; when it cannot, the job
    ends with NEEDS_FILE and the player downloads it in a browser. Needs the game environment."""
    def body(job: Job) -> None:
        if not prefix_ready(job.paths):
            raise SetupError(SET_UP_FIRST)

        with job.lock():
            downloaded = not zip_path
            resumed = None

            if zip_path:
                job.emit(Step("aotr-download", "done"))   # the player did this step
                aotr_zip_path = Path(zip_path)
            else:
                job.start("aotr-download")
                remote = find_aotr()
                # A retry after a failed install needs no download when the installer is still unpacked.
                resumed = aotr.from_unpacked(job.paths, remote.name)

                if resumed is None:
                    aotr_zip_path = aotr.download_zip(job.paths, job.config, remote, job.emit, job.cancel)
                else:
                    aotr_zip_path = resumed.path

                job.done("aotr-download")

            if resumed is None:
                job.start("aotr-check")
                aotr_zip = aotr.check_zip(aotr_zip_path)
                aotr.check_space(job.paths, aotr_zip)
                proton_path = _ensure_prefix(job)
                job.done("aotr-check")

                job.start("aotr-unpack")
                aotr.unpack(job.paths, aotr_zip, job.emit, job.cancel)

                # The zip the app downloaded goes once it is unpacked, unless the player keeps it. The player's own stays.
                if downloaded and not job.config.keep_aotr_download:
                    aotr_zip.path.unlink(missing_ok=True)

                job.done("aotr-unpack")
            else:
                aotr_zip = resumed
                job.skip("aotr-check")
                proton_path = _ensure_prefix(job)
                job.skip("aotr-unpack")

            job.start("aotr-install")
            aotr.run_installer(job.paths, job.config, proton_path, aotr_zip, job.emit, job.cancel)
            job.done("aotr-install")

            job.start("aotr-settings")
            aotr.clean_up(job.paths)
            job.done("aotr-settings")

            shortcuts.sync(job.paths, job.emit, job.environ)

            if downloaded:
                _finish(job, "Age of the Ring is installed.")
            else:
                _finish(job, f"Age of the Ring is installed. You can delete {aotr_zip_path.name} now.")

    return _run(body, emit, cancel, environ)


def tool_install(tool: str, emit: Emit, cancel: threading.Event | None = None,
                 environ: dict[str, str] | None = None) -> int:
    """Install Workshop Studio or Mission Control. Needs the game environment."""
    def body(job: Job) -> None:
        if tool not in programs.TOOLS:
            raise SetupError("Use: tool-install workshop|mission-control")

        if not prefix_ready(job.paths):
            raise SetupError(SET_UP_FIRST)

        with job.lock():
            for folder in (job.paths.downloads, job.paths.logs):
                folder.mkdir(parents=True, exist_ok=True)

            job.start(tool)
            programs.install_tool(job.paths, tool, job.cancel)
            job.done(tool)
            _finish(job, f"{programs.NAMES[tool]} is installed.")

    return _run(body, emit, cancel, environ)


def remove(program: str, emit: Emit, cancel: threading.Event | None = None,
           environ: dict[str, str] | None = None) -> int:
    """Remove one program from the game environment, with its shortcut."""
    def body(job: Job) -> None:
        with job.lock():
            programs.remove(job.paths, job.config, program, job.emit)
            shortcuts.sync(job.paths, job.emit, job.environ)
            _finish(job)

    return _run(body, emit, cancel, environ)


def switch_graphics(backend: str, emit: Emit, cancel: threading.Event | None = None,
                    environ: dict[str, str] | None = None) -> int:
    """Switch the graphics backend for the game environment."""
    def body(job: Job) -> None:
        with job.lock():
            job.config = set_graphics(job.paths, job.config, backend, job.emit)
            job.emit(Status("graphics", job.config.graphics))
            job.emit(Done())

    return _run(body, emit, cancel, environ)


def reset(emit: Emit, cancel: threading.Event | None = None, environ: dict[str, str] | None = None) -> int:
    """Reset the game environment, deleting every game and program in it."""
    def body(job: Job) -> None:
        with job.lock():
            reset_prefix(job.paths, job.config, job.emit)
            shortcuts.sync(job.paths, job.emit, job.environ)

    return _run(body, emit, cancel, environ)


def open_program(program: str, emit: Emit, cancel: threading.Event | None = None,
                 environ: dict[str, str] | None = None) -> int:
    """Open a program and wait until it ends. The AIO Launcher is installed first if it is missing, and the Arena updated.
    The lock is held only while the game environment is got ready, not while the program runs."""
    def body(job: Job) -> None:
        if program in programs.TOOLS or program == "aotr":
            if not programs.installed(job.paths, program):
                raise SetupError(f"{programs.NAMES[program]} is not installed.")

        elif program not in ("aio-launcher", "arena"):
            raise SetupError("Use: open aio-launcher|arena|aotr|workshop|mission-control")

        with job.lock():
            proton_path = _ensure_prefix(job)

            if program == "aio-launcher":
                programs.install_aio_launcher(job.paths, job.config, proton_path, job.emit, job.cancel)

            if program == "arena":
                programs.install_or_update_arena(job.paths, job.emit, job.cancel)

        launch.start_program(job.paths, job.config, proton_path, program, _exe(job.paths, program),
                             LABELS.get(program, program), job.emit)

    return _run(body, emit, cancel, environ)


def _exe(paths: Paths, program: str) -> Path:
    if program == "aio-launcher":
        return paths.aio_launcher_exe

    if program == "arena":
        return paths.arena_exe

    if program == "aotr":
        return paths.aotr_exe

    return paths.tool_exe(program)


def ready_to_open(program: str, environ: dict[str, str] | None = None) -> bool:
    """Whether a shortcut can start this program without the wizard: the game environment is ready and the program is in
    it."""
    paths = paths_for(environ)
    return prefix_ready(paths) and programs.installed(paths, program)


def setup_complete(environ: dict[str, str] | None = None) -> bool:
    """Check if the setup of the game environment is complete."""
    paths = paths_for(environ)

    try:
        config = load_config(paths.config, environ)
    except ConfigError:
        config = Config()

    return programs.status(paths, config)["complete"] == "yes"

