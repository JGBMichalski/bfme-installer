"""The community All-in-One Launcher, which installs, patches and starts the games."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from ..download import Download
from ..errors import JobCancelled, SetupError
from ..events import Emit, Log, Warn, report_speed
from ..paths import Paths
from ..proton import NO_WINE_SERVER, Proton
from ..shortcuts import MenuShortcuts
from .base import Program, Shortcut

if TYPE_CHECKING:
    from ..jobs import InstallJob


class AioLauncher(Program):
    key = "aio-launcher"
    title = "AIO Launcher"
    name = "the AIO Launcher"
    summary = "Install, patch and start your games"
    removal = (
        "Its files and settings are deleted. The games it installed, the Arena and Age of the Ring are not touched."
    )
    steps = (
        ("aio-launcher", "Download the AIO Launcher", "Fetching the All-in-One Launcher for managing the games."),
        ("arena", "Download the Arena", "Fetching the Online Arena for playing multiplayer."),
        ("shortcuts", "Add menu shortcuts", "Adding the AIO Launcher and the Arena to your application menu."),
    )
    installed_with = "arena"
    choice = (
        "All-in-One Launcher",
        "Install, patch and play the BFME games. Includes the Online Arena for multiplayer.",
    )
    shortcut = Shortcut(
        name="BFME All-in-One Launcher",
        comment="Install, mod and manage the Battle for Middle-earth games",
        suffix="AioLauncher",
    )
    # Shortcuts made before it was called "aio-launcher" pass "launcher".
    aliases = ("launcher",)
    prepare_installs = True
    installs_games = True

    URL = "https://arena-files.bfmeladder.com/downloads/AllInOneLauncherSetup.exe"
    # Left in the game environment until the setup finishes, so a half-copied file is not taken for the AIO Launcher.
    INSTALLING = ".bfme-aio-launcher-installing"
    POLL_SEC = 3
    WAIT_SEC = 180
    DONE = (
        "Done. Start 'BFME All-in-One Launcher' to install the games, and 'BFME Online Arena' to play online.",
        "Do not switch patches in the AIO Launcher after a game is installed. On Wine this once broke the BFME 2 files.",
    )

    def exe(self, paths: Paths) -> Path:
        return paths.roaming / "BFME All In One Launcher/AllInOneLauncher.exe"

    def setup_file(self, paths: Paths) -> Path:
        return paths.downloads / "AllInOneLauncherSetup.exe"

    def installed(self, paths: Paths) -> bool:
        return super().installed(paths) and not (paths.prefix / self.INSTALLING).exists()

    def leftovers(self, paths: Paths) -> list[Path]:
        setup = self.setup_file(paths)
        return [paths.prefix / self.INSTALLING, setup, setup.with_name(setup.name + ".part")]

    def run_install(self, job: InstallJob) -> None:
        """It, then the Arena that comes with it, then their shortcuts."""
        from . import ARENA

        if self.installed(job.paths):
            job.skip("aio-launcher")
        else:
            job.start("aio-launcher")
            proton = job.ensure_prefix()
            self.install(job.paths, proton, job.emit, job.cancel)
            job.done("aio-launcher")

        job.start("arena")
        job.ensure_prefix()
        ARENA.update(job.paths, job.emit, job.cancel)
        job.done("arena")

        # The programs are installed whatever happens here, and sync says what went wrong.
        job.start("shortcuts")
        MenuShortcuts(job.paths, job.environ).sync(job.emit)
        job.done("shortcuts")
        job.finish(*self.DONE)

    def prepare_to_open(self, paths: Paths, proton: Proton, emit: Emit, cancel: threading.Event | None = None) -> None:
        self.install(paths, proton, emit, cancel)

    def install(
        self,
        paths: Paths,
        proton: Proton,
        emit: Emit,
        cancel: threading.Event | None = None,
        url: str | None = None,
    ) -> None:
        """Run its setup in the game environment, unless it is installed. The prefix must be ready."""
        if self.installed(paths):
            return

        exe = self.exe(paths)
        setup = self.setup_file(paths)

        if not setup.is_file():
            emit(Log(f"Downloading {setup.name}."))
            Download(url or self.URL, setup, cancel=cancel, on_speed=report_speed(emit)).run()

        emit(Log("Installing the AIO Launcher. It may open for a moment; the setup closes it again."))

        # A leftover half-copied file would look finished to wait_for_stable_file.
        exe.unlink(missing_ok=True)
        (paths.prefix / self.INSTALLING).touch()
        paths.logs.mkdir(parents=True, exist_ok=True)
        log = paths.logs / "aio-launcher-setup.log"

        # The setup starts the AIO Launcher, and Proton does not return until every program in the session ends. Wait for
        # the installed file to appear and stop growing, then end the session. The first start of the setup must not use
        # runinprefix.
        with open(log, "w", encoding="utf-8") as out:
            process = proton.start([str(setup)], inprefix=False, output=out)

            try:
                done = self.wait_for_stable_file(exe, self.WAIT_SEC, cancel)
            finally:
                if not proton.stop_session():
                    emit(Warn(NO_WINE_SERVER))

                process.wait()

        if not done:
            raise SetupError(f"The AIO Launcher was not installed. See {log}")

        (paths.prefix / self.INSTALLING).unlink()
        setup.unlink()

    def wait_for_stable_file(self, path: Path, limit_sec: int, cancel: threading.Event | None = None) -> bool:
        """Wait until the file exists and its size stops changing between two looks. False after limit_sec."""
        waited = 0
        last = -1

        while waited < limit_sec:
            if cancel is not None and cancel.is_set():
                raise JobCancelled()

            if path.is_file():
                size = path.stat().st_size

                if size > 0 and size == last:
                    return True

                last = size

            time.sleep(self.POLL_SEC)
            waited += self.POLL_SEC

        return False
