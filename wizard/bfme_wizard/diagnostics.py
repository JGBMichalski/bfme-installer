"""The text behind "Copy diagnostics", and where the logs are. No GTK.

The report is for pasting into a bug report. It can contain the player's home folder and user name (log lines often
do), so the window tells them to check it before sharing.
"""
from __future__ import annotations

import os
from pathlib import Path

from .model import GAMES, SetupModel

LOG_LINES = 40


def data_dir(environ: dict[str, str] | None = None) -> Path:
    """The setup's data folder, the same place the script uses (BFME_HOME, else XDG_DATA_HOME/bfme-installer)."""
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
    """Some file in the logs folder, to show it in a file manager (None when there are no logs yet)."""
    files = sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime) if log_dir.is_dir() else []
    return files[-1] if files else None


def tail(path: Path, lines: int = LOG_LINES) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        return f"(could not read: {error})"
    return "\n".join(text.splitlines()[-lines:])


def build_report(version: str, model: SetupModel, log_dir: Path) -> str:
    out = ["BFME Installer diagnostics", f"Version: {version}", f"Runner: {model.installed.get('runner', 'unknown')}"]
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
    for title, prefix in (("launcher", "launcher"), ("Arena", "arena"), ("prefix creation", "prefix-create")):
        log = newest_log(log_dir, prefix)
        out += ["", f"--- latest {title} log ({log.name}, last {LOG_LINES} lines) ---" if log else f"--- no {title} log ---"]
        if log:
            out.append(tail(log))
    return "\n".join(out) + "\n"
