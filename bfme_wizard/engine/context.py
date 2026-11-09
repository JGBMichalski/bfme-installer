"""What an action in the game environment works with. A running job is one; a test can make its own."""

from __future__ import annotations

import threading

from .config import Config
from .errors import JobCancelled, SetupError
from .events import Emit
from .paths import Paths
from .proton import Proton


class Context:
    """The data folder, the player's settings, where events go, the player's stop, and the Proton that is ready.

    Asking where something is (a program's file, whether the prefix is ready) only needs `paths`. Doing something
    (installing, opening, removing, changing the game environment) takes a context.
    """

    def __init__(
        self,
        paths: Paths,
        config: Config | None = None,
        emit: Emit | None = None,
        cancel: threading.Event | None = None,
        environ: dict[str, str] | None = None,
        proton: Proton | None = None,
    ) -> None:
        self.paths = paths
        self.config = config or Config()
        self.emit: Emit = emit or self._ignore
        self.cancel = cancel or threading.Event()
        self.environ = environ
        self._proton = proton

    @staticmethod
    def _ignore(_event) -> None:
        return

    @property
    def proton(self) -> Proton:
        """The Proton that runs programs. A job gets it ready first (Job.ensure_runner)."""
        if self._proton is None:
            raise SetupError("Proton is not ready yet.")

        return self._proton

    @proton.setter
    def proton(self, proton: Proton) -> None:
        self._proton = proton

    def renew_proton(self) -> None:
        """After the config changed: Proton with the new settings. A Proton the caller chose (its path) stays."""
        path = None

        if self._proton is not None:
            path = self._proton.chosen_path

        self._proton = Proton(self.paths, self.config, path, self.environ)

    def stop_if_asked(self) -> None:
        """Stop if the player asked for it."""
        if self.cancel.is_set():
            raise JobCancelled()
