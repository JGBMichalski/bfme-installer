"""The BFME Online Arena, for multiplayer. It comes with the AIO Launcher, and updates itself each time it is opened."""

from __future__ import annotations

import hashlib
import threading
import urllib.error
import urllib.request
from pathlib import Path

from ..download import Download
from ..errors import SetupError
from ..events import Emit, Log, Warn, report_speed
from ..paths import Paths
from ..proton import Proton
from .base import Program, Shortcut


class Arena(Program):
    key = "arena"
    title = "Arena"
    name = "the Arena"
    summary = "Play online matches against other players"
    removal = "Its files and settings are deleted. The AIO Launcher, the games and Age of the Ring are not touched."
    installed_by = "aio-launcher"
    installed_with = "aio-launcher"
    shortcut = Shortcut(
        name="BFME Online Arena",
        comment="Play Battle for Middle-earth online",
        suffix="Arena",
    )
    prepare_installs = True

    FILES_HOST = "https://arena-files.bfmeladder.com"
    SERVER_HOST = "https://bfmeladder.com"
    BRANCH = "main"
    HASH_TIMEOUT_SEC = 10

    def exe(self, paths: Paths) -> Path:
        return paths.roaming / "BFME Competetive Arena/BfmeFoundationProject_OnlineArena.exe"

    def download_file(self, paths: Paths) -> Path:
        return paths.downloads / "OnlineArena.exe"

    def leftovers(self, paths: Paths) -> list[Path]:
        tmp = self.download_file(paths)
        return [tmp, tmp.with_name(tmp.name + ".part")]

    def prepare_to_open(self, paths: Paths, proton: Proton, emit: Emit, cancel: threading.Event | None = None) -> None:
        self.update(paths, emit, cancel)

    def remote_hash(self, server_host: str | None = None) -> str:
        """The MD5 of the newest Arena, or "" when the server cannot be asked."""
        server_host = server_host or self.SERVER_HOST
        url = f"{server_host}/api/applications/versionHash?name=online-arena&version={self.BRANCH}"

        try:
            request = urllib.request.Request(url, headers={"User-Agent": Download.USER_AGENT})

            with urllib.request.urlopen(request, timeout=self.HASH_TIMEOUT_SEC) as response:
                return response.read().decode(errors="replace").strip()
        except (urllib.error.URLError, OSError):
            return ""

    def update(
        self,
        paths: Paths,
        emit: Emit,
        cancel: threading.Event | None = None,
        files_host: str | None = None,
        server_host: str | None = None,
    ) -> None:
        """Download the Arena, or a newer one. An installed Arena is kept when the server cannot be asked."""
        files_host = files_host or self.FILES_HOST
        exe = self.exe(paths)
        (exe.parent / "Data").mkdir(parents=True, exist_ok=True)
        remote = self.remote_hash(server_host)

        if exe.is_file():
            if not remote:
                emit(Warn("Could not check for Arena updates. Starting the installed version."))
                return

            if self._md5(exe) == remote:
                return

            emit(Log("A new Arena version is available."))
        else:
            emit(Log("The Arena is not installed yet."))

        tmp = self.download_file(paths)
        tmp.unlink(missing_ok=True)
        tmp.with_name(tmp.name + ".part").unlink(missing_ok=True)
        emit(Log(f"Downloading {tmp.name}."))
        Download(
            f"{files_host}/application-builds/online-arena-{self.BRANCH}",
            tmp,
            cancel=cancel,
            on_speed=report_speed(emit),
        ).run()

        if remote:
            got = self._md5(tmp)

            if got != remote:
                tmp.unlink()
                raise SetupError(f"Arena download failed its checksum check (expected {remote}, got {got}).")

        tmp.replace(exe)
        exe.chmod(0o755)

    def _md5(self, path: Path) -> str:
        digest = hashlib.md5()

        with open(path, "rb") as f:
            while True:
                block = f.read(1024 * 1024)

                if not block:
                    break

                digest.update(block)

        return digest.hexdigest()
