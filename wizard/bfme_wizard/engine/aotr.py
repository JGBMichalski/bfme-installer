"""Age of the Ring: checking the download, unpacking it, and running its installer in the game environment.

The zip comes from ModDB: the app downloads it (see moddb.py), or the player does and chooses it. It is a ZIP64 archive
(~19 GB, Deflate64) that only 7-Zip can open.
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

from . import proton
from .config import Config
from .download import download, verify_md5
from .errors import JobCancelled, SetupError
from .events import Emit, Log, Progress, report_speed
from .moddb import RemoteFile
from .paths import Paths
from .programs import AOTR_INSTALLING

# The installed game is about this much bigger than the unpacked installer, with a little room to spare. Measured for 10.0.0:
# 18.87 GB unpacked, 27.51 GB installed (146%), so an install needs 46.4 GB at its peak and this asks for 47.2 GB.
INSTALL_RATIO_PERCENT = 150
WATCH_SEC = 2
NEED_7ZIP = (
    "7-Zip is needed to read the download. Install it (Debian/Ubuntu: p7zip-full, Fedora: 7zip, Arch: 7zip) "
    "and try again."
)
DOWNLOAD_AGAIN = "Download it again from ModDB."
# The installer's data files: AotR_Standalone_9.3.0_Installer-1a.bin, -1b.bin, -2a.bin, ...
PART = re.compile(r"^(.*)-(\d+)([a-z])\.bin$")


@dataclass(frozen=True)
class AotrZip:
    path: Path
    exe_name: str  # the installer program inside the zip
    unpacked_bytes: int


def sevenzip() -> str:
    for name in ("7zz", "7z", "7za"):
        found = shutil.which(name)

        if found:
            return found

    raise SetupError(NEED_7ZIP)


def zip_entries(zip_path: Path) -> list[tuple[int, str]]:
    """(size, name) per file in the zip. Fails on an incomplete zip: an unfinished browser download has no directory."""
    done = subprocess.run(
        [sevenzip(), "l", "-slt", "-ba", "--", str(zip_path)], capture_output=True, text=True, check=False
    )

    if done.returncode != 0:
        raise SetupError(f"This file is incomplete or damaged. {DOWNLOAD_AGAIN}")

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


def check_zip(zip_path: Path) -> AotrZip:
    """Make sure this is the whole Age of the Ring download, before anything is unpacked."""
    if not zip_path.is_file():
        raise SetupError(f"The file '{zip_path}' was not found.")

    if zip_path.name.endswith((".part", ".crdownload", ".download")):
        raise SetupError(
            "This download is not finished yet. Wait until your browser has finished, then choose the file again."
        )

    if not re.fullmatch(r"AotR_Standalone_.*_Installer\.zip", zip_path.name):
        raise SetupError(
            "This is not the Age of the Ring installer. Choose the file named like "
            "AotR_Standalone_10.0.0_Installer.zip."
        )

    entries = zip_entries(zip_path)
    exe_name = ""

    for _, name in entries:
        if re.fullmatch(r"AotR_Standalone_[^/]*_Installer\.exe", name):
            exe_name = name
            break

    if not exe_name:
        raise SetupError(f"The installer program is missing from this file. {DOWNLOAD_AGAIN}")

    stem = exe_name[: -len(".exe")]
    has_parts = False
    unpacked = 0

    for size, name in entries:
        unpacked += size
        match = PART.match(name)

        if match and match.group(1) == stem:
            has_parts = True

    if not has_parts:
        raise SetupError(f"The installer's data files are missing from this file. {DOWNLOAD_AGAIN}")

    return AotrZip(path=zip_path, exe_name=exe_name, unpacked_bytes=unpacked)


def dir_bytes(folder: Path) -> int:
    """The size of every file under the folder. Files the installer deletes while this counts are skipped."""
    total = 0

    for root, _dirs, files in os.walk(folder):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                pass

    return total


def check_space(paths: Paths, aotr_zip: AotrZip) -> None:
    """The unpacked installer and the installed game must both fit. What is already there counts towards it."""
    already = dir_bytes(paths.aotr_unpack) + dir_bytes(paths.aotr_exe.parent)
    need = aotr_zip.unpacked_bytes + aotr_zip.unpacked_bytes * INSTALL_RATIO_PERCENT // 100 - already
    _need_free_space(paths, need)


def _need_free_space(paths: Paths, need: int) -> None:
    paths.base.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(paths.base).free

    if need > free:
        raise SetupError(
            f"Not enough free space: Age of the Ring needs {need // 1000000000 + 1} GB more, but only "
            f"{free // 1000000000} GB is free."
        )


def check_download_space(paths: Paths, config: Config, remote: RemoteFile) -> None:
    """Before the download: the zip, then the installer unpacked from it (about as big as the zip), then the installed game.
    The zip is deleted once it is unpacked, unless the player keeps it."""
    zip_path = paths.downloads / remote.name
    part = zip_path.with_name(zip_path.name + ".part")
    already = dir_bytes(paths.aotr_unpack) + dir_bytes(paths.aotr_exe.parent)

    if part.is_file():
        already += part.stat().st_size

    installed = remote.size * INSTALL_RATIO_PERCENT // 100
    # Without the zip the most at once is the unpacked installer and the installed game; with it, all three.
    need = remote.size + installed

    if config.keep_aotr_download:
        need += remote.size

    _need_free_space(paths, need - already)


def download_zip(
    paths: Paths, config: Config, remote: RemoteFile, emit: Emit, cancel: threading.Event | None = None
) -> Path:
    """Download the zip into the downloads folder, with progress, and check it against ModDB's MD5. A finished download
    is not repeated."""
    zip_path = paths.downloads / remote.name

    if zip_path.is_file() and zip_path.stat().st_size == remote.size:
        return zip_path

    check_download_space(paths, config, remote)
    emit(Log(f"Downloading {remote.name} ({remote.size // 1000000000} GB) from ModDB."))

    def progress(percent: int) -> None:
        emit(Progress(percent))

    download(remote.url, zip_path, progress, cancel, report_speed(emit))
    emit(Log("Checking the download."))
    verify_md5(zip_path, remote.md5)

    return zip_path


def from_unpacked(paths: Paths, zip_name: str) -> AotrZip | None:
    """The installer this zip left unpacked, when its unpack finished: a retry does not need the zip again."""
    complete = paths.aotr_unpack / ".complete"

    if not complete.is_file() or complete.read_text().strip() != zip_name:
        return None

    for path in paths.aotr_unpack.glob("AotR_Standalone_*_Installer.exe"):
        return AotrZip(path=paths.downloads / zip_name, exe_name=path.name, unpacked_bytes=dir_bytes(paths.aotr_unpack))

    return None


def _watch(
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

        time.sleep(WATCH_SEC)

    return process.returncode


def unpack(paths: Paths, aotr_zip: AotrZip, emit: Emit, cancel: threading.Event | None = None) -> None:
    """Unpack the zip into the downloads folder. A finished unpack of the same zip is not repeated. 7-Zip checks every
    file's CRC, so a damaged download fails here, not in the installer."""

    def measure() -> int | None:
        """Measure the unpack progress as a percentage of the total expected bytes."""
        if aotr_zip.unpacked_bytes <= 0:
            return None

        return dir_bytes(paths.aotr_unpack) * 100 // aotr_zip.unpacked_bytes

    complete = paths.aotr_unpack / ".complete"

    if complete.is_file() and complete.read_text().strip() == aotr_zip.path.name:
        return

    command = [sevenzip(), "x", "-y", "-bd", "-bso0", "-bsp0", f"-o{paths.aotr_unpack}", str(aotr_zip.path)]
    shutil.rmtree(paths.aotr_unpack, ignore_errors=True)
    paths.aotr_unpack.mkdir(parents=True)
    paths.logs.mkdir(parents=True, exist_ok=True)
    log = paths.logs / "aotr-unpack.log"

    with open(log, "w", encoding="utf-8") as out:
        process = subprocess.Popen(command, stdout=out, stderr=out, stdin=subprocess.DEVNULL)
        code = _watch(process, measure, emit, cancel)

    if code != 0:
        raise SetupError(f"The file could not be unpacked. It may be damaged: download it again from ModDB. See {log}")

    complete.write_text(aotr_zip.path.name + "\n")
    emit(Progress(100))


def _parts(unpack_dir: Path) -> list[Path]:
    """The installer's data files in the order it reads them: by number, then letter."""
    found = []

    for path in unpack_dir.glob("*.bin"):
        match = PART.match(path.name)

        if match and path.is_file():
            found.append((int(match.group(2)), match.group(3), path))

    found.sort()
    ordered = []

    for _number, _letter, path in found:
        ordered.append(path)

    return ordered


def install_percent(unpack_dir: Path, proc: Path = Path("/proc")) -> int | None:
    """How far the installer has read its data files, in percent. It reads them in order, so its position in them is its
    progress. The files are found among every process's open files by inode, which is the same inside and outside the
    Wine container. None while they cannot be seen."""
    starts = {}
    total = 0

    for part in _parts(unpack_dir):
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

        position = _fd_position(proc / fd.parent.parent.name / "fdinfo" / fd.name)

        if position is not None:
            best = max(best, starts[key] + position)

    if best < 0:
        return None

    return min(100, best * 100 // total)


def _fd_position(fdinfo: Path) -> int | None:
    """Get the current position of the file descriptor from its fdinfo file."""
    try:
        text = fdinfo.read_text()
    except OSError:
        return None

    for line in text.splitlines():
        if line.startswith("pos:"):
            return int(line[len("pos:") :].strip())

    return None


def run_installer(
    paths: Paths, config: Config, proton_path: str, aotr_zip: AotrZip, emit: Emit, cancel: threading.Event | None = None
) -> None:
    """Run the Age of the Ring installer without its window. It leaves a marker until it is done, so a half-finished install
    is not taken for Age of the Ring."""

    def measure() -> int | None:
        """Measure the install progress as a percentage of the total expected bytes."""
        return install_percent(paths.aotr_unpack)

    def stop() -> None:
        """Stop the Wine session for the installer."""
        proton.stop_wine_session(paths, proton_path)

    (paths.prefix / AOTR_INSTALLING).touch()
    paths.logs.mkdir(parents=True, exist_ok=True)
    args = [f"./{aotr_zip.exe_name}", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", r"/LOG=C:\aotr-install.log"]

    with open(paths.logs / "aotr-install.log", "w", encoding="utf-8") as out:
        process = proton.start(paths, config, proton_path, args, inprefix=True, output=out, cwd=paths.aotr_unpack)
        code = _watch(process, measure, emit, cancel, stop)

    installer_log = paths.drive_c / "aotr-install.log"

    if installer_log.is_file():
        shutil.move(installer_log, paths.logs / "aotr-installer.log")

    if code != 0 or not paths.aotr_exe.is_file():
        raise SetupError(f"Age of the Ring was not installed (exit {code}). See {paths.logs / 'aotr-installer.log'}")

    (paths.prefix / AOTR_INSTALLING).unlink()
    emit(Progress(100))


def clean_up(paths: Paths) -> None:
    """Delete the unpacked installer."""
    shutil.rmtree(paths.aotr_unpack, ignore_errors=True)
