"""One setup at a time, so two never write the same files."""

from __future__ import annotations

import fcntl
import os
from typing import IO

from .errors import SetupError
from .paths import Paths


class SetupLock:
    """An flock on <data dir>/.setup.lock, held for a `with` block. Entering fails at once when another setup holds it.
    Closing the file releases the lock, also when the block fails."""

    def __init__(self, paths: Paths, environ: dict[str, str] | None = None) -> None:
        self.paths = paths
        self.environ = environ
        self._file: IO | None = None

    def busy_message(self) -> str:
        env = os.environ if self.environ is None else self.environ
        app_id = env.get("FLATPAK_ID")

        if app_id:
            return (
                "Another setup is already running. Wait for it to finish. If you stopped one earlier and it is stuck, "
                f"run: flatpak kill {app_id}"
            )

        return "Another setup is already running. Wait for it to finish."

    def __enter__(self) -> SetupLock:
        self.paths.base.mkdir(parents=True, exist_ok=True)
        self._file = open(self.paths.base / ".setup.lock", "w", encoding="utf-8")  # noqa: SIM115

        try:
            fcntl.flock(self._file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._file.close()
            self._file = None
            raise SetupError(self.busy_message()) from None

        return self

    def __exit__(self, *_exc) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
