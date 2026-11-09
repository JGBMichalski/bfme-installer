"""The system check: what must be in place before the setup can run, and whether the games' d3d9.dll is ready for the
Arena's in-game overlay. Only checks that can fail inside the Flatpak."""

from __future__ import annotations

import platform
import shutil
from pathlib import Path

from .config import Config
from .events import Check, Emit, Fix, Log
from .game_environment import GameEnvironment
from .graphics import Graphics
from .overlay_pattern import OverlayPattern
from .paths import Paths
from .programs import ARENA


class SystemCheck:
    """The checks for one game environment and the player's settings."""

    MIN_FREE_GB = 30  # three games plus the Arena
    FLATPAK_RUNTIME_VERSION = "25.08"
    LIB_ROOT = Path("/usr/lib")

    FLATPAK_32BIT_HELP = "\n".join(
        [
            "The 32-bit parts of the Flatpak runtime are not installed, so the games and apps cannot start.",
            "Easiest fix: run the installer again (it also picks the 32-bit driver that matches your graphics card):",
            "  curl -fLO <repository address>/install-flatpak.sh && bash install-flatpak.sh",
            "Or by hand, then start the app again:",
            f"  flatpak install flathub org.freedesktop.Platform.Compat.i386//{FLATPAK_RUNTIME_VERSION} "
            f"org.freedesktop.Platform.GL32.default//{FLATPAK_RUNTIME_VERSION}",
            "With an NVIDIA graphics card also install the matching 32-bit driver. Find its name with:",
            "  flatpak list | grep nvidia",
            "and install the same name with GL32 in place of GL, for example org.freedesktop.Platform.GL32.nvidia-<version>.",
        ]
    )

    def __init__(self, paths: Paths, config: Config, lib_root: Path | None = None) -> None:
        self.paths = paths
        self.config = config
        self.lib_root = lib_root or self.LIB_ROOT

    def flatpak_32bit_missing(self) -> bool:
        """Whether the 32-bit Flatpak extensions are missing. Flatpak does not install them for apps outside Flathub, and
        without them Proton's container fails silently."""
        lib_root = self.lib_root

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

    def flatpak_32bit_fix(self) -> str:
        """The command that installs the missing extensions, with the 32-bit match of each NVIDIA driver."""
        lib_root = self.lib_root
        extensions = [
            f"org.freedesktop.Platform.Compat.i386//{self.FLATPAK_RUNTIME_VERSION}",
            f"org.freedesktop.Platform.GL32.default//{self.FLATPAK_RUNTIME_VERSION}",
        ]

        for driver in sorted((lib_root / "x86_64-linux-gnu/GL").glob("nvidia-*")):
            if driver.is_dir():
                extensions.append(f"org.freedesktop.Platform.GL32.{driver.name}")

        return "flatpak install --user flathub " + " ".join(extensions)

    @staticmethod
    def _existing_parent(path: Path) -> Path:
        """The folder itself, or the nearest one above it that exists."""
        while not path.is_dir() and path != path.parent:
            path = path.parent

        return path

    def _graphics_check(self) -> Check:
        config = self.config
        """What the computer supports, and whether the chosen backend matches it."""
        backend, why = Graphics.probe()
        using = f"Using {Graphics.label(config.graphics)}."

        if backend == "unknown":
            return Check("graphics", "warn", f"Graphics: {why}. {using}")

        if backend == config.graphics:
            return Check("graphics", "ok", f"Graphics: {why}. {using}")

        # The computer suits OpenGL but Vulkan is set: before the first setup detection still picks OpenGL.
        if backend == "opengl" and not config.graphics_chosen:
            return Check("graphics", "ok", f"Graphics: {why}. The setup will use OpenGL (WineD3D).")

        if backend == "opengl":
            return Check(
                "graphics", "warn", f"Graphics: {why}. OpenGL is recommended: switch it under Settings, Graphics."
            )

        return Check("graphics", "ok", f"Graphics: {why}. Using {Graphics.label(config.graphics)}, as you chose.")

    def _d3d9_check(self) -> Check:
        """Whether the d3d9.dll the games load is the chosen graphics' own, and ready for the Arena's in-game overlay. A
        warning at most: nothing on the computer has to change, and the programs open either way."""
        found = OverlayPattern(self.paths).inspect()
        overlay = "the Arena's in-game overlay"

        if found.missing:
            message = f"d3d9.dll: not in the game environment, so {overlay} cannot start."
        elif found.problem is not None:
            message = f"d3d9.dll: cannot be made ready for {overlay}, because {found.problem}."
        elif found.ready:
            message = f"d3d9.dll: {found.whose}'s, ready for {overlay}."
        else:
            message = (
                f"d3d9.dll: {found.whose}'s, not ready for {overlay} yet. Opening any program here makes it ready."
            )

        graphics = self.config.graphics
        matches = found.whose == ("DXVK" if graphics == "vulkan" else "Wine")

        if found.whose is not None and not matches:
            message += f" The graphics are {Graphics.label(graphics)}, though."

        if found.own:
            names = found.own
            listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
            have = "has its" if len(names) == 1 else "have their"
            message += f" {listed} {have} own d3d9.dll, which the overlay may not work with."

        level = "ok" if found.ready and matches and not found.own else "warn"
        return Check("d3d9", level, message)

    def run(self, emit: Emit) -> bool:
        """Run every check and report each one. False when a check failed and the setup cannot go on."""
        config = self.config
        paths = self.paths
        emit(Log(f"System check (graphics: {Graphics.label(config.graphics)})"))
        checks: list[Check] = []

        machine = platform.machine()

        if machine == "x86_64":
            checks.append(Check("cpu", "ok", "x86_64 processor"))
        else:
            checks.append(Check("cpu", "fail", f"processor is {machine}; only x86_64 is supported"))

        if self.flatpak_32bit_missing():
            checks.append(Check("flatpak-32bit", "fail", "the 32-bit Flatpak extensions are not installed"))
        else:
            checks.append(Check("flatpak-32bit", "ok", "32-bit Flatpak extensions installed"))

        checks.append(self._graphics_check())

        if GameEnvironment(paths).ready() and ARENA.installed(paths):
            checks.append(self._d3d9_check())

        free_gb = shutil.disk_usage(self._existing_parent(paths.base)).free // (1024**3)

        if free_gb >= self.MIN_FREE_GB:
            checks.append(Check("disk", "ok", f"free disk space: {free_gb} GB (need about {self.MIN_FREE_GB} GB)"))
        else:
            checks.append(
                Check("disk", "warn", f"less than {self.MIN_FREE_GB} GB free where the data goes ({paths.base})")
            )

        # A Flatpak cannot see the host's firewall services.
        checks.append(
            Check(
                "firewall",
                "ok",
                "firewall: not checked from inside a Flatpak. If you cannot host or join games, "
                "check ufw or firewalld on your system.",
            )
        )

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
                for line in self.FLATPAK_32BIT_HELP.splitlines():
                    emit(Log(f"         {line}"))

                emit(Fix("flatpak-32bit", self.flatpak_32bit_fix()))

        if fails:
            emit(Log(f"{fails} problem(s) must be fixed first."))
            return False

        if warns:
            emit(Log(f"Ready, with {warns} warning(s) above."))
        else:
            emit(Log("Ready."))

        return True
