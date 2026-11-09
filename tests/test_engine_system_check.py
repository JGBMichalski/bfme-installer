"""engine.system_check: the system check."""

from collections import namedtuple

import pytest

from bfme_wizard.engine import system_check as doctor
from bfme_wizard.engine.config import Config, ConfigFile
from bfme_wizard.engine.events import Check, Fix, Log
from bfme_wizard.engine.game_environment import GameEnvironment
from bfme_wizard.engine.games import GAMES
from bfme_wizard.engine.graphics import Graphics
from bfme_wizard.engine.overlay_pattern import OverlayPattern
from bfme_wizard.engine.paths import Paths
from bfme_wizard.engine.programs import ARENA
from bfme_wizard.engine.system_check import SystemCheck
from tests.fake_dll import fake_dxvk, fake_wine_d3d9

Usage = namedtuple("Usage", "total used free")
KEPT = ("cpu", "flatpak-32bit", "graphics", "disk", "firewall")


@pytest.fixture
def paths(tmp_path):
    return Paths(tmp_path / "data")


@pytest.fixture
def probe(monkeypatch):
    answer = {"value": ("vulkan", "Vulkan 1.4 on Test GPU")}
    monkeypatch.setattr(Graphics, "probe", lambda: answer["value"])
    return answer


def lib_root(tmp_path, *files):
    """A stand-in for /usr/lib holding these files and folders (folders end in /)."""
    root = tmp_path / "lib"

    for name in files:
        if name.endswith("/"):
            (root / name).mkdir(parents=True, exist_ok=True)
        else:
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).touch()

    return root


def run(paths, config, root):
    events = []
    ok = SystemCheck(paths, config, root).run(events.append)
    return ok, events


def logs(events):
    out = []

    for event in events:
        if isinstance(event, Log):
            out.append(event.text)

    return out


LD = "i386-linux-gnu/ld-linux.so.2"
GL32 = "i386-linux-gnu/GL/default/"


# The 32-bit extensions

MISSING_32BIT_HELP = [
    "         The 32-bit parts of the Flatpak runtime are not installed, so the games and apps cannot start.",
    "         Easiest fix: run the installer again (it also picks the 32-bit driver that matches your graphics card):",
    "           curl -fLO <repository address>/install-flatpak.sh && bash install-flatpak.sh",
    "         Or by hand, then start the app again:",
    "           flatpak install flathub org.freedesktop.Platform.Compat.i386//25.08 org.freedesktop.Platform.GL32.default//25.08",
    "         With an NVIDIA graphics card also install the matching 32-bit driver. Find its name with:",
    "           flatpak list | grep nvidia",
    "         and install the same name with GL32 in place of GL, for example org.freedesktop.Platform.GL32.nvidia-<version>.",
]


def help_lines(events):
    out = []

    for line in logs(events):
        if line.startswith("         "):
            out.append(line)

    return out


@pytest.mark.parametrize(
    "files,missing",
    [
        ((), True),
        ((LD,), True),
        ((GL32,), True),
        ((LD, GL32), False),
        ((LD, GL32, "x86_64-linux-gnu/GL/nvidia-550-107-02/"), True),
        ((LD, "x86_64-linux-gnu/GL/nvidia-550-107-02/", "i386-linux-gnu/GL/nvidia-550-107-02/"), False),
    ],
)
def test_the_32bit_extensions(tmp_path, files, missing):
    assert (
        SystemCheck(Paths(tmp_path / "data"), Config(), lib_root(tmp_path, *files)).flatpak_32bit_missing() is missing
    )


def test_the_fix_names_each_nvidia_drivers_32bit_match(tmp_path):
    root = lib_root(tmp_path, "x86_64-linux-gnu/GL/nvidia-560-35-03/", "x86_64-linux-gnu/GL/nvidia-550-107-02/")

    assert SystemCheck(Paths(tmp_path / "data"), Config(), root).flatpak_32bit_fix() == (
        "flatpak install --user flathub org.freedesktop.Platform.Compat.i386//25.08 "
        "org.freedesktop.Platform.GL32.default//25.08 org.freedesktop.Platform.GL32.nvidia-550-107-02 "
        "org.freedesktop.Platform.GL32.nvidia-560-35-03"
    )


def test_missing_extensions_fail_the_check_with_help_and_a_fix(tmp_path, paths, probe):
    ok, events = run(paths, Config(), lib_root(tmp_path))

    assert ok is False
    assert Check("flatpak-32bit", "fail", "the 32-bit Flatpak extensions are not installed") in events
    assert (
        Fix("flatpak-32bit", SystemCheck(Paths(tmp_path / "data"), Config(), lib_root(tmp_path)).flatpak_32bit_fix())
        in events
    )
    assert help_lines(events) == MISSING_32BIT_HELP
    assert logs(events)[-1] == "1 problem(s) must be fixed first."


# The other checks


def test_a_ready_computer_passes(tmp_path, paths, probe, monkeypatch):
    monkeypatch.setattr(doctor.shutil, "disk_usage", lambda path: Usage(0, 0, 100 * 1024**3))
    ok, events = run(paths, Config(), lib_root(tmp_path, LD, GL32))

    checks = [e for e in events if isinstance(e, Check)]
    assert ok is True
    assert [c.id for c in checks] == list(KEPT)
    assert {c.level for c in checks} == {"ok"}
    assert logs(events)[0] == "System check (graphics: Vulkan (DXVK))"
    assert "  [ok]   free disk space: 100 GB (need about 30 GB)" in logs(events)
    assert logs(events)[-1] == "Ready."


def test_another_processor_fails(tmp_path, paths, probe, monkeypatch):
    monkeypatch.setattr(doctor.platform, "machine", lambda: "aarch64")
    ok, events = run(paths, Config(), lib_root(tmp_path, LD, GL32))

    assert ok is False
    assert Check("cpu", "fail", "processor is aarch64; only x86_64 is supported") in events


def test_little_disk_space_is_a_warning(tmp_path, paths, probe, monkeypatch):
    monkeypatch.setattr(doctor.shutil, "disk_usage", lambda path: Usage(0, 0, 5 * 1024**3))
    ok, events = run(paths, Config(), lib_root(tmp_path, LD, GL32))

    assert ok is True
    assert Check("disk", "warn", f"less than 30 GB free where the data goes ({paths.base})") in events
    assert logs(events)[-1] == "Ready, with 1 warning(s) above."


def test_disk_space_is_measured_where_the_data_will_go(tmp_path, paths, probe, monkeypatch):
    asked = []

    def disk_usage(path):
        asked.append(path)
        return Usage(0, 0, 100 * 1024**3)

    monkeypatch.setattr(doctor.shutil, "disk_usage", disk_usage)
    run(paths, Config(), lib_root(tmp_path, LD, GL32))

    assert asked == [tmp_path]


# The graphics check, for each probe answer and saved backend

VULKAN = ("vulkan", "Vulkan 1.4 on Test GPU")
OPENGL = ("opengl", "no graphics card with Vulkan was found")
UNKNOWN = ("unknown", "could not check Vulkan (boom)")
NO_VULKAN = "Graphics: no graphics card with Vulkan was found."
NOT_CHECKED = "Graphics: could not check Vulkan (boom)."

# (probe answer, saved backend): the graphics check's level and message.
GRAPHICS_CHECKS = [
    (VULKAN, None, "ok", "Graphics: Vulkan 1.4 on Test GPU. Using Vulkan (DXVK)."),
    (VULKAN, "vulkan", "ok", "Graphics: Vulkan 1.4 on Test GPU. Using Vulkan (DXVK)."),
    (VULKAN, "opengl", "ok", "Graphics: Vulkan 1.4 on Test GPU. Using OpenGL (WineD3D), as you chose."),
    (OPENGL, None, "ok", f"{NO_VULKAN} The setup will use OpenGL (WineD3D)."),
    (OPENGL, "vulkan", "warn", f"{NO_VULKAN} OpenGL is recommended: switch it under Settings, Graphics."),
    (OPENGL, "opengl", "ok", f"{NO_VULKAN} Using OpenGL (WineD3D)."),
    (UNKNOWN, None, "warn", f"{NOT_CHECKED} Using Vulkan (DXVK)."),
    (UNKNOWN, "vulkan", "warn", f"{NOT_CHECKED} Using Vulkan (DXVK)."),
    (UNKNOWN, "opengl", "warn", f"{NOT_CHECKED} Using OpenGL (WineD3D)."),
]


@pytest.mark.parametrize("answer,saved,level,message", GRAPHICS_CHECKS)
def test_the_checks_for_each_graphics_answer(tmp_path, paths, probe, monkeypatch, answer, saved, level, message):
    monkeypatch.setattr(doctor.shutil, "disk_usage", lambda path: Usage(0, 0, 100 * 1024**3))
    probe["value"] = answer
    paths.base.mkdir(parents=True, exist_ok=True)

    if saved:
        paths.config.write_text(f"BFME_GRAPHICS={saved}\n")
    else:
        paths.config.write_text("")

    _, events = run(paths, ConfigFile(paths.config).load({}), lib_root(tmp_path, LD, GL32))

    checks = []

    for event in events:
        if isinstance(event, (Check, Fix)):
            checks.append(event)

    assert checks == [
        Check("cpu", "ok", "x86_64 processor"),
        Check("flatpak-32bit", "ok", "32-bit Flatpak extensions installed"),
        Check("graphics", level, message),
        Check("disk", "ok", "free disk space: 100 GB (need about 30 GB)"),
        Check(
            "firewall",
            "ok",
            "firewall: not checked from inside a Flatpak. "
            "If you cannot host or join games, check ufw or firewalld on your system.",
        ),
    ]


# The d3d9.dll check, in a game environment with the Arena

OVERLAY = "the Arena's in-game overlay"
READY_DXVK = OverlayPattern.with_pattern(fake_dxvk())
READY_WINE = OverlayPattern.with_pattern(fake_wine_d3d9())
NOT_READY = f"not ready for {OVERLAY} yet. Opening any program here makes it ready."


def with_the_arena(paths, dll):
    """A ready game environment with the Arena, and this d3d9.dll where the games load it (none for None)."""
    for folder in ("windows/syswow64", "users/steamuser"):
        (paths.drive_c / folder).mkdir(parents=True, exist_ok=True)

    ARENA.exe(paths).parent.mkdir(parents=True, exist_ok=True)
    ARENA.exe(paths).write_bytes(b"MZ")

    if dll is not None:
        OverlayPattern(paths).dll.write_bytes(dll)


def d3d9_checks(tmp_path, paths, graphics="vulkan"):
    """Whether the system check lets the setup go on, and its d3d9.dll checks."""
    ok, events = run(paths, Config(graphics=graphics), lib_root(tmp_path, LD, GL32))
    return ok, [event for event in events if isinstance(event, Check) and event.id == "d3d9"]


def give_own_d3d9(paths, *keys):
    for game in GAMES:
        if game.key in keys:
            game.game_dir(paths).mkdir(parents=True, exist_ok=True)
            (game.game_dir(paths) / "d3d9.dll").write_bytes(b"MZ")


# (d3d9.dll, graphics): the check's level and message. It warns at most, so the setup always goes on.
@pytest.mark.parametrize(
    "dll, graphics, level, message",
    [
        pytest.param(READY_DXVK, "vulkan", "ok", f"d3d9.dll: DXVK's, ready for {OVERLAY}.", id="DXVK's"),
        pytest.param(READY_WINE, "opengl", "ok", f"d3d9.dll: Wine's, ready for {OVERLAY}.", id="Wine's"),
        pytest.param(fake_dxvk(), "vulkan", "warn", f"d3d9.dll: DXVK's, {NOT_READY}", id="DXVK's as it comes"),
        pytest.param(fake_wine_d3d9(), "opengl", "warn", f"d3d9.dll: Wine's, {NOT_READY}", id="Wine's as it comes"),
        pytest.param(
            READY_WINE,
            "vulkan",
            "warn",
            f"d3d9.dll: Wine's, ready for {OVERLAY}. The graphics are Vulkan (DXVK), though.",
            id="Wine's with Vulkan",
        ),
        pytest.param(
            fake_dxvk(),
            "opengl",
            "warn",
            f"d3d9.dll: DXVK's, {NOT_READY} The graphics are OpenGL (WineD3D), though.",
            id="DXVK's with OpenGL",
        ),
        pytest.param(
            None, "vulkan", "warn", f"d3d9.dll: not in the game environment, so {OVERLAY} cannot start.", id="none"
        ),
        pytest.param(
            fake_dxvk(name=b"N4dxvk10D3D9VolumeE\0"),
            "vulkan",
            "warn",
            f"d3d9.dll: cannot be made ready for {OVERLAY}, because it is neither DXVK's nor Wine's.",
            id="another",
        ),
    ],
)
def test_the_d3d9_check(tmp_path, paths, probe, dll, graphics, level, message):
    with_the_arena(paths, dll)

    assert d3d9_checks(tmp_path, paths, graphics) == (True, [Check("d3d9", level, message)])


def test_a_game_with_its_own_d3d9_is_a_warning(tmp_path, paths, probe):
    with_the_arena(paths, READY_DXVK)
    ready = f"d3d9.dll: DXVK's, ready for {OVERLAY}."
    give_own_d3d9(paths, "rotwk")

    assert d3d9_checks(tmp_path, paths)[1] == [
        Check(
            "d3d9", "warn", f"{ready} Rise of the Witch-king has its own d3d9.dll, which the overlay may not work with."
        )
    ]

    give_own_d3d9(paths, "bfme1", "bfme2")

    assert d3d9_checks(tmp_path, paths)[1] == [
        Check(
            "d3d9",
            "warn",
            f"{ready} BFME, BFME 2 and Rise of the Witch-king have their own d3d9.dll, which the overlay may not work with.",
        )
    ]


def test_the_d3d9_check_comes_after_the_graphics_check(tmp_path, paths, probe):
    with_the_arena(paths, READY_DXVK)

    _, events = run(paths, Config(), lib_root(tmp_path, LD, GL32))

    assert [event.id for event in events if isinstance(event, Check)] == [
        "cpu",
        "flatpak-32bit",
        "graphics",
        "d3d9",
        "disk",
        "firewall",
    ]


def test_without_the_arena_there_is_no_d3d9_check(tmp_path, paths, probe):
    with_the_arena(paths, None)
    ARENA.exe(paths).unlink()

    assert d3d9_checks(tmp_path, paths) == (True, [])


def test_before_the_game_environment_is_ready_there_is_no_d3d9_check(tmp_path, paths, probe):
    with_the_arena(paths, None)
    (paths.prefix / GameEnvironment.CREATING_MARKER).touch()

    assert d3d9_checks(tmp_path, paths) == (True, [])
