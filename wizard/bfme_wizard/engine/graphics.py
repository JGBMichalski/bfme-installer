"""The graphics backend's name, and which one suits this computer."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


class Graphics:
    """The graphics backends: their names, and which one suits this computer."""

    PROBE_TIMEOUT_SEC = 20  # a hung driver must not stop the setup
    PACKAGE_ROOT = Path(__file__).resolve().parents[2]  # the folder that holds bfme_wizard

    @staticmethod
    def label(graphics: str) -> str:
        return "OpenGL (WineD3D)" if graphics == "opengl" else "Vulkan (DXVK)"

    @staticmethod
    def probe() -> tuple[str, str]:
        """("vulkan", "opengl" or "unknown", why).

        Runs engine/vulkan.py as a child process: loading a broken graphics driver can hang or crash the process that does it,
        and that must not be the wizard.
        """
        env = dict(os.environ)
        pythonpath = str(Graphics.PACKAGE_ROOT)

        if env.get("PYTHONPATH"):
            pythonpath += os.pathsep + env["PYTHONPATH"]

        env["PYTHONPATH"] = pythonpath
        command = [sys.executable, "-m", "bfme_wizard.engine.vulkan"]

        try:
            done = subprocess.run(
                command, env=env, capture_output=True, text=True, timeout=Graphics.PROBE_TIMEOUT_SEC, check=False
            )
            out = done.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            out = ""

        backend, _, why = out.partition(" ")

        if backend not in ("vulkan", "opengl", "unknown") or not why:
            return "unknown", "could not check Vulkan"

        return backend, why


class GraphicsCards:
    """The graphics cards of this computer, as `lspci` lists them. Read when made. None without `lspci`."""

    # The kinds of device lspci gives a graphics card: an ordinary one, a card that only renders (a laptop's NVIDIA card,
    # say), and one that only drives a screen.
    KINDS = re.compile(r"\b(VGA compatible controller|3D controller|Display controller)\b")
    TIMEOUT_SEC = 10

    def __init__(self) -> None:
        self.names = self._read()

    def _read(self) -> list[str]:
        """The name of each card, as lspci gives it after the kind of device."""
        lspci = shutil.which("lspci")

        if lspci is None:
            return []

        try:
            done = subprocess.run([lspci], capture_output=True, text=True, timeout=self.TIMEOUT_SEC, check=False)
        except (OSError, subprocess.SubprocessError):
            return []

        names = []

        for line in done.stdout.splitlines():
            if self.KINDS.search(line):
                names.append(line.partition(": ")[2] or line)

        return names

    @property
    def count(self) -> int:
        return len(self.names)

    @property
    def nvidia_offload(self) -> bool:
        """Whether to send the games to an NVIDIA card: only on a computer with more than one card, one of them
        NVIDIA."""
        has_nvidia = False

        for name in self.names:
            if "nvidia" in name.lower():
                has_nvidia = True

        return self.count > 1 and has_nvidia
