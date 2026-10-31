"""engine.jobs: each job's events, written out as status lines."""
import hashlib
import shutil
import subprocess
import threading
from pathlib import Path

import pytest
from bfme_wizard.engine import aotr, download, doctor, graphics, jobs, programs, shortcuts
from bfme_wizard.engine.events import (
    Cancelled,
    Check,
    Done,
    Error,
    Fix,
    Log,
    Progress,
    Speed,
    Status,
    Step,
    Warn,
)
from bfme_wizard.engine.lock import setup_lock
from bfme_wizard.engine.paths import Paths

SEVENZIP = shutil.which("7zz") or shutil.which("7z") or shutil.which("7za")
needs_7zip = pytest.mark.skipif(SEVENZIP is None, reason="7-Zip is needed to read the Age of the Ring download")

# Makes the prefix on the first start, and installs the AIO Launcher and Age of the Ring when their installers run.
FAKE_UMU = r"""#!/bin/sh
case "${1:-}" in
  "") mkdir -p "$WINEPREFIX/drive_c/windows" "$WINEPREFIX/drive_c/users/steamuser" ;;
  *AllInOneLauncherSetup.exe)
      d="$WINEPREFIX/drive_c/users/steamuser/AppData/Roaming/BFME All In One Launcher"
      mkdir -p "$d"; printf 'aio-launcher' > "$d/AllInOneLauncher.exe" ;;
  *AotR_Standalone*Installer.exe)
      mkdir -p "$WINEPREFIX/drive_c/AgeoftheRing"; printf 'aotr' > "$WINEPREFIX/drive_c/AgeoftheRing/AotR_Launcher.exe" ;;
esac
echo "umu $*" >> "$UMU_LOG"
exit 0
"""
def executable(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)


class World:
    """Everything a job needs, faked."""

    def __init__(self, tmp_path, monkeypatch, file_server):
        self.tmp = tmp_path
        self.paths = Paths(tmp_path / "data")
        bin_dir = tmp_path / "bin"
        executable(bin_dir / "umu-run", FAKE_UMU)
        executable(bin_dir / "lspci", "#!/bin/sh\n")
        self.home = tmp_path / "home"
        self.env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(self.home), "BFME_HOME": str(self.paths.base),
            "XDG_DATA_HOME": str(tmp_path / "xdg"), "BFME_PROTONPATH": "fake-proton",
            "UMU_LOG": str(tmp_path / "umu.log"),
        }

        for name, value in self.env.items():
            monkeypatch.setenv(name, value)

        monkeypatch.delenv("FLATPAK_ID", raising=False)

        # The downloads come from the local server.
        file_server.files["/setup.exe"] = b"fake-download"
        file_server.files["/tool.exe"] = b"fake-download"
        file_server.files["/api/applications/versionHash?name=online-arena&version=main"] = \
            hashlib.md5(b"arena-binary").hexdigest().encode()
        file_server.files["/application-builds/online-arena-main"] = b"arena-binary"
        monkeypatch.setattr(programs, "AIO_LAUNCHER_URL", file_server.url("/setup.exe"))
        monkeypatch.setattr(programs, "ARENA_FILES_HOST", file_server.url(""))
        monkeypatch.setattr(programs, "ARENA_SERVER_HOST", file_server.url(""))
        monkeypatch.setattr(programs, "TOOL_URLS", {"workshop": file_server.url("/tool.exe"),
                                                    "mission-control": file_server.url("/tool.exe")})

        # The 32-bit extensions are there, the menu folder is shared, and the computer suits Vulkan.
        lib = tmp_path / "lib"
        (lib / "i386-linux-gnu/GL/default").mkdir(parents=True)
        (lib / "i386-linux-gnu/ld-linux.so.2").touch()
        monkeypatch.setattr(doctor, "LIB_ROOT", lib)
        mountinfo = tmp_path / "mountinfo"
        mountinfo.write_text(f"20 1 0:20 / / rw - tmpfs tmpfs rw\n40 20 0:40 / {self.home} rw - ext4 /dev/sda1 rw\n")
        monkeypatch.setattr(shortcuts, "MOUNTINFO", mountinfo)
        monkeypatch.setattr(graphics, "probe", lambda: ("vulkan", "Vulkan 1.4 on Test GPU"))
        monkeypatch.setattr(programs, "POLL_SEC", 0.05)
        monkeypatch.setattr(aotr, "WATCH_SEC", 0.05)
        monkeypatch.setattr(download, "SPEED_INTERVAL_SEC", 0)

    def make_prefix(self):
        for folder in ("windows", "users/steamuser"):
            (self.paths.drive_c / folder).mkdir(parents=True, exist_ok=True)

    def engine(self, job, *args, cancel=None):
        events = []
        code = job(*args, events.append, cancel)
        return code, events


def lines(events):
    """The events as status lines, without PROGRESS."""
    out = []

    for event in events:
        if isinstance(event, Step):
            out.append(f"@bfme STEP {event.id} {event.status}")
        elif isinstance(event, Check):
            out.append(f"@bfme CHECK {event.id} {event.level} {event.message}")
        elif isinstance(event, Fix):
            out.append(f"@bfme FIX {event.check_id} {event.command}")
        elif isinstance(event, Warn):
            out.append(f"@bfme WARN {event.message}")
        elif isinstance(event, Error):
            out.append(f"@bfme ERROR {event.step or '-'} {event.message}")
        elif isinstance(event, Cancelled):
            out.append("@bfme CANCELLED")
        elif isinstance(event, Done):
            out.append("@bfme DONE")
        elif isinstance(event, Status):
            out.append(f"@bfme STATUS {event.key} {event.value}")

    return out


def without_checks(found):
    """The checks depend on the computer (free disk space); they are tested in test_engine_doctor."""
    out = []

    for line in found:
        if not line.startswith(("@bfme CHECK ", "@bfme FIX ")):
            out.append(line)

    return out


@pytest.fixture
def world(tmp_path, monkeypatch, file_server):
    return World(tmp_path, monkeypatch, file_server)


def status_lines(**changed):
    """The STATUS lines every job ends with: nothing installed, unless changed (use _ for -)."""
    values = {
        "runner": "proton", "graphics": "vulkan", "prefix": "ready", "aio-launcher": "missing",
        "arena": "missing", "aotr": "missing", "workshop": "missing", "mission-control": "missing",
        "bfme1": "missing", "bfme2": "missing", "rotwk": "missing", "complete": "no",
    }

    for key, value in changed.items():
        values[key.replace("_", "-")] = value

    out = []

    for key, value in values.items():
        out.append(f"@bfme STATUS {key} {value}")

    return out


NO_WINE_SERVER = "@bfme WARN Could not find the Wine server to close the programs in the game environment. Close any that are still open."


# What is there

def test_status_of_nothing(world):
    code, events = world.engine(jobs.status)

    assert code == jobs.OK
    assert lines(events) == status_lines(prefix="missing")


def test_status_of_a_ready_environment(world):
    world.make_prefix()
    world.paths.aotr_exe.parent.mkdir(parents=True)
    world.paths.aotr_exe.write_text("x")

    code, events = world.engine(jobs.status)

    assert code == jobs.OK
    assert lines(events) == status_lines(aotr="installed", complete="yes")


def test_setup_complete_and_ready_to_open(world):
    assert not jobs.setup_complete()
    world.make_prefix()
    assert not jobs.setup_complete()
    assert not jobs.ready_to_open("aotr")
    world.paths.aotr_exe.parent.mkdir(parents=True)
    world.paths.aotr_exe.write_text("x")
    assert jobs.setup_complete()
    assert jobs.ready_to_open("aotr")
    assert not jobs.ready_to_open("arena")


# Installing

def test_prepare(world):
    code, events = world.engine(jobs.prepare)

    assert code == jobs.OK
    assert without_checks(lines(events)) == [
        "@bfme STEP doctor start",
        "@bfme STEP doctor done",
        "@bfme STEP runner start",
        "@bfme STEP runner done",
        "@bfme STEP prefix start",
        "@bfme STEP prefix done",
        *status_lines(),
        "@bfme DONE",
    ]

    assert Status("prefix", "ready") in events
    assert Log("The game environment is ready.") in events


def test_prepare_stops_at_a_failed_check(world, monkeypatch):
    monkeypatch.setattr(doctor.platform, "machine", lambda: "aarch64")
    code, events = world.engine(jobs.prepare)

    assert code == jobs.FAILED
    assert lines(events)[-1] == "@bfme ERROR doctor Your system needs a change first. Fix the problems above, then try again."
    assert not world.paths.prefix.exists()


def test_the_aio_launcher_and_the_arena(world):
    world.make_prefix()

    code, events = world.engine(jobs.aio_launcher_install)

    assert code == jobs.OK
    assert lines(events) == [
        "@bfme STEP aio-launcher start",
        NO_WINE_SERVER,
        "@bfme STEP aio-launcher done",
        "@bfme STEP arena start",
        "@bfme STEP arena done",
        "@bfme STEP shortcuts start",
        "@bfme STEP shortcuts done",
        *status_lines(aio_launcher="installed", arena="installed", complete="yes"),
        "@bfme DONE",
    ]

    assert Status("aio-launcher", "installed") in events
    assert Status("arena", "installed") in events
    assert (world.home / f".local/share/applications/{shortcuts.RELEASE_APP_ID}.AioLauncher.desktop").is_file()


def test_the_aio_launcher_needs_the_game_environment(world):
    code, events = world.engine(jobs.aio_launcher_install)

    assert code == jobs.FAILED
    assert lines(events) == ["@bfme ERROR - Set up the game environment first."]


@pytest.mark.parametrize("tool", programs.TOOLS)
def test_a_tool(world, tool):
    world.make_prefix()

    code, events = world.engine(jobs.tool_install, tool)

    assert code == jobs.OK
    assert lines(events) == [
        f"@bfme STEP {tool} start",
        f"@bfme STEP {tool} done",
        *status_lines(**{tool: "installed"}),
        "@bfme DONE",
    ]


def test_an_unknown_tool(world):
    world.make_prefix()

    code, events = world.engine(jobs.tool_install, "bogus")

    assert code == jobs.FAILED
    assert lines(events) == ["@bfme ERROR - Unknown tool: bogus."]


def aotr_zip(world, version="10.0.0"):
    """A small Age of the Ring download, made with 7-Zip as the real one would be read."""
    source = world.tmp / f"zip-source-{version}"
    source.mkdir()
    (source / f"AotR_Standalone_{version}_Installer.exe").write_text("installer")
    (source / f"AotR_Standalone_{version}_Installer-1a.bin").write_bytes(b"x" * 2048)
    zip_path = world.tmp / f"AotR_Standalone_{version}_Installer.zip"
    subprocess.run([SEVENZIP, "a", "-tzip", "-bso0", "-bsp0", str(zip_path), "."], cwd=source, check=True)
    return zip_path


@needs_7zip
def test_age_of_the_ring_from_the_players_file(world):
    zip_path = aotr_zip(world)

    world.make_prefix()

    code, events = world.engine(jobs.aotr_install, str(zip_path))

    assert code == jobs.OK
    assert lines(events) == [
        "@bfme STEP aotr-download done",
        "@bfme STEP aotr-check start",
        "@bfme STEP aotr-check done",
        "@bfme STEP aotr-unpack start",
        "@bfme STEP aotr-unpack done",
        "@bfme STEP aotr-install start",
        "@bfme STEP aotr-install done",
        "@bfme STEP aotr-settings start",
        "@bfme STEP aotr-settings done",
        *status_lines(aotr="installed", complete="yes"),
        "@bfme DONE",
    ]
    assert zip_path.exists()                    # the player's own file is never deleted


@needs_7zip
def test_age_of_the_ring_downloaded_by_the_app(world, moddb):
    name = moddb.publish(aotr_zip(world).read_bytes())
    world.make_prefix()

    code, events = world.engine(jobs.aotr_install, None)

    assert code == jobs.OK
    assert lines(events)[:2] == ["@bfme STEP aotr-download start", "@bfme STEP aotr-download done"]
    assert Status("aotr", "installed") in events
    assert not (world.paths.downloads / name).exists()        # deleted once unpacked
    assert any(isinstance(event, Speed) for event in events)   # the download reported its speed
    assert Log("Age of the Ring is installed.") in events


@needs_7zip
def test_the_download_can_be_kept(world, moddb):
    name = moddb.publish(aotr_zip(world).read_bytes())
    world.make_prefix()
    world.paths.config.write_text("BFME_KEEP_AOTR_DOWNLOAD=1\n")

    code, _events = world.engine(jobs.aotr_install, None)

    assert code == jobs.OK
    assert (world.paths.downloads / name).exists()


def test_when_moddb_cannot_be_read_the_player_is_asked_for_the_file(world, moddb):
    moddb.publish(b"x")
    moddb.server.files["/downloads/start/290690"] = b"<html>Please verify you are human</html>"
    world.make_prefix()

    code, events = world.engine(jobs.aotr_install, None)

    assert code == jobs.NEEDS_FILE
    assert events[-1] == Error("aotr-download", "ModDB did not offer a download link. It may want a browser.")
    assert list(world.paths.downloads.glob("*")) == []


@needs_7zip
def test_a_retry_after_a_failed_install_does_not_download_again(world, moddb, monkeypatch):
    moddb.publish(aotr_zip(world).read_bytes())
    world.make_prefix()
    monkeypatch.setenv("NO_INSTALL", "1")
    executable(world.tmp / "bin" / "umu-run", FAKE_UMU.replace('  *AotR_Standalone*Installer.exe)\n',
                                                                 '  *AotR_Standalone*Installer.exe)\n      [ -n "$NO_INSTALL" ] && exit 3\n'))

    code, _events = world.engine(jobs.aotr_install, None)
    assert code == jobs.FAILED
    downloads_before = len(moddb.server.requests)

    monkeypatch.delenv("NO_INSTALL")
    code, events = world.engine(jobs.aotr_install, None)

    assert code == jobs.OK
    assert Step("aotr-unpack", "skip") in events
    mirror_requests = [path for path, _range in moddb.server.requests[downloads_before:] if "/mirror/" in path]
    assert mirror_requests == []


# Changing what is there

@pytest.mark.parametrize("program", ["aio-launcher", "arena", "aotr", "workshop", "mission-control"])
def test_remove(world, program):
    world.make_prefix()

    for exe in (world.paths.aio_launcher_exe, world.paths.arena_exe, world.paths.aotr_exe,
                world.paths.tool_exe("workshop"), world.paths.tool_exe("mission-control")):
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_text("x")

    code, events = world.engine(jobs.remove, program)

    everything_but_this = {
        "aio_launcher": "installed", "arena": "installed", "aotr": "installed", "workshop": "installed",
        "mission_control": "installed", "complete": "yes",
    }
    everything_but_this[program.replace("-", "_")] = "missing"

    assert code == jobs.OK
    assert lines(events) == [
        NO_WINE_SERVER,
        *status_lines(**everything_but_this),
        "@bfme DONE",
    ]


@pytest.mark.parametrize("backend", ["vulkan", "opengl"])
def test_switching_graphics(world, backend):
    world.make_prefix()

    code, events = world.engine(jobs.switch_graphics, backend)

    assert code == jobs.OK
    assert lines(events) == [f"@bfme STATUS graphics {backend}", "@bfme DONE"]


def test_reset(world):
    world.make_prefix()
    world.paths.aotr_exe.parent.mkdir(parents=True)
    world.paths.aotr_exe.write_text("x")

    code, events = world.engine(jobs.reset)

    assert code == jobs.OK
    assert lines(events) == [NO_WINE_SERVER]

    assert not world.paths.prefix.exists()


# What only the engine does

def test_a_stop_takes_effect_before_the_next_step(world):
    cancel = threading.Event()
    cancel.set()

    code, events = world.engine(jobs.prepare, cancel=cancel)

    assert code == jobs.STOPPED
    assert lines(events) == ["@bfme CANCELLED"]


def test_another_setup_holding_the_lock_is_an_error(world):
    world.make_prefix()

    with setup_lock(world.paths):
        code, events = world.engine(jobs.tool_install, "workshop")

    assert code == jobs.FAILED
    assert events[-1] == Error(None, "Another setup is already running. Wait for it to finish.")


def test_missing_32bit_extensions_stop_before_proton_runs(world, monkeypatch):
    monkeypatch.setattr(doctor, "LIB_ROOT", world.tmp / "nothing")
    world.make_prefix()

    code, events = world.engine(jobs.aio_launcher_install)

    assert code == jobs.FAILED
    assert events[-1] == Error("aio-launcher", "The 32-bit Flatpak extensions are not installed.")
    assert not Path(world.env["UMU_LOG"]).exists()


def test_a_bad_config_file_is_an_error(world):
    world.paths.base.mkdir(parents=True)
    world.paths.config.write_text("BFME_GRAPHICS=direct3d\n")

    code, events = world.engine(jobs.status)

    assert code == jobs.FAILED
    assert events == [Error(None, 'BFME_GRAPHICS must be vulkan or opengl, not "direct3d".')]


def test_progress_is_reported_while_proton_downloads(world, monkeypatch, file_server):
    seen = []

    def ensure_proton(paths, config, on_progress, cancel, emit=None):
        on_progress(50)
        on_progress(100)
        return "fake-proton"

    monkeypatch.setattr(jobs.proton, "ensure_proton", ensure_proton)

    code, events = world.engine(jobs.prepare)

    for event in events:
        if isinstance(event, Progress):
            seen.append(event.percent)

    assert code == jobs.OK
    assert seen == [50, 100]


# Opening a program

def test_opening_age_of_the_ring_starts_it_from_its_folder(world):
    world.make_prefix()
    world.paths.aotr_exe.parent.mkdir(parents=True)
    world.paths.aotr_exe.write_text("x")

    code, events = world.engine(jobs.open_program, "aotr")

    assert code == jobs.OK
    assert Path(world.env["UMU_LOG"]).read_text().splitlines()[-1] == f"umu {world.paths.aotr_exe}"
    assert events[-1].text.startswith("Starting aotr. Log: ")


def test_opening_a_missing_program_says_so(world):
    world.make_prefix()

    code, events = world.engine(jobs.open_program, "workshop")

    assert code == jobs.FAILED
    assert events[-1] == Error(None, "Workshop Studio is not installed.")


def test_opening_the_aio_launcher_installs_it_first(world):
    world.make_prefix()

    code, events = world.engine(jobs.open_program, "aio-launcher")

    assert code == jobs.OK
    assert programs.aio_launcher_installed(world.paths)
    assert events[-1].text.startswith("Starting the AIO Launcher. Log: ")
    assert list(world.paths.logs.glob("aio-launcher-2*.log"))


def test_the_lock_is_free_while_the_program_runs(world, monkeypatch):
    world.make_prefix()
    world.paths.aotr_exe.parent.mkdir(parents=True)
    world.paths.aotr_exe.write_text("x")
    held = []

    def start_program(*args):
        with setup_lock(world.paths):
            held.append(True)

        return 0

    monkeypatch.setattr(jobs.launch, "start_program", start_program)
    world.engine(jobs.open_program, "aotr")

    assert held == [True]
