"""engine.programs.aotr: the Age of the Ring download, unpacking and installer."""

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
from bfme_wizard.engine.game_environment import GameEnvironment
from bfme_wizard.engine.paths import Paths
from bfme_wizard.engine.programs import AOTR, AgeOfTheRing
from bfme_wizard.engine.programs.aotr import ModDB, RemoteFile, ZipContents
from bfme_wizard.engine.programs.aotr import program as aotr_module
from tests.helpers import context

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
    "damaged": "This file is incomplete or damaged. Try again, and the app downloads it again.",
    "no installer": "The installer program is missing from this file. Try again, and the app downloads it again.",
    "no data files": "The installer's data files are missing from this file. Try again, and the app downloads it again.",
    "another installer's data files": (
        "The installer's data files are missing from this file. Try again, and the app downloads it again."
    ),
}


def bad_downloads(tmp_path):
    """{case: zip path} for each way a download can be wrong."""
    for folder in "abc":
        (tmp_path / folder).mkdir()

    garbage = tmp_path / "garbage" / ZIP
    garbage.parent.mkdir()
    garbage.write_bytes(b"PK\x03\x04 not really a zip")

    return {
        "missing": tmp_path / "nothing" / ZIP,
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


def remote_for(data, md5=None, url="http://127.0.0.1:1/never", size=None):
    import hashlib

    return RemoteFile(
        name=ZIP, size=len(data) if size is None else size, md5=md5 or hashlib.md5(data).hexdigest(), url=url
    )


def test_there_must_be_room_for_the_unpacked_installer_and_the_game(paths, monkeypatch):
    monkeypatch.setattr(aotr_module.shutil, "disk_usage", lambda path: Usage(0, 0, 2_700_000_000))
    remote = remote_for(b"", size=1_000_000_000)

    AOTR.check_space(context(paths), remote)  # 1 GB unpacked + 1.5 GB installed

    monkeypatch.setattr(aotr_module.shutil, "disk_usage", lambda path: Usage(0, 0, 2_000_000_000))

    with pytest.raises(
        SetupError, match="^Not enough free space: Age of the Ring needs 3 GB more, but only 2 GB is free.$"
    ):
        AOTR.check_space(context(paths), remote)


def test_keeping_the_download_needs_room_for_it_too(paths, monkeypatch):
    monkeypatch.setattr(aotr_module.shutil, "disk_usage", lambda path: Usage(0, 0, 3_000_000_000))
    remote = remote_for(b"", size=1_000_000_000)

    AOTR.check_space(context(paths), remote)

    with pytest.raises(SetupError, match="needs 4 GB more"):
        AOTR.check_space(context(paths, config=Config(keep_aotr_download=True)), remote)


def test_what_is_already_downloaded_unpacked_or_installed_counts(paths, monkeypatch):
    # 1000 zip + 1500 installed = 2500 needed, of which 400 downloaded + 600 unpacked + 500 installed is already there.
    monkeypatch.setattr(aotr_module.shutil, "disk_usage", lambda path: Usage(0, 0, 1000))
    paths.downloads.mkdir(parents=True)
    (paths.downloads / (ZIP + ".part")).write_bytes(b"x" * 400)
    AOTR.unpack_dir(paths).mkdir(parents=True)
    (AOTR.unpack_dir(paths) / "part.bin").write_bytes(b"x" * 600)
    AOTR.exe(paths).parent.mkdir(parents=True)
    (AOTR.exe(paths).parent / "game.big").write_bytes(b"x" * 500)

    AOTR.check_space(context(paths), remote_for(b"", size=1000))

    with pytest.raises(SetupError, match="Not enough free space"):
        AOTR.check_space(context(paths), remote_for(b"", size=1100))


# Unpacking


@needs_7zip
def test_unpacking_checks_the_zip_and_reports_progress(tmp_path, paths):
    events = []

    contents = AOTR.unpack(context(paths, events.append), make_zip(tmp_path, GOOD))

    assert contents.exe_name == EXE
    assert progress(events)[-1] == 100
    assert (AOTR.unpack_dir(paths) / EXE).read_bytes() == b"installer"
    assert (AOTR.unpack_dir(paths) / ".complete").read_text() == ZIP + "\n"


@needs_7zip
def test_a_bad_zip_is_not_unpacked(tmp_path, paths):
    with pytest.raises(SetupError, match="installer program is missing"):
        AOTR.unpack(context(paths), make_zip(tmp_path, {"readme.txt": b"x"}))

    assert not AOTR.unpack_dir(paths).exists()


@needs_7zip
def test_what_an_earlier_unpack_left_is_cleared_first(tmp_path, paths):
    AOTR.unpack_dir(paths).mkdir(parents=True)
    (AOTR.unpack_dir(paths) / "stale.bin").write_bytes(b"old")
    (AOTR.unpack_dir(paths) / ".complete").write_text("AotR_Standalone_9.2.0_Installer.zip\n")

    AOTR.unpack(context(paths), make_zip(tmp_path, GOOD))

    assert not (AOTR.unpack_dir(paths) / "stale.bin").exists()
    assert (AOTR.unpack_dir(paths) / EXE).exists()


# A 7-Zip whose listing shows a good zip, and that does `unpack` (its "x" command) as told.
FAKE_7ZIP = f"""#!/bin/sh
if [ "$1" = l ]; then
  printf 'Path = {EXE}\\nSize = 50\\n\\nPath = AotR_Standalone_9.3.0_Installer-1a.bin\\nSize = 50\\n'
  exit 0
fi
"""


def test_a_failed_unpack_says_where_to_look(tmp_path, paths, monkeypatch):
    executable(tmp_path / "bin" / "7zz", FAKE_7ZIP + "echo 'CRC Failed' >&2\nexit 2\n")
    (tmp_path / ZIP).write_bytes(b"zip")
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))

    with pytest.raises(
        SetupError, match="The file could not be unpacked. It may be damaged. Try again.* See .*aotr-unpack.log"
    ):
        AOTR.unpack(context(paths), tmp_path / ZIP)

    assert not (AOTR.unpack_dir(paths) / ".complete").exists()
    assert "CRC Failed" in (paths.logs / "aotr-unpack.log").read_text()


def test_unpacking_stops_when_cancelled(tmp_path, paths, monkeypatch):
    executable(tmp_path / "bin" / "7zz", FAKE_7ZIP + "exec /bin/sleep 30\n")
    (tmp_path / ZIP).write_bytes(b"zip")
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    cancel = threading.Event()
    threading.Timer(0.2, cancel.set).start()

    with pytest.raises(JobCancelled):
        AOTR.unpack(context(paths, cancel=cancel), tmp_path / ZIP)

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
    return ZipContents(EXE, 100)


def test_the_installer_runs_silently_in_the_unpack_folder(env, paths):
    make_prefix(paths)
    events = []

    AOTR.run_installer(context(paths, events.append, proton="fake-proton"), unpacked(paths))

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
        AOTR.run_installer(context(paths, [].append, proton="fake-proton"), unpacked(paths))

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
        AOTR.run_installer(context(paths, [].append, cancel, proton=str(tmp_path / "proton")), unpacked(paths))

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

    GameEnvironment(paths).prepare(context(paths, [].append, config=Config()))
    contents = AOTR.unpack(context(paths, [].append), zip_path)
    AOTR.run_installer(context(paths, [].append, proton="fake-proton"), contents)
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


def test_the_download_is_checked_against_moddbs_md5(paths, moddb):
    data = os.urandom(8192)
    moddb.publish(data, name=ZIP)
    events = []

    zip_path = AOTR.download_zip(context(paths, events.append, config=Config()), ModDB().find())

    assert zip_path == paths.downloads / ZIP
    assert zip_path.read_bytes() == data
    assert progress(events)[-1] == 100


def test_a_download_with_the_wrong_md5_is_deleted(paths, moddb):
    moddb.publish(b"what was uploaded", name=ZIP, md5="0" * 32)

    with pytest.raises(SetupError, match="Checksum mismatch"):
        AOTR.download_zip(context(paths, [].append, config=Config()), ModDB().find())

    assert not (paths.downloads / ZIP).exists()


def test_a_finished_download_is_not_repeated(paths):
    data = b"already here"
    paths.downloads.mkdir(parents=True)
    (paths.downloads / ZIP).write_bytes(data)

    assert AOTR.download_zip(context(paths, [].append, config=Config()), remote_for(data)) == paths.downloads / ZIP


def test_an_unpacked_installer_of_the_same_zip_is_used_again(paths):
    remote = remote_for(b"")
    assert AOTR.from_unpacked(paths, remote) is None
    unpacked(paths)
    (AOTR.unpack_dir(paths) / "AotR_Standalone_9.3.0_Installer-1a.bin").write_bytes(b"x" * 10)

    assert AOTR.from_unpacked(paths, remote) is None  # its unpack did not finish
    (AOTR.unpack_dir(paths) / ".complete").write_text(ZIP + "\n")
    found = AOTR.from_unpacked(paths, remote)

    assert (found.exe_name, found.unpacked_bytes) == (EXE, len("installer") + 10 + len(ZIP) + 1)
    newer = RemoteFile("AotR_Standalone_10.1.0_Installer.zip", remote.size, remote.md5, remote.url)
    assert AOTR.from_unpacked(paths, newer) is None
