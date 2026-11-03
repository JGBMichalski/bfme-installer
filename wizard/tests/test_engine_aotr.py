"""engine.aotr: the Age of the Ring download, unpacking and installer."""

import os
import shutil
import subprocess
import sys
import threading
from collections import namedtuple
from pathlib import Path

import pytest

from bfme_wizard.engine.config import Config
from bfme_wizard.engine.errors import JobCancelled, SetupError
from bfme_wizard.engine.events import Progress
from bfme_wizard.engine.paths import Paths
from bfme_wizard.engine.prefix import GameEnvironment
from bfme_wizard.engine.programs import AOTR, AgeOfTheRing
from bfme_wizard.engine.programs import aotr as aotr_module
from bfme_wizard.engine.programs.aotr import AotrZip
from bfme_wizard.engine.proton import Proton

SEVENZIP = shutil.which("7zz") or shutil.which("7z") or shutil.which("7za")
needs_7zip = pytest.mark.skipif(SEVENZIP is None, reason="7-Zip is needed to read the Age of the Ring download")
Usage = namedtuple("Usage", "total used free")
EXE = "AotR_Standalone_9.3.0_Installer.exe"
ZIP = "AotR_Standalone_9.3.0_Installer.zip"

# Called with the installer, it installs Age of the Ring and writes the installer's own log, as the real one does.
FAKE_UMU = r"""#!/bin/sh
printf '%s|%s\n' "$*" "$(pwd)" >> "$UMU_LOG"
case "$1" in
  *AotR_Standalone*Installer.exe)
    [ -n "$NO_INSTALL" ] && exit 3
    [ -n "$HANG" ] && { sleep 30 & echo $! > "$SESSION_PID"; wait; exit 1; }
    mkdir -p "$WINEPREFIX/drive_c/AgeoftheRing"
    printf 'aotr' > "$WINEPREFIX/drive_c/AgeoftheRing/AotR_Launcher.exe"
    printf 'installer log' > "$WINEPREFIX/drive_c/aotr-install.log" ;;
esac
exit 0
"""


def executable(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)


@pytest.fixture
def paths(tmp_path):
    return Paths(tmp_path / "data")


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(AgeOfTheRing, "WATCH_SEC", 0.05)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A fake umu-run and lspci first on PATH."""
    executable(tmp_path / "bin" / "umu-run", FAKE_UMU)
    executable(tmp_path / "bin" / "lspci", "#!/bin/sh\n")
    values = {
        "PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "BFME_HOME": str(tmp_path / "data"),
        "BFME_PROTONPATH": "fake-proton",
        "UMU_LOG": str(tmp_path / "umu.log"),
        "SESSION_PID": str(tmp_path / "session.pid"),
        "XDG_DATA_HOME": str(tmp_path / "xdg"),
    }

    for name, value in values.items():
        monkeypatch.setenv(name, value)

    return values


def make_prefix(paths):
    for folder in ("windows", "users/steamuser"):
        (paths.drive_c / folder).mkdir(parents=True, exist_ok=True)


def make_zip(tmp_path, files, name=ZIP):
    """A zip holding these {name: bytes}, made with 7-Zip as the real download would be read."""
    source = tmp_path / ("zip-source-" + name)
    source.mkdir()

    for file_name, data in files.items():
        (source / file_name).write_bytes(data)

    zip_path = tmp_path / name
    subprocess.run([SEVENZIP, "a", "-tzip", "-bso0", "-bsp0", str(zip_path), "."], cwd=source, check=True)
    return zip_path


GOOD = {
    EXE: b"installer",
    "AotR_Standalone_9.3.0_Installer-1a.bin": os.urandom(4096),
    "AotR_Standalone_9.3.0_Installer-1b.bin": os.urandom(2048),
}


def progress(events):
    out = []

    for event in events:
        if isinstance(event, Progress):
            out.append(event.percent)

    return out


# Checking the download

BAD_DOWNLOAD_MESSAGES = {
    "unfinished": "This download is not finished yet. Wait until your browser has finished, then choose the file again.",
    "wrong name": "This is not the Age of the Ring installer. Choose the file named like AotR_Standalone_10.0.0_Installer.zip.",
    "damaged": "This file is incomplete or damaged. Download it again from ModDB.",
    "no installer": "The installer program is missing from this file. Download it again from ModDB.",
    "no data files": "The installer's data files are missing from this file. Download it again from ModDB.",
    "another installer's data files": "The installer's data files are missing from this file. Download it again from ModDB.",
}


def bad_downloads(tmp_path):
    """{case: zip path} for each way a download can be wrong."""
    for folder in "abc":
        (tmp_path / folder).mkdir()

    garbage = tmp_path / "garbage" / ZIP
    garbage.parent.mkdir()
    garbage.write_bytes(b"PK\x03\x04 not really a zip")
    unfinished = tmp_path / (ZIP + ".crdownload")
    unfinished.write_bytes(b"x")
    wrong_name = tmp_path / "AgeOfTheRing.zip"
    wrong_name.write_bytes(b"x")

    return {
        "missing": tmp_path / "nothing" / ZIP,
        "unfinished": unfinished,
        "wrong name": wrong_name,
        "damaged": garbage,
        "no installer": make_zip(tmp_path / "a", {"AotR_Standalone_9.3.0_Installer-1a.bin": b"x"}),
        "no data files": make_zip(tmp_path / "b", {EXE: b"installer", "readme.txt": b"x"}),
        "another installer's data files": make_zip(tmp_path / "c", {EXE: b"x", "Other_Installer-1a.bin": b"x"}),
    }


@needs_7zip
def test_a_bad_download_says_what_is_wrong(tmp_path):
    zips = bad_downloads(tmp_path)
    expected = dict(BAD_DOWNLOAD_MESSAGES)
    expected["missing"] = f"The file '{zips['missing']}' was not found."

    for case, zip_path in zips.items():
        with pytest.raises(SetupError) as raised:
            AOTR.check_zip(zip_path)

        assert str(raised.value) == expected[case], case


@needs_7zip
def test_a_good_download_names_its_installer_and_size(tmp_path):
    aotr_zip = AOTR.check_zip(make_zip(tmp_path, GOOD))

    assert aotr_zip.exe_name == EXE
    assert aotr_zip.unpacked_bytes == sum(len(data) for data in GOOD.values())


def test_without_7zip_it_says_what_to_install(tmp_path, monkeypatch):
    zip_path = tmp_path / ZIP
    zip_path.write_bytes(b"x")
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))

    with pytest.raises(SetupError, match="7-Zip is needed to read the download"):
        AOTR.check_zip(zip_path)


# Free space


def test_too_little_space_says_how_much_more_is_needed(paths, monkeypatch):
    monkeypatch.setattr(aotr_module.shutil, "disk_usage", lambda path: Usage(0, 0, 3_500_000_000))
    aotr_zip = AotrZip(Path(ZIP), EXE, unpacked_bytes=2_000_000_000)

    with pytest.raises(
        SetupError, match="^Not enough free space: Age of the Ring needs 6 GB more, but only 3 GB is free.$"
    ):
        AOTR.check_space(paths, aotr_zip)


def test_what_is_already_unpacked_or_installed_counts(paths, monkeypatch):
    # 1400 unpacked + 2240 installed = 3640 needed, of which 2600 is already there.
    monkeypatch.setattr(aotr_module.shutil, "disk_usage", lambda path: Usage(0, 0, 2000))
    (AOTR.unpack_dir(paths)).mkdir(parents=True)
    (AOTR.unpack_dir(paths) / "part.bin").write_bytes(b"x" * 1600)
    AOTR.exe(paths).parent.mkdir(parents=True)
    (AOTR.exe(paths).parent / "game.big").write_bytes(b"x" * 1000)

    AOTR.check_space(paths, AotrZip(Path(ZIP), EXE, unpacked_bytes=1400))


# Unpacking


@needs_7zip
def test_unpacking_reports_progress_and_is_not_repeated(tmp_path, paths):
    aotr_zip = AOTR.check_zip(make_zip(tmp_path, GOOD))
    events = []

    AOTR.unpack(paths, aotr_zip, events.append)

    assert progress(events)[-1] == 100
    assert (AOTR.unpack_dir(paths) / EXE).read_bytes() == b"installer"
    assert (AOTR.unpack_dir(paths) / ".complete").read_text() == ZIP + "\n"

    events.clear()
    AOTR.unpack(paths, aotr_zip, events.append)

    assert events == []


@needs_7zip
def test_a_different_zip_is_unpacked_again(tmp_path, paths):
    aotr_zip = AOTR.check_zip(make_zip(tmp_path, GOOD))
    AOTR.unpack_dir(paths).mkdir(parents=True)
    (AOTR.unpack_dir(paths) / "stale.bin").write_bytes(b"old")
    (AOTR.unpack_dir(paths) / ".complete").write_text("AotR_Standalone_9.2.0_Installer.zip\n")

    AOTR.unpack(paths, aotr_zip, [].append)

    assert not (AOTR.unpack_dir(paths) / "stale.bin").exists()
    assert (AOTR.unpack_dir(paths) / EXE).exists()


def test_a_failed_unpack_says_where_to_look(tmp_path, paths, monkeypatch):
    executable(tmp_path / "bin" / "7zz", "#!/bin/sh\necho 'CRC Failed' >&2\nexit 2\n")
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))

    with pytest.raises(SetupError, match="The file could not be unpacked. It may be damaged: .* See .*aotr-unpack.log"):
        AOTR.unpack(paths, AotrZip(tmp_path / ZIP, EXE, 100), [].append)

    assert not (AOTR.unpack_dir(paths) / ".complete").exists()
    assert "CRC Failed" in (paths.logs / "aotr-unpack.log").read_text()


def test_unpacking_stops_when_cancelled(tmp_path, paths, monkeypatch):
    executable(tmp_path / "bin" / "7zz", "#!/bin/sh\nexec /bin/sleep 30\n")
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    cancel = threading.Event()
    threading.Timer(0.2, cancel.set).start()

    with pytest.raises(JobCancelled):
        AOTR.unpack(paths, AotrZip(tmp_path / ZIP, EXE, 100), [].append, cancel)

    assert not (AOTR.unpack_dir(paths) / ".complete").exists()


# The installer's progress


def test_progress_is_how_far_the_installer_has_read_its_data_files(tmp_path):
    for name, size in (("X-1a.bin", 1000), ("X-1b.bin", 1000), ("X-2a.bin", 2000), ("notes.bin", 500)):
        (tmp_path / name).write_bytes(b"x" * size)

    assert AOTR.install_percent(tmp_path) is None

    # A process reading the third file, 500 bytes in: 1000 + 1000 + 500 of 4000.
    reader = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys, time\nf = open(sys.argv[1], 'rb')\nf.seek(500)\nprint('ready', flush=True)\ntime.sleep(30)",
            str(tmp_path / "X-2a.bin"),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )

    try:
        assert reader.stdout.readline() == "ready\n"
        assert AOTR.install_percent(tmp_path) == 62
    finally:
        reader.kill()
        reader.wait()


def test_data_files_are_read_by_number_then_letter(tmp_path):
    for name in ("X-10a.bin", "X-2b.bin", "X-2a.bin", "X-1a.bin"):
        (tmp_path / name).write_bytes(b"x")

    names = []

    for path in AOTR._parts(tmp_path):
        names.append(path.name)

    assert names == ["X-1a.bin", "X-2a.bin", "X-2b.bin", "X-10a.bin"]


# Running the installer


def unpacked(paths):
    AOTR.unpack_dir(paths).mkdir(parents=True, exist_ok=True)
    (AOTR.unpack_dir(paths) / EXE).write_text("installer")
    return AotrZip(Path(ZIP), EXE, 100)


def test_the_installer_runs_silently_in_the_unpack_folder(env, paths):
    make_prefix(paths)
    events = []

    AOTR.run_installer(paths, Proton(paths, Config(), "fake-proton"), unpacked(paths), events.append)

    assert (
        Path(env["UMU_LOG"]).read_text()
        == f"./{EXE} /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG=C:\\aotr-install.log|{AOTR.unpack_dir(paths)}\n"
    )
    assert AOTR.installed(paths)
    assert (paths.logs / "aotr-installer.log").read_text() == "installer log"
    assert not (paths.drive_c / "aotr-install.log").exists()
    assert progress(events)[-1] == 100


def test_an_installer_that_fails_leaves_it_unfinished(env, paths, monkeypatch):
    make_prefix(paths)
    monkeypatch.setenv("NO_INSTALL", "1")

    with pytest.raises(SetupError, match=r"Age of the Ring was not installed \(exit 3\). See .*aotr-installer.log"):
        AOTR.run_installer(paths, Proton(paths, Config(), "fake-proton"), unpacked(paths), [].append)

    assert (paths.prefix / AOTR.INSTALLING).exists()


def test_cancelling_the_installer_ends_the_wine_session(tmp_path, env, paths, monkeypatch):
    make_prefix(paths)
    monkeypatch.setenv("HANG", "1")
    log = tmp_path / "wineserver.log"
    executable(
        tmp_path / "proton/files/bin/wineserver",
        f'#!/bin/sh\necho "$*" >> \'{log}\'\n[ "$1" = -k ] && kill "$(cat "$SESSION_PID")" 2>/dev/null\nexit 0\n',
    )
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()

    with pytest.raises(JobCancelled):
        AOTR.run_installer(paths, Proton(paths, Config(), str(tmp_path / "proton")), unpacked(paths), [].append, cancel)

    assert log.read_text().startswith("-k\n")
    assert not AOTR.installed(paths)


# The whole install


def tree(paths):
    found = set()

    for path in paths.base.rglob("*"):
        relative = str(path.relative_to(paths.base))

        if not relative.startswith(("logs", ".setup.lock", "bin", "icons", "dxvk-cache")):
            found.add(relative)

    return found


# The game is installed, and the unpacked installer and the unfinished-install marker are gone.
WHOLE_INSTALL_TREE = {
    "downloads",
    "prefix",
    "prefix/.bfme-settings-v4",
    "prefix/drive_c",
    "prefix/drive_c/AgeoftheRing",
    "prefix/drive_c/AgeoftheRing/AotR_Launcher.exe",
    "prefix/drive_c/users",
    "prefix/drive_c/users/steamuser",
    "prefix/drive_c/windows",
}

# The prefix settings: one import of all of them.
PREFIX_SETTINGS = ["reg import C:\\bfme-settings.reg"]


@needs_7zip
def test_a_whole_install_leaves_the_game_and_cleans_up(tmp_path, env, paths):
    zip_path = make_zip(tmp_path, GOOD)
    make_prefix(paths)

    aotr_zip = AOTR.check_zip(zip_path)
    AOTR.check_space(paths, aotr_zip)
    GameEnvironment(paths).prepare(Proton(paths, Config(), "fake-proton"), [].append)
    AOTR.unpack(paths, aotr_zip, [].append)
    AOTR.run_installer(paths, Proton(paths, Config(), "fake-proton"), aotr_zip, [].append)
    AOTR.clean_up(paths)

    # Each call is logged as "arguments|working folder".
    expected_calls = []

    for setting in PREFIX_SETTINGS:
        expected_calls.append(f"{setting}|{os.getcwd()}")

    expected_calls.append(
        f"./{EXE} /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG=C:\\aotr-install.log|{AOTR.unpack_dir(paths)}"
    )

    assert tree(paths) == WHOLE_INSTALL_TREE
    assert Path(env["UMU_LOG"]).read_text().splitlines() == expected_calls


# Downloading it from ModDB


def remote_for(data, md5=None, url="http://127.0.0.1:1/never"):
    import hashlib

    from bfme_wizard.engine.moddb import RemoteFile

    return RemoteFile(name=ZIP, size=len(data), md5=md5 or hashlib.md5(data).hexdigest(), url=url)


def test_the_download_is_checked_against_moddbs_md5(paths, moddb):
    from bfme_wizard.engine.moddb import find_aotr

    data = os.urandom(8192)
    moddb.publish(data, name=ZIP)
    events = []

    zip_path = AOTR.download_zip(paths, Config(), find_aotr(), events.append)

    assert zip_path == paths.downloads / ZIP
    assert zip_path.read_bytes() == data
    assert progress(events)[-1] == 100


def test_a_download_with_the_wrong_md5_is_deleted(paths, moddb):
    from bfme_wizard.engine.moddb import find_aotr

    moddb.publish(b"what was uploaded", name=ZIP, md5="0" * 32)

    with pytest.raises(SetupError, match="Checksum mismatch"):
        AOTR.download_zip(paths, Config(), find_aotr(), [].append)

    assert not (paths.downloads / ZIP).exists()


def test_a_finished_download_is_not_repeated(paths):
    data = b"already here"
    paths.downloads.mkdir(parents=True)
    (paths.downloads / ZIP).write_bytes(data)

    assert AOTR.download_zip(paths, Config(), remote_for(data), [].append) == paths.downloads / ZIP


def test_before_downloading_there_must_be_room_for_the_unpacked_installer_and_the_game(paths, monkeypatch):
    monkeypatch.setattr(aotr_module.shutil, "disk_usage", lambda path: Usage(0, 0, 2_700_000_000))
    remote = remote_for(b"")
    remote = remote.__class__(remote.name, 1_000_000_000, remote.md5, remote.url)

    AOTR.check_download_space(paths, Config(), remote)  # 1 GB unpacked + 1.6 GB installed

    monkeypatch.setattr(aotr_module.shutil, "disk_usage", lambda path: Usage(0, 0, 2_000_000_000))

    with pytest.raises(SetupError, match="needs 3 GB more, but only 2 GB is free"):
        AOTR.check_download_space(paths, Config(), remote)


def test_keeping_the_download_needs_room_for_it_too(paths, monkeypatch):
    monkeypatch.setattr(aotr_module.shutil, "disk_usage", lambda path: Usage(0, 0, 3_000_000_000))
    remote = remote_for(b"")
    remote = remote.__class__(remote.name, 1_000_000_000, remote.md5, remote.url)

    AOTR.check_download_space(paths, Config(), remote)

    with pytest.raises(SetupError, match="needs 4 GB more"):
        AOTR.check_download_space(paths, Config(keep_aotr_download=True), remote)


def test_an_unpacked_installer_of_the_same_zip_is_used_again(paths):
    assert AOTR.from_unpacked(paths, ZIP) is None
    unpacked(paths)
    (AOTR.unpack_dir(paths) / "AotR_Standalone_9.3.0_Installer-1a.bin").write_bytes(b"x" * 10)

    assert AOTR.from_unpacked(paths, ZIP) is None  # its unpack did not finish
    (AOTR.unpack_dir(paths) / ".complete").write_text(ZIP + "\n")
    found = AOTR.from_unpacked(paths, ZIP)

    assert (found.exe_name, found.unpacked_bytes) == (EXE, len("installer") + 10 + len(ZIP) + 1)
    assert AOTR.from_unpacked(paths, "AotR_Standalone_10.1.0_Installer.zip") is None
