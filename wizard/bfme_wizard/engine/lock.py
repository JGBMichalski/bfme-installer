"""One setup at a time, so two never write the same files.

The lock is an flock on <data dir>/.setup.lock, the same file and kind of lock the setup script took, so the two keep each other
out while both exist.
"""

from __future__ import annotations

import fcntl
import os
from collections.abc import Generator
from contextlib import contextmanager

from .errors import SetupError
from .paths import Paths


def busy_message(environ: dict[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    app_id = env.get("FLATPAK_ID")

    if app_id:
        return (
            f"Another setup is already running. Wait for it to finish. If you stopped one earlier and it is stuck, run: "
            f"flatpak kill {app_id}"
        )

    return "Another setup is already running. Wait for it to finish."


@contextmanager
def setup_lock(paths: Paths, environ: dict[str, str] | None = None) -> Generator[None]:
    """Hold the setup lock for the `with` block. Fails at once when another setup holds it."""
    paths.base.mkdir(parents=True, exist_ok=True)

    with open(paths.base / ".setup.lock", "w", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SetupError(busy_message(environ)) from None

        # Closing the file releases the lock, also when the block fails.
        yield
