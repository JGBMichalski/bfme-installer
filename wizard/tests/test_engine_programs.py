"""engine.programs: installing, updating and removing the programs, and the status report."""

import hashlib
import os
import threading

import pytest

from bfme_wizard.engine import download as download_module
from bfme_wizard.engine import jobs
from bfme_wizard.engine.config import Config
from bfme_wizard.engine.errors import JobCancelled, SetupError
from bfme_wizard.engine.events import Log, Warn
from bfme_wizard.engine.jobs import StatusJob
from bfme_wizard.engine.paths import Paths
from bfme_wizard.engine.programs import AIO_LAUNCHER, AOTR, ARENA, TOOLS, AioLauncher, program


def executable(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)


@pytest.fixture
def paths(tmp_path):
    return Paths(tmp_path / "data")


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(AioLauncher, "POLL_SEC", 0.05)
    monkeypatch.setattr(download_module, "RETRY_DELAY_SEC", 0)


def make_prefix(paths):
    for folder in ("windows", "users/steamuser"):
        (paths.drive_c / folder).mkdir(parents=True, exist_ok=True)


def put(path, text="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def logs(events):
    out = []

    for event in events:
        if isinstance(event, Log):
            out.append(event.text)

    return out


# The status report

LAYOUTS = {
    "nothing": [],
    "prefix only": ["prefix"],
    "aio-launcher": ["prefix", "aio-launcher"],
    "aio-launcher still installing": ["prefix", "aio-launcher", "aio-launcher-marker"],
    "arena only": ["prefix", "arena"],
    "aotr": ["prefix", "aotr"],
    "aotr still installing": ["prefix", "aotr", "aotr-marker"],
    "programs without a prefix": ["aio-launcher", "aotr"],
    "tools only": ["prefix", "workshop", "mission-control"],
    "games": ["prefix", "aio-launcher", "bfme1", "bfme2", "rotwk"],
    "a game folder without its program": ["prefix", "bfme2-folder"],
}

STATUS_KEYS = [
    "runner",
    "graphics",
    "gpu",
    "fps-counter",
    "graphics-cards",
    "prefix",
    "aio-launcher",
    "arena",
    "aotr",
    "workshop",
    "mission-control",
    "bfme1",
    "bfme2",
    "rotwk",
    "complete",
]

# What differs, per layout, from a status where nothing is there. An unfinished install counts as missing, and only a
# prefix with a launcher or AotR in it is complete.
STATUS_CHANGES = {
    "nothing": {},
    "prefix only": {"prefix": "ready"},
    "aio-launcher": {"prefix": "ready", "aio-launcher": "installed", "complete": "yes"},
    "aio-launcher still installing": {"prefix": "ready"},
    "arena only": {"prefix": "ready", "arena": "installed", "complete": "yes"},
    "aotr": {"prefix": "ready", "aotr": "installed", "complete": "yes"},
    "aotr still installing": {"prefix": "ready"},
    "programs without a prefix": {"aio-launcher": "installed", "aotr": "installed"},
    "tools only": {"prefix": "ready", "workshop": "installed", "mission-control": "installed"},
    "games": {
        "prefix": "ready",
        "aio-launcher": "installed",
        "bfme1": "installed",
        "bfme2": "installed",
        "rotwk": "installed",
        "complete": "yes",
    },
    "a game folder without its program": {"prefix": "ready"},
}

TOOL_KEYS = [tool.key for tool in TOOLS]


def build(paths, parts):
    for part in parts:
        if part == "prefix":
            make_prefix(paths)
        elif part == "aio-launcher":
            put(AIO_LAUNCHER.exe(paths))
        elif part == "aio-launcher-marker":
            put(paths.prefix / AIO_LAUNCHER.INSTALLING)
        elif part == "arena":
            put(ARENA.exe(paths))
        elif part == "aotr":
            put(AOTR.exe(paths))
        elif part == "aotr-marker":
            put(paths.prefix / AOTR.INSTALLING)
        elif part in TOOL_KEYS:
            put(program(part).exe(paths))
        elif part in jobs.GAME_EXES:
            put(paths.drive_c / jobs.GAME_EXES[part])
        elif part == "bfme2-folder":
            (paths.drive_c / "BFME2").mkdir(parents=True)


@pytest.mark.parametrize("layout", LAYOUTS)
def test_the_status_of_each_layout(paths, layout, tmp_path, monkeypatch):
    # One graphics card, whatever computer runs the test.
    executable(tmp_path / "bin" / "lspci", "#!/bin/sh\necho '00:02.0 VGA compatible controller: Intel'\n")
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:/usr/bin:/bin")
    build(paths, LAYOUTS[layout])

    expected = {
        "runner": "proton",
        "graphics": "vulkan",
        "gpu": "auto",
        "fps-counter": "0",
        "graphics-cards": "1",
        "prefix": "missing",
        "aio-launcher": "missing",
        "arena": "missing",
        "aotr": "missing",
        "workshop": "missing",
        "mission-control": "missing",
        "bfme1": "missing",
        "bfme2": "missing",
        "rotwk": "missing",
        "complete": "no",
    }
    expected.update(STATUS_CHANGES[layout])

    found = StatusJob([].append, environ={"BFME_HOME": str(paths.base)}).setup_status()

    assert found == expected
    assert list(found) == STATUS_KEYS


# Waiting for a file


def test_a_file_that_stops_growing_is_done(tmp_path):
    path = tmp_path / "f"
    timer = threading.Timer(0.1, put, [path])
    timer.start()

    assert AIO_LAUNCHER.wait_for_stable_file(path, 5)


def test_an_empty_or_missing_file_is_never_done(tmp_path):
    (tmp_path / "empty").touch()

    assert not AIO_LAUNCHER.wait_for_stable_file(tmp_path / "empty", 0.3)
    assert not AIO_LAUNCHER.wait_for_stable_file(tmp_path / "missing", 0.3)


def test_waiting_stops_when_cancelled(tmp_path):
    cancel = threading.Event()
    cancel.set()

    with pytest.raises(JobCancelled):
        AIO_LAUNCHER.wait_for_stable_file(tmp_path / "f", 5, cancel)


# The AIO Launcher

# The setup writes the AIO Launcher, then keeps running like Proton does until the Wine session ends. The fake wineserver
# ends it, as the real one would.
FAKE_UMU = r"""#!/bin/sh
printf '%s|%s\n' "$*" "${PROTON_VERB:-}" >> "$UMU_LOG"
[ -n "$NO_INSTALL" ] || { mkdir -p "$(dirname "$AIO_LAUNCHER_EXE")"; printf 'aio-launcher' > "$AIO_LAUNCHER_EXE"; }
sleep 30 &
echo $! > "$SESSION_PID"
wait
"""
FAKE_WINESERVER = r"""#!/bin/sh
echo "$*" >> "$WINESERVER_LOG"
[ "$1" = "-k" ] && kill "$(cat "$SESSION_PID")" 2>/dev/null
exit 0
"""


@pytest.fixture
def aio_launcher_env(tmp_path, paths, monkeypatch, file_server):
    executable(tmp_path / "bin" / "umu-run", FAKE_UMU)
    executable(tmp_path / "bin" / "lspci", "#!/bin/sh\n")
    executable(tmp_path / "proton/files/bin/wineserver", FAKE_WINESERVER)
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:/usr/bin:/bin")
    monkeypatch.setenv("UMU_LOG", str(tmp_path / "umu.log"))
    monkeypatch.setenv("WINESERVER_LOG", str(tmp_path / "wineserver.log"))
    monkeypatch.setenv("SESSION_PID", str(tmp_path / "session.pid"))
    monkeypatch.setenv("AIO_LAUNCHER_EXE", str(AIO_LAUNCHER.exe(paths)))
    file_server.files["/setup.exe"] = b"setup"
    make_prefix(paths)
    return {"proton": str(tmp_path / "proton"), "url": file_server.url("/setup.exe"), "tmp": tmp_path}


def test_the_aio_launcher_setup_runs_once_and_the_session_is_ended(paths, aio_launcher_env):
    events = []

    AIO_LAUNCHER.install(paths, Config(), aio_launcher_env["proton"], events.append, url=aio_launcher_env["url"])

    tmp = aio_launcher_env["tmp"]
    setup = paths.downloads / "AllInOneLauncherSetup.exe"
    assert AIO_LAUNCHER.installed(paths)
    assert (tmp / "umu.log").read_text() == f"{setup}|\n"  # the first start is not runinprefix
    assert (tmp / "wineserver.log").read_text() == "-k\n-w\n"
    assert not setup.exists()
    assert (paths.logs / "aio-launcher-setup.log").exists()
    assert logs(events) == [
        "Downloading AllInOneLauncherSetup.exe.",
        "Installing the AIO Launcher. It may open for a moment; the setup closes it again.",
    ]


def test_an_installed_aio_launcher_is_left_alone(paths, aio_launcher_env, file_server):
    put(AIO_LAUNCHER.exe(paths))

    AIO_LAUNCHER.install(paths, Config(), aio_launcher_env["proton"], [].append, url=aio_launcher_env["url"])

    assert file_server.requests == []
    assert not (aio_launcher_env["tmp"] / "umu.log").exists()


def test_an_interrupted_install_is_redone_with_the_setup_already_downloaded(paths, aio_launcher_env, file_server):
    put(AIO_LAUNCHER.exe(paths), "half")
    put(paths.prefix / AIO_LAUNCHER.INSTALLING)
    put(paths.downloads / "AllInOneLauncherSetup.exe", "setup")

    AIO_LAUNCHER.install(paths, Config(), aio_launcher_env["proton"], [].append, url=aio_launcher_env["url"])

    assert file_server.requests == []
    assert AIO_LAUNCHER.exe(paths).read_text() == "aio-launcher"
    assert AIO_LAUNCHER.installed(paths)


def test_a_setup_that_installs_nothing_fails_and_stays_unfinished(paths, aio_launcher_env, monkeypatch):
    monkeypatch.setenv("NO_INSTALL", "1")
    monkeypatch.setattr(AioLauncher, "WAIT_SEC", 0.3)

    with pytest.raises(SetupError, match="The AIO Launcher was not installed. See .*aio-launcher-setup.log"):
        AIO_LAUNCHER.install(paths, Config(), aio_launcher_env["proton"], [].append, url=aio_launcher_env["url"])

    assert (paths.prefix / AIO_LAUNCHER.INSTALLING).exists()
    assert (aio_launcher_env["tmp"] / "wineserver.log").read_text() == "-k\n-w\n"


def test_without_a_wine_server_it_warns(paths, aio_launcher_env, tmp_path):
    os.remove(tmp_path / "proton/files/bin/wineserver")
    executable(
        tmp_path / "bin" / "umu-run",
        '#!/bin/sh\nmkdir -p "$(dirname "$AIO_LAUNCHER_EXE")"; echo x > "$AIO_LAUNCHER_EXE"\n',
    )
    events = []

    AIO_LAUNCHER.install(paths, Config(), aio_launcher_env["proton"], events.append, url=aio_launcher_env["url"])

    assert (
        Warn(
            "Could not find the Wine server to close the programs in the game environment. Close any that are still open."
        )
        in events
    )


# The Arena

ARENA_BUILD = b"arena build"
ARENA_MD5 = hashlib.md5(ARENA_BUILD).hexdigest()
HASH_PATH = "/api/applications/versionHash?name=online-arena&version=main"
BUILD_PATH = "/application-builds/online-arena-main"


@pytest.fixture
def arena_server(file_server):
    file_server.files[HASH_PATH] = ARENA_MD5.encode()
    file_server.files[BUILD_PATH] = ARENA_BUILD
    host = file_server.url("")
    return file_server, host


def install_arena(paths, host, events=None):
    ARENA.update(paths, (events if events is not None else []).append, files_host=host, server_host=host)


def test_a_missing_arena_is_downloaded_and_checked(paths, arena_server):
    _, host = arena_server
    events = []

    install_arena(paths, host, events)

    assert ARENA.exe(paths).read_bytes() == ARENA_BUILD
    assert os.access(ARENA.exe(paths), os.X_OK)
    assert (ARENA.exe(paths).parent / "Data").is_dir()
    assert logs(events) == ["The Arena is not installed yet.", "Downloading OnlineArena.exe."]


def test_an_up_to_date_arena_is_not_downloaded(paths, arena_server):
    server, host = arena_server
    put(ARENA.exe(paths), ARENA_BUILD.decode())

    install_arena(paths, host)

    assert [path for path, _ in server.requests] == [HASH_PATH]


def test_a_newer_arena_replaces_the_old_one(paths, arena_server):
    _, host = arena_server
    put(ARENA.exe(paths), "old build")
    events = []

    install_arena(paths, host, events)

    assert ARENA.exe(paths).read_bytes() == ARENA_BUILD
    assert logs(events) == ["A new Arena version is available.", "Downloading OnlineArena.exe."]


def test_without_the_server_an_installed_arena_is_kept(paths, arena_server):
    server, host = arena_server
    del server.files[HASH_PATH]
    put(ARENA.exe(paths), "old build")
    events = []

    install_arena(paths, host, events)

    assert ARENA.exe(paths).read_text() == "old build"
    assert events == [Warn("Could not check for Arena updates. Starting the installed version.")]


def test_without_the_hash_a_missing_arena_is_downloaded_unchecked(paths, arena_server):
    server, host = arena_server
    del server.files[HASH_PATH]

    install_arena(paths, host)

    assert ARENA.exe(paths).read_bytes() == ARENA_BUILD


def test_a_download_with_the_wrong_checksum_keeps_the_old_arena(paths, arena_server):
    server, host = arena_server
    server.files[HASH_PATH] = b"0" * 32
    put(ARENA.exe(paths), "old build")

    with pytest.raises(
        SetupError, match=f"Arena download failed its checksum check \\(expected {'0' * 32}, got {ARENA_MD5}\\)."
    ):
        install_arena(paths, host)

    assert ARENA.exe(paths).read_text() == "old build"
    assert not (paths.downloads / "OnlineArena.exe").exists()


# The tools


@pytest.mark.parametrize("tool", TOOL_KEYS)
def test_a_tool_is_downloaded_into_its_folder(paths, file_server, tool):
    file_server.files["/tool.exe"] = b"tool"

    program(tool).install(paths, [].append, url=file_server.url("/tool.exe"))

    assert program(tool).exe(paths).read_bytes() == b"tool"
    assert os.access(program(tool).exe(paths), os.X_OK)
    assert program(tool).installed(paths)


# Removing


def everything(paths):
    """Every program, the games, a player's settings and what interrupted installs leave behind."""
    make_prefix(paths)

    for part in (
        "aio-launcher",
        "arena",
        "aotr",
        "workshop",
        "mission-control",
        "bfme2",
        "aio-launcher-marker",
        "aotr-marker",
    ):
        build(paths, [part])

    put(paths.drive_c / "users/steamuser/AppData/Roaming/Age of the Ring/Options.ini")
    put(paths.downloads / "AllInOneLauncherSetup.exe")
    put(paths.downloads / "AllInOneLauncherSetup.exe.part")
    put(paths.downloads / "OnlineArena.exe.part")
    put(AOTR.unpack_dir(paths) / "setup.exe")
    put(paths.downloads / "other.zip")


def tree(paths):
    """Every file and folder under the data folder, without the logs, the lock and the menu shortcut files
    (shortcuts are a later step)."""
    found = set()

    for path in paths.base.rglob("*"):
        relative = str(path.relative_to(paths.base))

        if not relative.startswith(("logs", ".setup.lock", "bin", "icons")):
            found.add(relative)

    return found


ROAMING = "prefix/drive_c/users/steamuser/AppData/Roaming"

# Per program: what removing it says, and every path it takes away. Everything else stays, the player's AotR settings
# and other downloads included.
REMOVED = {
    "aio-launcher": (
        "Removed the AIO Launcher.",
        {
            "downloads/AllInOneLauncherSetup.exe",
            "downloads/AllInOneLauncherSetup.exe.part",
            "prefix/.bfme-aio-launcher-installing",
            f"{ROAMING}/BFME All In One Launcher",
            f"{ROAMING}/BFME All In One Launcher/AllInOneLauncher.exe",
        },
    ),
    "arena": (
        "Removed the Arena.",
        {
            "downloads/OnlineArena.exe.part",
            f"{ROAMING}/BFME Competetive Arena",
            f"{ROAMING}/BFME Competetive Arena/BfmeFoundationProject_OnlineArena.exe",
        },
    ),
    "aotr": (
        "Removed Age of the Ring.",
        {
            "downloads/aotr",
            "downloads/aotr/setup.exe",
            "prefix/.bfme-aotr-installing",
            "prefix/drive_c/AgeoftheRing",
            "prefix/drive_c/AgeoftheRing/AotR_Launcher.exe",
        },
    ),
    "workshop": (
        "Removed Workshop Studio.",
        {
            "prefix/drive_c/BFME Tools/Workshop Studio",
            "prefix/drive_c/BFME Tools/Workshop Studio/WorkshopStudio.exe",
        },
    ),
    "mission-control": (
        "Removed Mission Control.",
        {
            "prefix/drive_c/BFME Tools/Mission Control",
            "prefix/drive_c/BFME Tools/Mission Control/MissionControl.exe",
        },
    ),
}


@pytest.mark.parametrize("key", list(REMOVED))
def test_removing_takes_away_only_the_programs_files(paths, key):
    message, gone = REMOVED[key]
    everything(paths)
    before = tree(paths)
    assert gone <= before

    events = []
    program(key).remove(paths, Config(), events.append)

    assert tree(paths) == before - gone
    assert logs(events) == [message]
    assert not program(key).installed(paths)


def test_an_unknown_program_is_refused(paths):
    with pytest.raises(SetupError, match="Unknown program: bfme2."):
        program("bfme2").remove(paths, Config(), [].append)


def test_the_arena_update_check_names_the_app_not_python(paths, arena_server):
    server, host = arena_server
    put(ARENA.exe(paths), ARENA_BUILD.decode())

    install_arena(paths, host)

    assert server.agents == ["bfme-installer"]


def test_a_tool_download_says_so(paths, file_server):
    file_server.files["/tool.exe"] = b"tool"
    events = []

    program("workshop").install(paths, events.append, url=file_server.url("/tool.exe"))

    assert logs(events) == ["Downloading WorkshopStudio.exe."]
