"""The graphics backend's name, and which one suits this computer."""

from __future__ import annotations

import os
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
