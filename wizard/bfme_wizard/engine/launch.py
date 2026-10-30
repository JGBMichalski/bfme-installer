"""Starting a program in the game environment, with a log of its own."""
from __future__ import annotations

import time
from pathlib import Path

from . import proton
from .config import Config
from .events import Emit, Log
from .paths import Paths

KEEP_LOGS = 10


def start_program(paths: Paths, config: Config, proton_path: str, log_name: str, exe: Path, label: str,
                  emit: Emit) -> int:
    """Run the program from its own folder and wait until it ends. Its output goes to <log_name>-<time>.log; the newest
    KEEP_LOGS of those are kept. Returns its exit status."""
    paths.logs.mkdir(parents=True, exist_ok=True)
    log = paths.logs / f"{log_name}-{time.strftime('%Y%m%d-%H%M%S')}.log"
    emit(Log(f"Starting {label}. Log: {log}"))

    with open(log, "w", encoding="utf-8") as out:
        code = proton.run(paths, config, proton_path, [str(exe)], inprefix=True, output=out, cwd=exe.parent)

    _remove_old_logs(paths.logs, log_name)

    return code


def _remove_old_logs(logs: Path, log_name: str) -> None:
    found = []

    for log in logs.glob(f"{log_name}-*.log"):
        found.append((log.stat().st_mtime, log))

    found.sort(reverse=True)

    for _mtime, log in found[KEEP_LOGS:]:
        log.unlink(missing_ok=True)
