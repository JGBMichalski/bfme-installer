"""engine.jobs: each job's events, compared with the status lines of the setup script's command."""
import hashlib
import shutil
import subprocess
import threading
from pathlib import Path

import pytest
from bfme_wizard.engine import aotr, doctor, graphics, jobs, programs, shortcuts
from bfme_wizard.engine.events import (
    Cancelled,
    Check,
    Done,
    Error,
    Fix,
    Log,
    Progress,
    Status,
    Step,
    Warn,
)
from bfme_wizard.engine.lock import setup_lock
from bfme_wizard.engine.paths import Paths

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "bfme-linux-setup.sh"
SEVENZIP = shutil.which("7zz") or shutil.which("7z") or shutil.which("7za")

# Makes the prefix on the first start, and installs the AIO Launcher and Age of the Ring when their installers run.
FAKE_UMU = r"""#!/bin/sh
case "${1:-}" in
  "") mkdir -p "$WINEPREFIX/drive_c/windows" "$WINEPREFIX/drive_c/users/steamuser" ;;
  *AllInOneLauncherSetup.exe)
      d="$WINEPREFIX/drive_c/users/steamuser/AppData/Roaming/BFME All In One Launcher"
      mkdir -p "$d"; printf 'launcher' > "$d/AllInOneLauncher.exe" ;;
  *AotR_Standalone*Installer.exe)
      mkdir -p "$WINEPREFIX/drive_c/AgeoftheRing"; printf 'aotr' > "$WINEPREFIX/drive_c/AgeoftheRing/AotR_Launcher.exe" ;;
esac
echo "umu $*" >> "$UMU_LOG"
exit 0
"""
# What the setup script downloads with: the same files the engine's local server gives.
FAKE_CURL = r"""#!/usr/bin/env bash
out=""; url=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -m|--retry|--retry-delay|--connect-timeout|--speed-limit|--speed-time|-C) shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
case "$url" in *versionHash*) printf '%s' "$(printf 'arena-binary' | md5sum | awk '{print $1}')"; exit 0 ;; esac
[ -n "$out" ] || exit 0
mkdir -p "$(dirname "$out")"
case "$url" in *online-arena*) printf 'arena-binary' > "$out" ;; *) printf 'fake-download' > "$out" ;; esac
"""


def executable(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)


class World:
    """Everything a job needs, faked the same way for the script and the engine."""

    def __init__(self, tmp_path, monkeypatch, file_server):
        self.tmp = tmp_path
        self.paths = Paths(tmp_path / "data")
        bin_dir = tmp_path / "bin"
        executable(bin_dir / "umu-run", FAKE_UMU)
        executable(bin_dir / "curl", FAKE_CURL)
        executable(bin_dir / "bwrap", "#!/bin/sh\nexit 0\n")
        executable(bin_dir / "lspci", "#!/bin/sh\n")
        executable(tmp_path / "probe", "#!/bin/sh\necho 'vulkan Vulkan 1.4 on Test GPU'\n")
        self.home = tmp_path / "home"
        self.env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(self.home), "BFME_HOME": str(self.paths.base),
            "XDG_DATA_HOME": str(tmp_path / "xdg"), "BFME_UMU_RUN": str(bin_dir / "umu-run"),
            "BFME_PROTONPATH": "fake-proton", "BFME_VULKAN_PROBE": str(tmp_path / "probe"),
            "UMU_LOG": str(tmp_path / "umu.log"),
        }

        for name, value in self.env.items():
            monkeypatch.setenv(name, value)

        monkeypatch.delenv("FLATPAK_ID", raising=False)

        # The engine's downloads come from the local server, with the same files the fake curl gives.
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

    def make_prefix(self):
        for folder in ("windows", "users/steamuser"):
            (self.paths.drive_c / folder).mkdir(parents=True, exist_ok=True)

    def script(self, *args):
        done = subprocess.run([str(SCRIPT), "--machine", *args], env=self.env, capture_output=True, text=True, timeout=120)
        lines = []

        for line in done.stdout.splitlines():
            if line.startswith("@bfme ") and not line.startswith("@bfme PROGRESS"):
                lines.append(line.replace("@bfme STATUS launcher ", "@bfme STATUS aio-launcher "))

        return done.returncode, lines

    def engine(self, job, *args, cancel=None):
        events = []
        code = job(*args, events.append, cancel)
        return code, events

    def reset(self):
        shutil.rmtree(self.paths.base, ignore_errors=True)
        shutil.rmtree(self.home, ignore_errors=True)
        Path(self.env["UMU_LOG"]).unlink(missing_ok=True)


def lines(events):
    """The events as the setup script's status lines, without PROGRESS."""
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
    """The script outside the Flatpak checks other things than the engine in it; the checks are compared in
    test_engine_doctor."""
    out = []

    for line in found:
        if not line.startswith(("@bfme CHECK ", "@bfme FIX ")):
            out.append(line)

    return out


@pytest.fixture
def world(tmp_path, monkeypatch, file_server):
    return World(tmp_path, monkeypatch, file_server)


def same(world, setup, script_args, job, *job_args, compare=lambda found: found):
    """Run the script's command and the engine's job from the same start; both must report the same."""
    setup()
    script_code, from_script = world.script(*script_args)
    world.reset()
    setup()
    code, events = world.engine(job, *job_args)

    assert compare(lines(events)) == compare(from_script)
    assert code == script_code

    return events


def nothing():
    pass


# What is there

def test_status_of_nothing(world):
    same(world, nothing, ["status"], jobs.status)


def test_status_of_a_ready_environment(world):
    def setup():
        world.make_prefix()
        (world.paths.aotr_exe.parent).mkdir(parents=True)
        world.paths.aotr_exe.write_text("x")

    same(world, setup, ["status"], jobs.status)


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
    events = same(world, nothing, ["prepare"], jobs.prepare, compare=without_checks)

    assert Status("prefix", "ready") in events
    assert Log("The game environment is ready.") in events


def test_prepare_stops_at_a_failed_check(world, monkeypatch):
    monkeypatch.setattr(doctor.platform, "machine", lambda: "aarch64")
    code, events = world.engine(jobs.prepare)

    assert code == jobs.FAILED
    assert lines(events)[-1] == "@bfme ERROR doctor Fix the problems above, then run prepare again."
    assert not world.paths.prefix.exists()


def test_the_aio_launcher_and_the_arena(world):
    events = same(world, world.make_prefix, ["launcher-install"], jobs.aio_launcher_install)

    assert Status("aio-launcher", "installed") in events
    assert Status("arena", "installed") in events
    assert (world.home / f".local/share/applications/{shortcuts.RELEASE_APP_ID}.Launcher.desktop").is_file()


def test_the_aio_launcher_needs_the_game_environment(world):
    same(world, nothing, ["launcher-install"], jobs.aio_launcher_install)


@pytest.mark.parametrize("tool", programs.TOOLS)
def test_a_tool(world, tool):
    same(world, world.make_prefix, ["tool-install", tool], jobs.tool_install, tool)


def test_an_unknown_tool(world):
    same(world, world.make_prefix, ["tool-install", "bogus"], jobs.tool_install, "bogus")


@pytest.mark.skipif(SEVENZIP is None, reason="7-Zip is needed to read the Age of the Ring download")
def test_age_of_the_ring(world):
    source = world.tmp / "zip-source"
    source.mkdir()
    (source / "AotR_Standalone_9.3.0_Installer.exe").write_text("installer")
    (source / "AotR_Standalone_9.3.0_Installer-1a.bin").write_bytes(b"x" * 2048)
    zip_path = world.tmp / "AotR_Standalone_9.3.0_Installer.zip"
    subprocess.run([SEVENZIP, "a", "-tzip", "-bso0", "-bsp0", str(zip_path), "."], cwd=source, check=True)

    events = same(world, world.make_prefix, ["aotr-install", str(zip_path)], jobs.aotr_install, str(zip_path))

    assert Status("aotr", "installed") in events


def test_age_of_the_ring_needs_a_file(world):
    same(world, world.make_prefix, ["aotr-install"], jobs.aotr_install, "")


# Changing what is there

@pytest.mark.parametrize("program", ["aio-launcher", "arena", "aotr", "workshop", "mission-control"])
def test_remove(world, program):
    def setup():
        world.make_prefix()

        for exe in (world.paths.aio_launcher_exe, world.paths.arena_exe, world.paths.aotr_exe,
                    world.paths.tool_exe("workshop"), world.paths.tool_exe("mission-control")):
            exe.parent.mkdir(parents=True, exist_ok=True)
            exe.write_text("x")

    script_name = "launcher" if program == "aio-launcher" else program
    events = same(world, setup, ["remove", script_name], jobs.remove, program)

    assert Status(program, "missing") in events


@pytest.mark.parametrize("backend", ["vulkan", "opengl"])
def test_switching_graphics(world, backend):
    same(world, world.make_prefix, ["graphics", backend], jobs.switch_graphics, backend)


def test_reset(world):
    def setup():
        world.make_prefix()
        world.paths.aotr_exe.parent.mkdir(parents=True)
        world.paths.aotr_exe.write_text("x")

    same(world, setup, ["reset-prefix", "--yes"], jobs.reset)

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
    assert events[-1] == Error("launcher", "The 32-bit Flatpak extensions are not installed.")
    assert not Path(world.env["UMU_LOG"]).exists()


def test_a_bad_config_file_is_an_error(world):
    world.paths.base.mkdir(parents=True)
    world.paths.config.write_text("BFME_GRAPHICS=direct3d\n")

    code, events = world.engine(jobs.status)

    assert code == jobs.FAILED
    assert events == [Error(None, 'BFME_GRAPHICS must be vulkan or opengl, not "direct3d".')]


def test_progress_is_reported_while_proton_downloads(world, monkeypatch, file_server):
    seen = []
    monkeypatch.setattr(jobs.proton, "ensure_proton",
                        lambda paths, config, on_progress, cancel: (on_progress(50), on_progress(100), "fake-proton")[2])

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
    assert list(world.paths.logs.glob("launcher-2*.log"))


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
