"""The logs of a program's starts: one file per start, <name>-<date>-<time>.log, of which the newest few are kept."""

from __future__ import annotations

import re
import time
from pathlib import Path


class RunLogs:
    KEEP = 10

    def __init__(self, folder: Path, name: str) -> None:
        self.folder = folder
        self.name = name

    def new(self) -> Path:
        """The file for a start now."""
        self.folder.mkdir(parents=True, exist_ok=True)
        return self.folder / f"{self.name}-{time.strftime('%Y%m%d-%H%M%S')}.log"

    def started(self) -> list[Path]:
        """The logs of the starts, newest first. Only <name>-<date>-<time>.log: aio-launcher-setup.log is not one."""
        pattern = re.compile(rf"{re.escape(self.name)}-\d{{8}}-\d{{6}}\.log")
        found = []

        for log in self.folder.glob(f"{self.name}-*.log"):
            if pattern.fullmatch(log.name):
                found.append((log.stat().st_mtime, log))

        found.sort(reverse=True)
        newest_first = []

        for _mtime, log in found:
            newest_first.append(log)

        return newest_first

    def remove_old(self) -> None:
        """Keep only the newest KEEP."""
        for log in self.started()[self.KEEP :]:
            log.unlink(missing_ok=True)
