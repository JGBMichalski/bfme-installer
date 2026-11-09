"""Age of the Ring, a large mod with its own launcher and its own copy of the games.

The app downloads its zip from ModDB (see moddb.py). It is a ZIP64 archive (~19 GB, Deflate64) that only 7-Zip can
open. The zip is unpacked, then its installer runs in the game environment.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ...context import Context
from ...download import Download
from ...errors import JobCancelled, SetupError
from ...events import Emit, Log, Progress, report_speed
from ...paths import Paths
from ..base import Program, Shortcut
from .moddb import ModDB, RemoteFile

if TYPE_CHECKING:
    from ...jobs import InstallJob

# Age of the Ring 10.0.0. Shown to the player, so they know what they are in for before they start.
DOWNLOAD_GB = 19
INSTALLED_GB = 28


@dataclass(frozen=True)
class ZipContents:
    exe_name: str  # the installer program inside the zip
    unpacked_bytes: int


class AgeOfTheRing(Program):
    key = "aotr"
    title = "Age of the Ring"
    name = "Age of the Ring"
    summary = "A large mod with its own launcher"
    removal = (
        f"It and its own copy of the games are deleted, which frees about {INSTALLED_GB} GB. Your settings for it are "
        "kept. The AIO Launcher, the Arena and the games you installed with the AIO Launcher are not touched."
    )
    before_install = f"About {DOWNLOAD_GB} GB to download."
    steps = (
        (
            "aotr-download",
            "Download Age of the Ring",
            "Downloading the file from ModDB. It is large and can take a while.",
        ),
        (
            "aotr-unpack",
            "Unpack the download",
            "Checking and extracting the installer files. This takes a few minutes.",
        ),
        ("aotr-install", "Install Age of the Ring", "Copying the game and the mod. This can take an hour."),
        ("aotr-settings", "Finish up", "Removing the temporary files."),
    )
    choice = (
        "Age of the Ring",
        "A large mod with its own launcher and its own copy of the games. It downloads from ModDB, about "
        f"{DOWNLOAD_GB} GB.",
    )
    shortcut = Shortcut(
        name="Age of the Ring",
        comment="Play the Age of the Ring mod for Battle for Middle-earth 2",
        suffix="Aotr",
    )

    # Left in the game environment until the installer finishes, so a half-finished install is not taken for the mod.
    INSTALLING = ".bfme-aotr-installing"
    # The installed game is about this much bigger than the unpacked installer, with a little room to spare. Measured for
    # 10.0.0: 18.87 GB unpacked, 27.51 GB installed (146%), so an install needs 46.4 GB at its peak and this asks for
    # 47.2 GB.
    INSTALL_RATIO_PERCENT = 150
    WATCH_SEC = 2
    NEED_7ZIP = (
        "7-Zip is needed to read the download. Install it (Debian/Ubuntu: p7zip-full, Fedora: 7zip, Arch: 7zip) "
        "and try again."
    )
    DOWNLOAD_AGAIN = "Try again, and the app downloads it again."
    # The installer's data files: AotR_Standalone_9.3.0_Installer-1a.bin, -1b.bin, -2a.bin, ...
    PART = re.compile(r"^(.*)-(\d+)([a-z])\.bin$")

    def exe(self, paths: Paths) -> Path:
        return paths.drive_c / "AgeoftheRing/AotR_Launcher.exe"

    def unpack_dir(self, paths: Paths) -> Path:
        """Where the zip is unpacked: the installer and its data files."""
        return paths.downloads / "aotr"

    def installed(self, paths: Paths) -> bool:
        return super().installed(paths) and not (paths.prefix / self.INSTALLING).exists()

    def leftovers(self, paths: Paths) -> list[Path]:
        return [paths.prefix / self.INSTALLING, self.unpack_dir(paths)]

    def zip_path(self, paths: Paths, remote: RemoteFile) -> Path:
        """Where the download goes."""
        return paths.downloads / remote.name

    def run_install(self, job: InstallJob) -> list[str]:
        """Download the zip from ModDB, check and unpack it, then run its installer."""
        job.start("aotr-download")
        remote = ModDB().find()
        # A retry after a failed install needs no download when the installer is still unpacked.
        contents = self.from_unpacked(job.paths, remote)

        if contents is None:
            self.check_space(job, remote)
            self.download_zip(job, remote)

        job.done("aotr-download")

        if contents is None:
            job.start("aotr-unpack")
            job.ensure_prefix()
            zip_path = self.zip_path(job.paths, remote)

            try:
                contents = self.unpack(job, zip_path)
            except SetupError:
                zip_path.unlink(missing_ok=True)  # the zip itself is bad: a retry downloads it again
                raise

            # The zip goes once it is unpacked, unless the player keeps it (BFME_KEEP_AOTR_DOWNLOAD).
            if not job.config.keep_aotr_download:
                zip_path.unlink(missing_ok=True)

            job.done("aotr-unpack")
        else:
            job.ensure_prefix()
            job.skip("aotr-unpack")

        job.start("aotr-install")
        self.run_installer(job, contents)
        job.done("aotr-install")

        job.start("aotr-settings")
        self.clean_up(job.paths)
        job.done("aotr-settings")

        return ["Age of the Ring is installed."]

    # The download

    def sevenzip(self) -> str:
        for name in ("7zz", "7z", "7za"):
            found = shutil.which(name)

            if found:
                return found

        raise SetupError(self.NEED_7ZIP)

    def zip_entries(self, zip_path: Path) -> list[tuple[int, str]]:
        """(size, name) per file in the zip. Fails on an incomplete zip, which has no
        directory."""
        done = subprocess.run(
            [self.sevenzip(), "l", "-slt", "-ba", "--", str(zip_path)], capture_output=True, text=True, check=False
        )

        if done.returncode != 0:
            raise SetupError(f"This file is incomplete or damaged. {self.DOWNLOAD_AGAIN}")

        entries = []
        name = None
        size = 0

        for line in done.stdout.splitlines():
            if line.startswith("Path = "):
                if name is not None:
                    entries.append((size, name))

                name = line[len("Path = ") :]
                size = 0

            if line.startswith("Size = "):
                size = int(line[len("Size = ") :] or 0)

        if name is not None:
            entries.append((size, name))

        return entries

    def check_zip(self, zip_path: Path) -> ZipContents:
        """Make sure this is the whole Age of the Ring installer, before anything is unpacked."""
        if not zip_path.is_file():
            raise SetupError(f"The file '{zip_path}' was not found.")

        entries = self.zip_entries(zip_path)
        exe_name = ""

        for _, name in entries:
            if re.fullmatch(r"AotR_Standalone_[^/]*_Installer\.exe", name):
                exe_name = name
                break

        if not exe_name:
            raise SetupError(f"The installer program is missing from this file. {self.DOWNLOAD_AGAIN}")

        stem = exe_name[: -len(".exe")]
        has_parts = False
        unpacked = 0

        for size, name in entries:
            unpacked += size
            match = self.PART.match(name)

            if match and match.group(1) == stem:
                has_parts = True

        if not has_parts:
            raise SetupError(f"The installer's data files are missing from this file. {self.DOWNLOAD_AGAIN}")

        return ZipContents(exe_name=exe_name, unpacked_bytes=unpacked)

    def download_zip(self, ctx: Context, remote: RemoteFile) -> Path:
        """Download the zip into the downloads folder, with progress, and check it against ModDB's MD5. A finished
        download is not repeated."""
        emit = ctx.emit
        cancel = ctx.cancel
        zip_path = self.zip_path(ctx.paths, remote)

        if zip_path.is_file() and zip_path.stat().st_size == remote.size:
            return zip_path

        emit(Log(f"Downloading {remote.name} ({remote.size // 1000000000} GB) from ModDB."))

        def progress(percent: int) -> None:
            emit(Progress(percent))

        Download(remote.url, zip_path, progress, cancel, report_speed(emit)).run()
        emit(Log("Checking the download."))
        Download.verify_md5(zip_path, remote.md5)

        return zip_path

    # Free space

    def dir_bytes(self, folder: Path) -> int:
        """The size of every file under the folder. Files the installer deletes while this counts are skipped."""
        total = 0

        for root, _dirs, files in os.walk(folder):
            for name in files:
                try:
                    total += os.lstat(os.path.join(root, name)).st_size
                except OSError:
                    pass

        return total

    def _already_there(self, paths: Paths) -> int:
        return self.dir_bytes(self.unpack_dir(paths)) + self.dir_bytes(self.folder(paths))

    def check_space(self, ctx: Context, remote: RemoteFile) -> None:
        """Before the download: the zip, then the installer unpacked from it (about as big as the zip), then the installed
        game must all fit. The zip is deleted once it is unpacked, unless the player keeps it. What is already there (the
        zip or part of it, the unpacked installer, the installed game) counts towards it."""
        paths = ctx.paths
        zip_path = self.zip_path(paths, remote)
        part = zip_path.with_name(zip_path.name + ".part")
        already = self._already_there(paths)

        for downloaded in (zip_path, part):
            if downloaded.is_file():
                already += downloaded.stat().st_size

        installed = remote.size * self.INSTALL_RATIO_PERCENT // 100
        # Without the zip the most at once is the unpacked installer and the installed game; with it, all three.
        need = remote.size + installed

        if ctx.config.keep_aotr_download:
            need += remote.size

        self._need_free_space(paths, need - already)

    def _need_free_space(self, paths: Paths, need: int) -> None:
        paths.base.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(paths.base).free

        if need > free:
            raise SetupError(
                f"Not enough free space: Age of the Ring needs {need // 1000000000 + 1} GB more, but only "
                f"{free // 1000000000} GB is free."
            )

    # Unpacking

    def from_unpacked(self, paths: Paths, remote: RemoteFile) -> ZipContents | None:
        """The installer this download left unpacked, when its unpack finished: a retry does not need the zip again."""
        unpack_dir = self.unpack_dir(paths)
        complete = unpack_dir / ".complete"

        if not complete.is_file() or complete.read_text().strip() != remote.name:
            return None

        for path in unpack_dir.glob("AotR_Standalone_*_Installer.exe"):
            return ZipContents(exe_name=path.name, unpacked_bytes=self.dir_bytes(unpack_dir))

        return None

    def unpack(self, ctx: Context, zip_path: Path) -> ZipContents:
        """Check the zip, then unpack it into the downloads folder. 7-Zip checks every file's CRC, so a damaged download
        fails here, not in the installer."""
        paths = ctx.paths
        emit = ctx.emit
        cancel = ctx.cancel
        unpack_dir = self.unpack_dir(paths)
        contents = self.check_zip(zip_path)

        def measure() -> int | None:
            """The unpack's progress: how much of the expected size is there."""
            if contents.unpacked_bytes <= 0:
                return None

            return self.dir_bytes(unpack_dir) * 100 // contents.unpacked_bytes

        command = [self.sevenzip(), "x", "-y", "-bd", "-bso0", "-bsp0", f"-o{unpack_dir}", str(zip_path)]
        shutil.rmtree(unpack_dir, ignore_errors=True)
        unpack_dir.mkdir(parents=True)
        paths.logs.mkdir(parents=True, exist_ok=True)
        log = paths.logs / "aotr-unpack.log"

        with open(log, "w", encoding="utf-8") as out:
            process = subprocess.Popen(command, stdout=out, stderr=out, stdin=subprocess.DEVNULL)
            code = self._watch(process, measure, emit, cancel)

        if code != 0:
            raise SetupError(f"The file could not be unpacked. It may be damaged. {self.DOWNLOAD_AGAIN} See {log}")

        # from_unpacked finds it by this, so a retry after a failed install does not unpack again.
        (unpack_dir / ".complete").write_text(zip_path.name + "\n")
        emit(Progress(100))

        return contents

    # Installing

    def run_installer(self, ctx: Context, contents: ZipContents) -> None:
        """Run the installer without its window. It leaves a marker until it is done, so a half-finished install is not
        taken for Age of the Ring."""
        paths = ctx.paths
        proton = ctx.proton
        emit = ctx.emit
        cancel = ctx.cancel
        unpack_dir = self.unpack_dir(paths)

        def measure() -> int | None:
            return self.install_percent(unpack_dir)

        def stop() -> None:
            proton.stop_session()

        (paths.prefix / self.INSTALLING).touch()
        paths.logs.mkdir(parents=True, exist_ok=True)
        args = [f"./{contents.exe_name}", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", r"/LOG=C:\aotr-install.log"]

        with open(paths.logs / "aotr-install.log", "w", encoding="utf-8") as out:
            process = proton.start(args, inprefix=True, output=out, cwd=unpack_dir)
            code = self._watch(process, measure, emit, cancel, stop)

        installer_log = paths.drive_c / "aotr-install.log"

        if installer_log.is_file():
            shutil.move(installer_log, paths.logs / "aotr-installer.log")

        if code != 0 or not self.exe(paths).is_file():
            raise SetupError(
                f"Age of the Ring was not installed (exit {code}). See {paths.logs / 'aotr-installer.log'}"
            )

        (paths.prefix / self.INSTALLING).unlink()
        emit(Progress(100))

    def clean_up(self, paths: Paths) -> None:
        """Delete the unpacked installer."""
        shutil.rmtree(self.unpack_dir(paths), ignore_errors=True)

    def install_percent(self, unpack_dir: Path, proc: Path = Path("/proc")) -> int | None:
        """How far the installer has read its data files, in percent. It reads them in order, so its position in them is
        its progress. The files are found among every process's open files by inode, which is the same inside and
        outside the Wine container. None while they cannot be seen."""
        starts = {}
        total = 0

        for part in self._parts(unpack_dir):
            st = part.stat()
            starts[(st.st_dev, st.st_ino)] = total
            total += st.st_size

        if total == 0:
            return None

        best = -1

        for fd in proc.glob("[0-9]*/fd/*"):
            try:
                st = os.stat(fd)
            except OSError:
                continue

            key = (st.st_dev, st.st_ino)

            if key not in starts:
                continue

            position = self._fd_position(proc / fd.parent.parent.name / "fdinfo" / fd.name)

            if position is not None:
                best = max(best, starts[key] + position)

        if best < 0:
            return None

        return min(100, best * 100 // total)

    def _parts(self, unpack_dir: Path) -> list[Path]:
        """The installer's data files in the order it reads them: by number, then letter."""
        found = []

        for path in unpack_dir.glob("*.bin"):
            match = self.PART.match(path.name)

            if match and path.is_file():
                found.append((int(match.group(2)), match.group(3), path))

        found.sort()
        ordered = []

        for _number, _letter, path in found:
            ordered.append(path)

        return ordered

    def _fd_position(self, fdinfo: Path) -> int | None:
        """The read position of an open file, from its fdinfo."""
        try:
            text = fdinfo.read_text()
        except OSError:
            return None

        for line in text.splitlines():
            if line.startswith("pos:"):
                return int(line[len("pos:") :].strip())

        return None

    def _watch(
        self,
        process: subprocess.Popen,
        measure: Callable[[], int | None],
        emit: Emit,
        cancel: threading.Event | None,
        on_cancel: Callable[[], None] | None = None,
    ) -> int:
        """Report progress while the process runs, capped at 99: only the process ending means done. A cancel stops the
        process, then on_cancel cleans up after it. Returns the exit status."""
        last = -1

        while process.poll() is None:
            if cancel is not None and cancel.is_set():
                process.terminate()

                if on_cancel is not None:
                    on_cancel()

                process.wait()
                raise JobCancelled()

            percent = measure()

            if percent is not None:
                percent = min(percent, 99)

                if percent != last:
                    emit(Progress(percent))
                    last = percent

            time.sleep(self.WATCH_SEC)

        return process.returncode
