"""The Troubleshoot report text and log locations. No GTK.

The report can contain the home folder and user name, so the window tells players to check it before sharing.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from pathlib import Path

from .engine.graphics import Graphics
from .engine.logs import RunLogs
from .model import GAMES, SetupModel


class Diagnostics:
    """What a bug report needs: the computer, where the setup stands, and the end of the latest logs."""

    LOG_LINES = 40
    # (title, log name) of the logs the report ends with
    LOGS = (("AIO Launcher", "aio-launcher"), ("Arena", "arena"), ("prefix creation", "prefix-create"))

    def __init__(self, log_dir: Path, environ: dict[str, str] | None = None) -> None:
        self.log_dir = log_dir
        self.environ = environ

    def newest_log(self, name: str) -> Path | None:
        """The most recent '<name>-<date>-<time>.log', or else the plain '<name>.log'."""
        started = RunLogs(self.log_dir, name).started()

        if started:
            return started[0]

        plain = self.log_dir / f"{name}.log"

        if plain.is_file():
            return plain

        return None

    def any_log(self) -> Path | None:
        """A file in the logs folder to reveal in a file manager; None without logs."""
        if not self.log_dir.is_dir():
            return None

        newest = None

        for log in self.log_dir.glob("*.log"):
            if newest is None or log.stat().st_mtime >= newest.stat().st_mtime:
                newest = log

        return newest

    def tail(self, path: Path, lines: int | None = None) -> str:
        """The last lines of a log."""
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            return f"(could not read: {error})"

        return "\n".join(text.splitlines()[-(lines or self.LOG_LINES) :])

    def _os_name(self) -> str:
        """The distribution's name. In the Flatpak the host's file says more than the runtime's."""
        for path in ("/run/host/os-release", "/etc/os-release"):
            try:
                text = Path(path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            for line in text.splitlines():
                if line.startswith("PRETTY_NAME="):
                    return line.partition("=")[2].strip().strip('"')

        return "unknown"

    def _gpus(self) -> list[str]:
        """One line per graphics card, as `lspci` names it; empty when `lspci` is missing or fails."""
        if not shutil.which("lspci"):
            return []

        try:
            out = subprocess.run(["lspci"], capture_output=True, text=True, timeout=5, check=False).stdout
        except (OSError, subprocess.SubprocessError):
            return []

        cards = []

        for line in out.splitlines():
            if re.search(r"\b(VGA compatible controller|3D controller|Display controller)\b", line):
                cards.append(line.partition(": ")[2] or line)

        return cards

    def _nvidia_driver(self) -> str | None:
        """The NVIDIA kernel driver's version, or None without one."""
        try:
            text = Path("/proc/driver/nvidia/version").read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

        match = re.search(r"Kernel Module(?: for \S+)?\s+(\d[\d.]*)", text)

        if match is None:
            return None

        return match.group(1)

    def _vulkan(self) -> str:
        backend, why = Graphics.probe()

        if backend == "unknown":
            return why

        suits = "Vulkan" if backend == "vulkan" else "OpenGL"
        return f"{why} (suits {suits})"

    def _session(self, env) -> str:
        if env.get("XDG_SESSION_TYPE"):
            return env["XDG_SESSION_TYPE"]

        if env.get("WAYLAND_DISPLAY"):
            return "wayland"

        if env.get("DISPLAY"):
            return "x11"

        return "unknown"

    def system_lines(self) -> list[str]:
        """What a bug report about the display, the graphics or the window needs to know about the computer.

        The window mode and click-offset problems depend on the session (X11 or Wayland) and the desktop; the graphics
        ones on the card and driver. Each line says "unknown" or "none" rather than being left out, so a missing fact is
        visible.
        """
        env = os.environ if self.environ is None else self.environ
        lines = [
            f"System: {self._os_name()}, kernel {platform.release()}",
            f"Desktop: {env.get('XDG_CURRENT_DESKTOP') or 'unknown'}, {self._session(env)} session",
        ]
        gpus = self._gpus()

        for gpu in gpus:
            lines.append(f"Graphics card: {gpu}")

        if not gpus:
            lines.append("Graphics card: unknown")

        lines.append(f"NVIDIA driver: {self._nvidia_driver() or 'none'}")
        lines.append(f"Vulkan: {self._vulkan()}")
        return lines

    def report(self, version: str, model: SetupModel, system: list[str] | None = None) -> str:
        status = model.status
        graphics = "unknown"
        runner = "unknown"

        if status is not None:
            graphics = model.graphics_label
            runner = "proton"

        out = [
            "BFME Installer diagnostics",
            f"Version: {version}",
            f"Runner: {runner}",
            f"Graphics: {graphics}",
        ]

        if system is None:
            system = self.system_lines()

        out += system

        if status is None:
            setup = ["prefix unknown", "aio-launcher unknown", "arena unknown"]
        else:
            setup = [f"prefix {'ready' if status.prefix_ready else 'missing'}"]

            for key in ("aio-launcher", "arena"):
                setup.append(f"{key} {'installed' if key in status.programs else 'missing'}")

        out.append("Setup: " + ", ".join(setup))

        games = []

        for key, name in GAMES:
            if status is None:
                games.append(f"{name} unknown")
            elif key in status.games:
                games.append(f"{name} installed")
            else:
                games.append(f"{name} missing")

        out.append("Games: " + ", ".join(games))
        out += ["", "System checks:"]

        if model.checks:
            marks = {"ok": "ok", "warn": "warning", "fail": "FAILED"}

            for _cid, level, message, fix in model.check_rows:
                out.append(f"  [{marks[level]}] {message}")

                if fix:
                    out.append(f"      fix: {fix}")
        else:
            out.append("  (not run yet)")

        for title, name in self.LOGS:
            log = self.newest_log(name)
            out.append("")

            if log is None:
                out.append(f"--- no {title} log ---")
                continue

            out.append(f"--- latest {title} log ({log.name}, last {self.LOG_LINES} lines) ---")
            out.append(self.tail(log))

        return "\n".join(out) + "\n"
