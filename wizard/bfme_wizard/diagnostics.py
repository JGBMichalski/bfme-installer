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

from .model import GAMES, SetupModel

LOG_LINES = 40


def data_dir(environ: dict[str, str] | None = None) -> Path:
    """The data folder the script uses: BFME_HOME, else XDG_DATA_HOME/bfme-installer."""
    env = os.environ if environ is None else environ
    if env.get("BFME_HOME"):
        return Path(env["BFME_HOME"])
    base = Path(env["XDG_DATA_HOME"]) if env.get("XDG_DATA_HOME") else Path.home() / ".local" / "share"
    return base / "bfme-installer"


def newest_log(log_dir: Path, prefix: str) -> Path | None:
    """The most recent '<prefix>-<time>.log', or the plain '<prefix>.log'."""
    candidates = sorted(log_dir.glob(f"{prefix}-*.log"), key=lambda p: p.stat().st_mtime) or sorted(log_dir.glob(f"{prefix}.log"))
    return candidates[-1] if candidates else None


def any_log(log_dir: Path) -> Path | None:
    """A file in the logs folder to reveal in a file manager; None without logs."""
    files = sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime) if log_dir.is_dir() else []
    return files[-1] if files else None


def tail(path: Path, lines: int = LOG_LINES) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        return f"(could not read: {error})"
    return "\n".join(text.splitlines()[-lines:])


def _os_name() -> str:
    """The distribution's name. In the Flatpak the host's file says more than the runtime's."""
    for path in ("/run/host/os-release", "/etc/os-release"):
        try:
            for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("PRETTY_NAME="):
                    return line.partition("=")[2].strip().strip('"')
        except OSError:
            continue
    return "unknown"


def _gpus() -> list[str]:
    """One line per graphics card, as `lspci` names it; empty when `lspci` is missing or fails."""
    if not shutil.which("lspci"):
        return []
    try:
        out = subprocess.run(["lspci"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    cards = []
    for line in out.splitlines():
        if re.search(r"\b(VGA compatible controller|3D controller|Display controller)\b", line):
            cards.append(line.partition(": ")[2] or line)
    return cards


def _nvidia_driver() -> str | None:
    """The NVIDIA kernel driver's version, or None without one."""
    try:
        match = re.search(r"Kernel Module(?: for \S+)?\s+(\d[\d.]*)", Path("/proc/driver/nvidia/version").read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None
    return match.group(1) if match else None


def system_lines(environ: dict[str, str] | None = None) -> list[str]:
    """What a bug report about the display, the graphics or the window needs to know about the computer.

    The window mode and click-offset problems depend on the session (X11 or Wayland) and the desktop; the graphics ones on the card
    and driver. Each line says "unknown" or "none" rather than being left out, so a missing fact is visible.
    """
    env = os.environ if environ is None else environ
    session = env.get("XDG_SESSION_TYPE") or ("wayland" if env.get("WAYLAND_DISPLAY") else "x11" if env.get("DISPLAY") else "unknown")
    lines = [
        f"System: {_os_name()}, kernel {platform.release()}",
        f"Desktop: {env.get('XDG_CURRENT_DESKTOP') or 'unknown'}, {session} session",
    ]
    gpus = _gpus()
    lines += [f"Graphics card: {gpu}" for gpu in gpus] or ["Graphics card: unknown"]
    lines.append(f"NVIDIA driver: {_nvidia_driver() or 'none'}")
    return lines


def build_report(version: str, model: SetupModel, log_dir: Path, system: list[str] | None = None) -> str:
    graphics = model.graphics_label if "graphics" in model.installed else "unknown"
    out = ["BFME Installer diagnostics", f"Version: {version}", f"Runner: {model.installed.get('runner', 'unknown')}",
           f"Graphics: {graphics}"]
    out += system_lines() if system is None else system
    out.append("Setup: " + ", ".join(f"{k} {model.installed.get(k, 'unknown')}" for k in ("prefix", "launcher", "arena")))
    out.append("Games: " + ", ".join(f"{name} {model.installed.get(key, 'unknown')}" for key, name in GAMES))
    out += ["", "System checks:"]
    if model.checks:
        marks = {"ok": "ok", "warn": "warning", "fail": "FAILED"}
        for cid, level, message, fix in model.check_rows:
            out.append(f"  [{marks[level]}] {message}")
            if fix:
                out.append(f"      fix: {fix}")
    else:
        out.append("  (not run yet)")
    for title, prefix in (("AIO Launcher", "launcher"), ("Arena", "arena"), ("prefix creation", "prefix-create")):
        log = newest_log(log_dir, prefix)
        out += ["", f"--- latest {title} log ({log.name}, last {LOG_LINES} lines) ---" if log else f"--- no {title} log ---"]
        if log:
            out.append(tail(log))
    return "\n".join(out) + "\n"
