"""engine.system_check: the system check."""

from collections import namedtuple

import pytest

from bfme_wizard.engine import system_check as doctor
from bfme_wizard.engine.config import Config, ConfigFile
from bfme_wizard.engine.events import Check, Fix, Log
from bfme_wizard.engine.graphics import Graphics
from bfme_wizard.engine.paths import Paths
from bfme_wizard.engine.system_check import SystemCheck

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
    (OPENGL, "vulkan", "warn", f"{NO_VULKAN} OpenGL is recommended: switch it under Troubleshoot, Graphics."),
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
