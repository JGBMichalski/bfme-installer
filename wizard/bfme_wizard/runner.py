"""Run one setup job at a time on a worker thread, and pass what it reports to the main loop. GLib only, no GTK."""
from __future__ import annotations

import threading
from collections.abc import Callable

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib  # noqa: E402

from .engine.events import Emit, Error, Event  # noqa: E402

# A job from engine/jobs.py with its own arguments already given: it takes (emit, cancel) and returns an exit status.
Job = Callable[[Emit, threading.Event], int]


class JobRunner:
    """One job at a time. Its events and its end reach the main loop in the order they happened."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()

    @property
    def busy(self) -> bool:
        """Return True if a job is currently running."""
        return self._thread is not None

    def run(self, job: Job, on_event: Callable[[Event], None], on_exit: Callable[[int], None]) -> None:
        """Start the job. on_event is called with each event, then on_exit with its exit status, all on the main loop. Raises RuntimeError if a job is already running."""
        if self._thread is not None:
            raise RuntimeError("a job is already running")

        self._cancel = threading.Event()
        cancel = self._cancel

        def emit(event: Event) -> None:
            """Emit an event to the main loop."""
            GLib.idle_add(_once, on_event, event)

        def finished(code: int) -> None:
            """Handle the job's completion on the main loop."""
            self._thread = None
            on_exit(code)

        def work() -> None:
            """Run the job in a separate thread."""
            try:
                code = job(emit, cancel)
            except Exception as error:   # a bug in a job must not leave the wizard waiting for ever
                emit(Error(None, f"Something went wrong: {error}"))
                code = 1

            GLib.idle_add(_once, finished, code)

        self._thread = threading.Thread(target=work, daemon=True)
        self._thread.start()

    def request_cancel(self) -> None:
        """Ask the job to stop. It stops before its next step, or at once while it downloads, unpacks or waits."""
        self._cancel.set()

    def terminate(self) -> None:
        """Stop now. A job has no process of its own to end, so this is the same request: the parts that can take long
        (downloads, unpacking, the installers) stop at once."""
        self._cancel.set()


def _once(callback: Callable, value: object) -> bool:
    """Call the callback with the given value once, then return False to remove it from the idle loop."""
    callback(value)
    return False   # an idle callback that returns True would run again
