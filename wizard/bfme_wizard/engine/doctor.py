"""The system check: what must be in place before the setup can run. Only checks that can fail inside the Flatpak."""
from __future__ import annotations

import platform
import shutil
from pathlib import Path

from . import graphics
from .config import Config
from .events import Check, Emit, Fix, Log
from .paths import Paths

MIN_FREE_GB = 30   # three games plus the Arena
FLATPAK_RUNTIME_VERSION = "25.08"
LIB_ROOT = Path("/usr/lib")

FLATPAK_32BIT_HELP = f"""The 32-bit parts of the Flatpak runtime are not installed, so the games and apps cannot start.
Easiest fix: run the installer again (it also picks the 32-bit driver that matches your graphics card):
  curl -fLO <repository address>/install-flatpak.sh && bash install-flatpak.sh
Or by hand, then start the app again:
  flatpak install flathub org.freedesktop.Platform.Compat.i386//{FLATPAK_RUNTIME_VERSION} org.freedesktop.Platform.GL32.default//{FLATPAK_RUNTIME_VERSION}
With an NVIDIA graphics card also install the matching 32-bit driver. Find its name with:
  flatpak list | grep nvidia
and install the same name with GL32 in place of GL, for example org.freedesktop.Platform.GL32.nvidia-<version>."""



def flatpak_32bit_missing(lib_root: Path | None = None) -> bool:
    """Whether the 32-bit Flatpak extensions are missing. Flatpak does not install them for apps outside Flathub, and
    without them Proton's container fails silently."""
    lib_root = lib_root or LIB_ROOT

    if not (lib_root / "i386-linux-gnu/ld-linux.so.2").exists():
        return True

    # Each 64-bit GL driver (nvidia-550-107-02, say) needs the same 32-bit one. A host driver update changes the name, and
    # flatpak update does not fetch the 32-bit match.
    found_gl32 = False

    for driver in sorted((lib_root / "x86_64-linux-gnu/GL").glob("nvidia-*")):
        if not driver.is_dir():
            continue

        if not (lib_root / "i386-linux-gnu/GL" / driver.name).is_dir():
            return True

        found_gl32 = True

    if found_gl32:
        return False

    return not (lib_root / "i386-linux-gnu/GL/default").is_dir()


def flatpak_32bit_fix(lib_root: Path | None = None) -> str:
    """The command that installs the missing extensions, with the 32-bit match of each NVIDIA driver."""
    lib_root = lib_root or LIB_ROOT
    extensions = [
        f"org.freedesktop.Platform.Compat.i386//{FLATPAK_RUNTIME_VERSION}",
        f"org.freedesktop.Platform.GL32.default//{FLATPAK_RUNTIME_VERSION}",
    ]

    for driver in sorted((lib_root / "x86_64-linux-gnu/GL").glob("nvidia-*")):
        if driver.is_dir():
            extensions.append(f"org.freedesktop.Platform.GL32.{driver.name}")

    return "flatpak install --user flathub " + " ".join(extensions)


def _existing_parent(path: Path) -> Path:
    """The folder itself, or the nearest one above it that exists."""
    while not path.is_dir() and path != path.parent:
        path = path.parent

    return path


def _graphics_check(config: Config) -> Check:
    """What the computer supports, and whether the chosen backend matches it."""
    backend, why = graphics.probe()
    using = f"Using {graphics.label(config.graphics)}."

    if backend == "unknown":
        return Check("graphics", "warn", f"Graphics: {why}. {using}")

    if backend == config.graphics:
        return Check("graphics", "ok", f"Graphics: {why}. {using}")

    # The computer suits OpenGL but Vulkan is set: before the first setup detection still picks OpenGL.
    if backend == "opengl" and not config.graphics_chosen:
        return Check("graphics", "ok", f"Graphics: {why}. The setup will use OpenGL (WineD3D).")

    if backend == "opengl":
        return Check("graphics", "warn", f"Graphics: {why}. OpenGL is recommended: switch it under Troubleshoot, Graphics.")

    return Check("graphics", "ok", f"Graphics: {why}. Using {graphics.label(config.graphics)}, as you chose.")


def run_checks(paths: Paths, config: Config, emit: Emit, lib_root: Path | None = None) -> bool:
    """Run every check and report each one. False when a check failed and the setup cannot go on."""
    emit(Log(f"System check (graphics: {graphics.label(config.graphics)})"))
    checks: list[Check] = []

    machine = platform.machine()

    if machine == "x86_64":
        checks.append(Check("cpu", "ok", "x86_64 processor"))
    else:
        checks.append(Check("cpu", "fail", f"processor is {machine}; only x86_64 is supported"))

    if flatpak_32bit_missing(lib_root):
        checks.append(Check("flatpak-32bit", "fail", "the 32-bit Flatpak extensions are not installed"))
    else:
        checks.append(Check("flatpak-32bit", "ok", "32-bit Flatpak extensions installed"))

    checks.append(_graphics_check(config))

    free_gb = shutil.disk_usage(_existing_parent(paths.base)).free // (1024 ** 3)

    if free_gb >= MIN_FREE_GB:
        checks.append(Check("disk", "ok", f"free disk space: {free_gb} GB (need about {MIN_FREE_GB} GB)"))
    else:
        checks.append(Check("disk", "warn", f"less than {MIN_FREE_GB} GB free where the data goes ({paths.base})"))

    # A Flatpak cannot see the host's firewall services.
    checks.append(Check("firewall", "ok", "firewall: not checked from inside a Flatpak. If you cannot host or join games, "
                                          "check ufw or firewalld on your system."))

    marks = {"ok": "[ok]  ", "warn": "[warn]", "fail": "[FAIL]"}
    fails = 0
    warns = 0

    for check in checks:
        emit(Log(f"  {marks[check.level]} {check.message}"))
        emit(check)

        if check.level == "fail":
            fails += 1

        if check.level == "warn":
            warns += 1

        if check.id == "flatpak-32bit" and check.level == "fail":
            for line in FLATPAK_32BIT_HELP.splitlines():
                emit(Log(f"         {line}"))

            emit(Fix("flatpak-32bit", flatpak_32bit_fix(lib_root)))

    if fails:
        emit(Log(f"{fails} problem(s) must be fixed first."))
        return False

    if warns:
        emit(Log(f"Ready, with {warns} warning(s) above."))
    else:
        emit(Log("Ready."))

    return True
