"""The programs in the game environment: installing, updating and removing them, and what is installed."""
from __future__ import annotations

import hashlib
import shutil
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import proton
from .config import Config
from .download import download
from .errors import JobCancelled, SetupError
from .events import Emit, Log, Warn
from .paths import Paths
from .prefix import prefix_ready

AIO_LAUNCHER_URL = "https://arena-files.bfmeladder.com/downloads/AllInOneLauncherSetup.exe"
ARENA_FILES_HOST = "https://arena-files.bfmeladder.com"
ARENA_SERVER_HOST = "https://bfmeladder.com"
ARENA_BRANCH = "main"
TOOL_URLS = {
    "workshop": "https://bfmeladder.com/download-go?app=workshop",
    "mission-control": "https://bfmeladder.com/download-go?app=mission-control",
}
NAMES = {
    "aio-launcher": "BFME All-in-One Launcher",
    "arena": "BFME Online Arena",
    "aotr": "Age of the Ring",
    "workshop": "Workshop Studio",
    "mission-control": "Mission Control",
}
PROGRAMS = ("aio-launcher", "arena", "aotr")
TOOLS = ("workshop", "mission-control")
# Each game's program, under drive_c. A game counts as installed once it is there.
GAME_EXES = {"bfme1": "BFME1/lotrbfme.exe", "bfme2": "BFME2/lotrbfme2.exe", "rotwk": "RotWK/lotrbfme2ep1.exe"}

AIO_LAUNCHER_INSTALLING = ".bfme-aio-launcher-installing"
AOTR_INSTALLING = ".bfme-aotr-installing"
POLL_SEC = 3
AIO_LAUNCHER_WAIT_SEC = 180
HASH_TIMEOUT_SEC = 10


def aio_launcher_installed(paths: Paths) -> bool:
    """install_aio_launcher leaves a marker until it finishes, so a half-copied file is not taken for the AIO Launcher."""
    return paths.aio_launcher_exe.is_file() and not (paths.prefix / AIO_LAUNCHER_INSTALLING).exists()


def arena_installed(paths: Paths) -> bool:
    return paths.arena_exe.is_file()


def aotr_installed(paths: Paths) -> bool:
    return paths.aotr_exe.is_file() and not (paths.prefix / AOTR_INSTALLING).exists()


def tool_installed(paths: Paths, tool: str) -> bool:
    return paths.tool_exe(tool).is_file()


def installed(paths: Paths, program: str) -> bool:
    if program == "aio-launcher":
        return aio_launcher_installed(paths)

    if program == "arena":
        return arena_installed(paths)

    if program == "aotr":
        return aotr_installed(paths)

    if program in TOOLS:
        return tool_installed(paths, program)

    return False


def status(paths: Paths, config: Config) -> dict[str, str]:
    """Where the setup stands, as the wizard reads it. Complete means the game environment is ready and holds at least one
    program; the tools do not count."""
    ready = prefix_ready(paths)
    out = {
        "runner": "proton",
        "graphics": config.graphics,
        "prefix": "ready" if ready else "missing",
    }
    any_program = False

    for program in (*PROGRAMS, *TOOLS):
        is_installed = installed(paths, program)
        out[program] = "installed" if is_installed else "missing"

        if is_installed and program in PROGRAMS:
            any_program = True

    for game, exe in GAME_EXES.items():
        out[game] = "installed" if (paths.drive_c / exe).is_file() else "missing"

    out["complete"] = "yes" if ready and any_program else "no"

    return out


def wait_for_stable_file(path: Path, limit_sec: int, cancel: threading.Event | None = None) -> bool:
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

        time.sleep(POLL_SEC)
        waited += POLL_SEC

    return False


def install_aio_launcher(paths: Paths, config: Config, proton_path: str, emit: Emit, cancel: threading.Event | None = None,
                         url: str | None = None) -> None:
    """Run the AIO Launcher's setup in the game environment. The prefix must be ready."""
    if aio_launcher_installed(paths):
        return

    setup = paths.downloads / "AllInOneLauncherSetup.exe"

    if not setup.is_file():
        download(url or AIO_LAUNCHER_URL, setup, cancel=cancel)

    emit(Log("Installing the AIO Launcher. It may open for a moment; the setup closes it again."))

    # A leftover half-copied file would look finished to wait_for_stable_file.
    paths.aio_launcher_exe.unlink(missing_ok=True)
    (paths.prefix / AIO_LAUNCHER_INSTALLING).touch()
    paths.logs.mkdir(parents=True, exist_ok=True)

    # The setup starts the AIO Launcher, and Proton does not return until every program in the session ends. Wait for the
    # installed file to appear and stop growing, then end the session. The first start of the setup must not use
    # runinprefix.
    with open(paths.logs / "aio-launcher-setup.log", "w", encoding="utf-8") as out:
        process = proton.start(paths, config, proton_path, [str(setup)], inprefix=False, output=out)

        try:
            done = wait_for_stable_file(paths.aio_launcher_exe, AIO_LAUNCHER_WAIT_SEC, cancel)
        finally:
            if not proton.stop_wine_session(paths, proton_path):
                emit(Warn(proton.NO_WINE_SERVER))

            process.wait()

    if not done:
        raise SetupError(f"The AIO Launcher was not installed. See {paths.logs / 'aio-launcher-setup.log'}")

    (paths.prefix / AIO_LAUNCHER_INSTALLING).unlink()
    setup.unlink()


def _md5(path: Path) -> str:
    digest = hashlib.md5()

    with open(path, "rb") as f:
        while True:
            block = f.read(1024 * 1024)

            if not block:
                break

            digest.update(block)

    return digest.hexdigest()


def arena_remote_hash(server_host: str | None = None) -> str:
    """The MD5 of the newest Arena, or "" when the server cannot be asked."""
    server_host = server_host or ARENA_SERVER_HOST
    url = f"{server_host}/api/applications/versionHash?name=online-arena&version={ARENA_BRANCH}"

    try:
        with urllib.request.urlopen(url, timeout=HASH_TIMEOUT_SEC) as response:
            return response.read().decode(errors="replace").strip()
    except (urllib.error.URLError, OSError):
        return ""


def install_or_update_arena(paths: Paths, emit: Emit, cancel: threading.Event | None = None,
                            files_host: str | None = None, server_host: str | None = None) -> None:
    """Download the Arena, or a newer one. An installed Arena is kept when the server cannot be asked."""
    files_host = files_host or ARENA_FILES_HOST
    (paths.arena_exe.parent / "Data").mkdir(parents=True, exist_ok=True)
    remote = arena_remote_hash(server_host)

    if paths.arena_exe.is_file():
        if not remote:
            emit(Warn("Could not check for Arena updates. Starting the installed version."))
            return

        if _md5(paths.arena_exe) == remote:
            return

        emit(Log("A new Arena version is available."))
    else:
        emit(Log("The Arena is not installed yet."))

    tmp = paths.downloads / "OnlineArena.exe"
    tmp.unlink(missing_ok=True)
    tmp.with_name(tmp.name + ".part").unlink(missing_ok=True)
    download(f"{files_host}/application-builds/online-arena-{ARENA_BRANCH}", tmp, cancel=cancel)

    if remote:
        got = _md5(tmp)

        if got != remote:
            tmp.unlink()
            raise SetupError(f"Arena download failed its checksum check (expected {remote}, got {got}).")

    tmp.replace(paths.arena_exe)
    paths.arena_exe.chmod(0o755)


def install_tool(paths: Paths, tool: str, cancel: threading.Event | None = None, url: str | None = None) -> None:
    """Workshop Studio and Mission Control are single programs, so they are downloaded straight into a folder of their
    own."""
    exe = paths.tool_exe(tool)
    download(url or TOOL_URLS[tool], exe, cancel=cancel)
    exe.chmod(0o755)


# Removing

def remove(paths: Paths, config: Config, program: str, emit: Emit) -> None:
    """Take one program out of the game environment: its folder and what an interrupted install of it left. Keeps the
    games, the other programs and the settings a program keeps in the player's own folder."""
    if program == "aio-launcher":
        folder = paths.aio_launcher_exe.parent
    elif program == "arena":
        folder = paths.arena_exe.parent
    elif program == "aotr":
        folder = paths.aotr_exe.parent
    elif program in TOOLS:
        folder = paths.tool_exe(program).parent
    else:
        raise SetupError("Use: remove aio-launcher|arena|aotr|workshop|mission-control")

    # Whatever the settings say, never delete outside the game environment.
    if paths.drive_c not in folder.parents:
        raise SetupError(f"Refusing to delete '{folder}'.")

    if not proton.end_wine_session(paths, config):
        emit(Warn(proton.NO_WINE_SERVER))
    shutil.rmtree(folder, ignore_errors=True)
    leftovers: list[Path] = []

    if program == "aio-launcher":
        setup = paths.downloads / "AllInOneLauncherSetup.exe"
        leftovers = [paths.prefix / AIO_LAUNCHER_INSTALLING, setup, setup.with_name(setup.name + ".part")]

    if program == "arena":
        tmp = paths.downloads / "OnlineArena.exe"
        leftovers = [tmp, tmp.with_name(tmp.name + ".part")]

    if program == "aotr":
        leftovers = [paths.prefix / AOTR_INSTALLING]
        shutil.rmtree(paths.aotr_unpack, ignore_errors=True)

    for leftover in leftovers:
        leftover.unlink(missing_ok=True)

    emit(Log(f"Removed {NAMES[program]}."))
