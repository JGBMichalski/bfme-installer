"""What every program in the game environment has and does. Each program is a subclass that fills in its own facts and
overrides the steps it does differently."""

from __future__ import annotations

import shutil
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ..config import Config
from ..errors import SetupError
from ..events import Emit, Log, Warn
from ..logs import RunLogs
from ..paths import Paths
from ..proton import NO_WINE_SERVER, Proton

if TYPE_CHECKING:
    from ..jobs import InstallJob

# Where the programs' pictures are: one PNG for each, named for its key. Files shipped with the wizard, so they show with
# no network.
ICONS_DIR = Path(__file__).resolve().parents[2] / "icons"


@dataclass(frozen=True)
class Shortcut:
    """A program's entry in the application menu."""

    name: str
    comment: str
    suffix: str  # the end of the shortcut's file name and of its icon's name, both <app id>.<suffix>


# (step id, title, description) of a step on the install page
Step = tuple[str, str, str]


class Program(ABC):
    key: str  # what the engine, the shortcuts and the logs call it
    title: str  # on a card and in a list
    name: str  # in a sentence
    summary: str  # what it is
    removal: str  # what removing it deletes, and what it leaves alone
    before_install: str = ""  # what the player should know first

    # The steps of the job that installs it. Empty when another program's job does (the Arena's).
    steps: tuple[Step, ...] = ()
    # The program whose job installs this one.
    installed_by: str = ""
    # Installing one of a pair installs the other when it is missing.
    installed_with: str = ""
    # On the start page: (title, description). None when it is not offered there.
    choice: tuple[str, str] | None = None
    # A menu shortcut opens it, by `--open <key>` or one of these older names.
    shortcut: Shortcut | None = None
    aliases: tuple[str, ...] = ()
    # Opening it installs or updates it first (prepare_to_open), so it may be opened when it is missing.
    prepare_installs = False
    # The step that waits for a file the player downloads in a browser, when the app cannot download it itself. Its job
    # then ends with NEEDS_FILE, and the window asks for the file.
    file_step = ""
    # Its menu shortcut, clicked once it is gone from a complete setup, installs it again rather than only showing the
    # home screen.
    shortcut_reinstalls = False
    # The games are installed through it, so the home screen points at it while there are none.
    installs_games = False
    # Tools are listed apart and do not count towards a complete setup.
    is_tool = False

    @property
    def job(self) -> str:
        """The key of the program whose job installs this one."""
        return self.installed_by or self.key

    @property
    def icon(self) -> Path:
        """The program's own picture. Read from ICONS_DIR when it is asked for, so a test can point it somewhere else."""
        return ICONS_DIR / f"{self.key}.png"

    @abstractmethod
    def exe(self, paths: Paths) -> Path:
        """The program file in the game environment."""

    def folder(self, paths: Paths) -> Path:
        """What removing it deletes."""
        return self.exe(paths).parent

    def installed(self, paths: Paths) -> bool:
        return self.exe(paths).is_file()

    def leftovers(self, paths: Paths) -> list[Path]:
        """Files and folders an interrupted install leaves behind. Removing the program deletes them too."""
        return []

    def run_install(self, job: InstallJob) -> None:
        """The steps of its install job, with the setup lock held. A program installed by another one's job has none."""
        raise SetupError(f"{self.title} is installed with {self.installed_by}.")

    def prepare_to_open(self, paths: Paths, proton: Proton, emit: Emit, cancel: threading.Event | None = None) -> None:
        """What opening it needs first, while the setup lock is held. Nothing by default."""
        return

    def logs(self, paths: Paths) -> RunLogs:
        return RunLogs(paths.logs, self.key)

    def open(self, paths: Paths, proton: Proton, emit: Emit) -> int:
        """Run the program from its own folder and wait until it ends. Its output goes to a log of its own. Returns its
        exit status."""
        exe = self.exe(paths)
        logs = self.logs(paths)
        log = logs.new()
        emit(Log(f"Starting {self.name}. Log: {log}"))

        with open(log, "w", encoding="utf-8") as out:
            code = proton.run([str(exe)], inprefix=True, output=out, cwd=exe.parent)

        logs.remove_old()

        return code

    def remove(self, paths: Paths, config: Config, emit: Emit) -> None:
        """Take it out of the game environment: its folder and what an interrupted install of it left. Keeps the games,
        the other programs and the settings it keeps in the player's own folder."""
        folder = self.folder(paths)

        # Whatever the settings say, never delete outside the game environment.
        if paths.drive_c not in folder.parents:
            raise SetupError(f"Refusing to delete '{folder}'.")

        if not Proton(paths, config).end_session():
            emit(Warn(NO_WINE_SERVER))

        shutil.rmtree(folder, ignore_errors=True)

        for leftover in self.leftovers(paths):
            if leftover.is_dir():
                shutil.rmtree(leftover, ignore_errors=True)
            else:
                leftover.unlink(missing_ok=True)

        emit(Log(f"Removed {self.name}."))
