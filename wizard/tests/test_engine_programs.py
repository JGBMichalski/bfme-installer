"""engine.programs: installing, updating and removing the programs, and the status report."""
import hashlib
import os
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from bfme_wizard.engine import download as download_module
from bfme_wizard.engine import programs
from bfme_wizard.engine.config import Config
from bfme_wizard.engine.errors import JobCancelled, SetupError
from bfme_wizard.engine.events import Log, Warn
from bfme_wizard.engine.paths import Paths

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "bfme-linux-setup.sh"
# The setup script calls the AIO Launcher "launcher".
SCRIPT_NAME = {"aio-launcher": "launcher"}
ENGINE_NAME = {"launcher": "aio-launcher"}


def executable(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)


@pytest.fixture
def paths(tmp_path):
    return Paths(tmp_path / "data")


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(programs, "POLL_SEC", 0.05)
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


# The status report, compared with the script's

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


def build(paths, parts):
    for part in parts:
        if part == "prefix":
            make_prefix(paths)
        elif part == "aio-launcher":
            put(paths.aio_launcher_exe)
        elif part == "aio-launcher-marker":
            put(paths.prefix / programs.AIO_LAUNCHER_INSTALLING)
        elif part == "arena":
            put(paths.arena_exe)
        elif part == "aotr":
            put(paths.aotr_exe)
        elif part == "aotr-marker":
            put(paths.prefix / programs.AOTR_INSTALLING)
        elif part in programs.TOOLS:
            put(paths.tool_exe(part))
        elif part in programs.GAME_EXES:
            put(paths.drive_c / programs.GAME_EXES[part])
        elif part == "bfme2-folder":
            (paths.drive_c / "BFME2").mkdir(parents=True)


def script_status(tmp_path, paths):
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "BFME_HOME": str(paths.base)}
    out = subprocess.run([str(SCRIPT), "--machine", "status"], env=env, capture_output=True, text=True, timeout=60).stdout
    found = {}

    for line in out.splitlines():
        if line.startswith("@bfme STATUS "):
            _, _, key, value = line.split(" ", 3)
            found[ENGINE_NAME.get(key, key)] = value

    return found


@pytest.mark.parametrize("layout", LAYOUTS)
def test_the_status_is_the_scripts(tmp_path, paths, layout):
    build(paths, LAYOUTS[layout])

    from_engine = programs.status(paths, Config())

    assert from_engine == script_status(tmp_path, paths)
    assert list(from_engine) == list(script_status(tmp_path, paths))


# Waiting for a file

def test_a_file_that_stops_growing_is_done(tmp_path):
    path = tmp_path / "f"
    timer = threading.Timer(0.1, put, [path])
    timer.start()

    assert programs.wait_for_stable_file(path, 5)


def test_an_empty_or_missing_file_is_never_done(tmp_path):
    (tmp_path / "empty").touch()

    assert not programs.wait_for_stable_file(tmp_path / "empty", 0.3)
    assert not programs.wait_for_stable_file(tmp_path / "missing", 0.3)


def test_waiting_stops_when_cancelled(tmp_path):
    cancel = threading.Event()
    cancel.set()

    with pytest.raises(JobCancelled):
        programs.wait_for_stable_file(tmp_path / "f", 5, cancel)


# The AIO Launcher

# The setup writes the AIO Launcher, then keeps running like Proton does until the Wine session ends. The fake wineserver
# ends it, as the real one would.
FAKE_UMU = r"""#!/bin/sh
printf '%s|%s\n' "$*" "${PROTON_VERB:-}" >> "$UMU_LOG"
[ -n "$NO_INSTALL" ] || { mkdir -p "$(dirname "$AIO_LAUNCHER_EXE")"; printf 'launcher' > "$AIO_LAUNCHER_EXE"; }
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
    monkeypatch.setenv("AIO_LAUNCHER_EXE", str(paths.aio_launcher_exe))
    file_server.files["/setup.exe"] = b"setup"
    make_prefix(paths)
    return {"proton": str(tmp_path / "proton"), "url": file_server.url("/setup.exe"), "tmp": tmp_path}


def test_the_aio_launcher_setup_runs_once_and_the_session_is_ended(paths, aio_launcher_env):
    events = []

    programs.install_aio_launcher(paths, Config(), aio_launcher_env["proton"], events.append, url=aio_launcher_env["url"])

    tmp = aio_launcher_env["tmp"]
    setup = paths.downloads / "AllInOneLauncherSetup.exe"
    assert programs.aio_launcher_installed(paths)
    assert (tmp / "umu.log").read_text() == f"{setup}|\n"      # the first start is not runinprefix
    assert (tmp / "wineserver.log").read_text() == "-k\n-w\n"
    assert not setup.exists()
    assert (paths.logs / "launcher-setup.log").exists()
    assert logs(events) == ["Installing the AIO Launcher. It may open for a moment; the setup closes it again."]


def test_an_installed_aio_launcher_is_left_alone(paths, aio_launcher_env, file_server):
    put(paths.aio_launcher_exe)

    programs.install_aio_launcher(paths, Config(), aio_launcher_env["proton"], [].append, url=aio_launcher_env["url"])

    assert file_server.requests == []
    assert not (aio_launcher_env["tmp"] / "umu.log").exists()


def test_an_interrupted_install_is_redone_with_the_setup_already_downloaded(paths, aio_launcher_env, file_server):
    put(paths.aio_launcher_exe, "half")
    put(paths.prefix / programs.AIO_LAUNCHER_INSTALLING)
    put(paths.downloads / "AllInOneLauncherSetup.exe", "setup")

    programs.install_aio_launcher(paths, Config(), aio_launcher_env["proton"], [].append, url=aio_launcher_env["url"])

    assert file_server.requests == []
    assert paths.aio_launcher_exe.read_text() == "launcher"
    assert programs.aio_launcher_installed(paths)


def test_a_setup_that_installs_nothing_fails_and_stays_unfinished(paths, aio_launcher_env, monkeypatch):
    monkeypatch.setenv("NO_INSTALL", "1")
    monkeypatch.setattr(programs, "AIO_LAUNCHER_WAIT_SEC", 0.3)

    with pytest.raises(SetupError, match="The AIO Launcher was not installed. See .*launcher-setup.log"):
        programs.install_aio_launcher(paths, Config(), aio_launcher_env["proton"], [].append, url=aio_launcher_env["url"])

    assert (paths.prefix / programs.AIO_LAUNCHER_INSTALLING).exists()
    assert (aio_launcher_env["tmp"] / "wineserver.log").read_text() == "-k\n-w\n"


def test_without_a_wine_server_it_warns(paths, aio_launcher_env, tmp_path):
    os.remove(tmp_path / "proton/files/bin/wineserver")
    executable(tmp_path / "bin" / "umu-run", "#!/bin/sh\nmkdir -p \"$(dirname \"$AIO_LAUNCHER_EXE\")\"; echo x > \"$AIO_LAUNCHER_EXE\"\n")
    events = []

    programs.install_aio_launcher(paths, Config(), aio_launcher_env["proton"], events.append, url=aio_launcher_env["url"])

    assert Warn("Could not find the Wine server. Close the AIO Launcher window to let the setup carry on.") in events


# The Arena

ARENA = b"arena build"
ARENA_MD5 = hashlib.md5(ARENA).hexdigest()
HASH_PATH = "/api/applications/versionHash?name=online-arena&version=main"
BUILD_PATH = "/application-builds/online-arena-main"


@pytest.fixture
def arena_server(file_server):
    file_server.files[HASH_PATH] = ARENA_MD5.encode()
    file_server.files[BUILD_PATH] = ARENA
    host = file_server.url("")
    return file_server, host


def install_arena(paths, host, events=None):
    programs.install_or_update_arena(paths, (events if events is not None else []).append, files_host=host, server_host=host)


def test_a_missing_arena_is_downloaded_and_checked(paths, arena_server):
    _, host = arena_server
    events = []

    install_arena(paths, host, events)

    assert paths.arena_exe.read_bytes() == ARENA
    assert os.access(paths.arena_exe, os.X_OK)
    assert (paths.arena_exe.parent / "Data").is_dir()
    assert logs(events) == ["The Arena is not installed yet."]


def test_an_up_to_date_arena_is_not_downloaded(paths, arena_server):
    server, host = arena_server
    put(paths.arena_exe, ARENA.decode())

    install_arena(paths, host)

    assert [path for path, _ in server.requests] == [HASH_PATH]


def test_a_newer_arena_replaces_the_old_one(paths, arena_server):
    _, host = arena_server
    put(paths.arena_exe, "old build")
    events = []

    install_arena(paths, host, events)

    assert paths.arena_exe.read_bytes() == ARENA
    assert logs(events) == ["A new Arena version is available."]


def test_without_the_server_an_installed_arena_is_kept(paths, arena_server):
    server, host = arena_server
    del server.files[HASH_PATH]
    put(paths.arena_exe, "old build")
    events = []

    install_arena(paths, host, events)

    assert paths.arena_exe.read_text() == "old build"
    assert events == [Warn("Could not check for Arena updates. Starting the installed version.")]


def test_without_the_hash_a_missing_arena_is_downloaded_unchecked(paths, arena_server):
    server, host = arena_server
    del server.files[HASH_PATH]

    install_arena(paths, host)

    assert paths.arena_exe.read_bytes() == ARENA


def test_a_download_with_the_wrong_checksum_keeps_the_old_arena(paths, arena_server):
    server, host = arena_server
    server.files[HASH_PATH] = b"0" * 32
    put(paths.arena_exe, "old build")

    with pytest.raises(SetupError, match=f"Arena download failed its checksum check \\(expected {'0' * 32}, got {ARENA_MD5}\\)."):
        install_arena(paths, host)

    assert paths.arena_exe.read_text() == "old build"
    assert not (paths.downloads / "OnlineArena.exe").exists()


# The tools

@pytest.mark.parametrize("tool", programs.TOOLS)
def test_a_tool_is_downloaded_into_its_folder(paths, file_server, tool):
    file_server.files["/tool.exe"] = b"tool"

    programs.install_tool(paths, tool, url=file_server.url("/tool.exe"))

    assert paths.tool_exe(tool).read_bytes() == b"tool"
    assert os.access(paths.tool_exe(tool), os.X_OK)
    assert programs.tool_installed(paths, tool)


# Removing, compared with the script's

def everything(paths):
    """Every program, the games, a player's settings and what interrupted installs leave behind."""
    make_prefix(paths)

    for part in ("aio-launcher", "arena", "aotr", "workshop", "mission-control", "bfme2", "aio-launcher-marker", "aotr-marker"):
        build(paths, [part])

    put(paths.drive_c / "users/steamuser/AppData/Roaming/Age of the Ring/Options.ini")
    put(paths.downloads / "AllInOneLauncherSetup.exe")
    put(paths.downloads / "AllInOneLauncherSetup.exe.part")
    put(paths.downloads / "OnlineArena.exe.part")
    put(paths.aotr_unpack / "setup.exe")
    put(paths.downloads / "other.zip")


def tree(paths):
    """Every file and folder under the data folder, without the logs, the lock and the script's own menu shortcut files
    (shortcuts are a later step)."""
    found = set()

    for path in paths.base.rglob("*"):
        relative = str(path.relative_to(paths.base))

        if not relative.startswith(("logs", ".setup.lock", "bin", "icons")):
            found.add(relative)

    return found


@pytest.mark.parametrize("program", [*programs.PROGRAMS, *programs.TOOLS])
def test_removing_is_the_scripts(tmp_path, paths, program):
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "BFME_HOME": str(paths.base)}
    everything(paths)
    done = subprocess.run([str(SCRIPT), "remove", SCRIPT_NAME.get(program, program)], env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    from_script = tree(paths)
    script_said = done.stdout.splitlines()[-1]

    for path in sorted(paths.base.iterdir()):
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()

    everything(paths)
    events = []
    programs.remove(paths, Config(), program, events.append)

    assert tree(paths) == from_script
    assert logs(events) == [script_said]
    assert not programs.installed(paths, program)


def test_an_unknown_program_is_refused(paths):
    with pytest.raises(SetupError, match="Use: remove aio-launcher|arena|aotr|workshop|mission-control"):
        programs.remove(paths, Config(), "bfme2", [].append)
