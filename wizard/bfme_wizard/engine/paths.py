"""Where everything lives: the data folder and the game environment (prefix). Each program and game knows its own files
(engine/programs/, engine/games.py)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    base: Path

    @classmethod
    def of(cls, environ: dict[str, str] | None = None) -> Paths:
        """The paths of this app's data folder (data_dir)."""
        return cls(cls.data_dir(environ))

    @staticmethod
    def data_dir(environ: dict[str, str] | None = None) -> Path:
        """BFME_HOME, else XDG_DATA_HOME/bfme-installer. In the Flatpak XDG_DATA_HOME is the app's own data folder."""
        env = os.environ if environ is None else environ

        if env.get("BFME_HOME"):
            return Path(env["BFME_HOME"])

        if env.get("XDG_DATA_HOME"):
            base = Path(env["XDG_DATA_HOME"])
        else:
            base = Path(env.get("HOME") or Path.home()) / ".local/share"

        return base / "bfme-installer"

    @staticmethod
    def menu_dir(environ: dict[str, str] | None = None) -> Path:
        """The host's menu folder. The Flatpak's own XDG_DATA_HOME is not the host's, so this ignores it."""
        env = os.environ if environ is None else environ
        return Path(env.get("HOME") or Path.home()) / ".local/share/applications"

    @property
    def config(self) -> Path:
        return self.base / "config.env"

    @property
    def downloads(self) -> Path:
        return self.base / "downloads"

    @property
    def logs(self) -> Path:
        return self.base / "logs"

    @property
    def prefix(self) -> Path:
        return self.base / "prefix"

    @property
    def drive_c(self) -> Path:
        return self.prefix / "drive_c"

    @property
    def roaming(self) -> Path:
        return self.drive_c / "users/steamuser/AppData/Roaming"  # Proton always names the user steamuser
