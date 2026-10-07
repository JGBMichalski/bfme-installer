"""Where the game folders are inside the game environment. No GTK.

Mirrors the layout in scripts/bfme-linux-setup.sh (BASE, PREFIX, WINE_USER), so keep the two in step.
"""
from __future__ import annotations

import getpass
import os
from dataclasses import dataclass
from pathlib import Path

from .diagnostics import data_dir
from .model import GAMES

# Per game: the folder under drive_c, and the folder the game itself makes under AppData/Roaming on its first start.
GAME_DIRS = {
    "bfme1": ("BFME1", "My Battle for Middle-earth Files"),
    "bfme2": ("BFME2", "My Battle for Middle-earth II Files"),
    "rotwk": ("RotWK", "My Rise of the Witch-king Files"),
}


@dataclass(frozen=True)
class GameFolders:
    key: str
    name: str
    game: Path
    user_data: Path

    @property
    def installed(self) -> bool:
        return self.game.is_dir()

    def maps_target(self) -> Path:
        """The nearest folder that exists: Maps, then the user-data folder, then the game folder."""
        for path in (self.user_data / "Maps", self.user_data, self.game):
            if path.is_dir():
                return path
        return self.game


def prefix_dir(environ: dict[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    return data_dir(env) / ("wineprefix" if env.get("BFME_RUNNER", "proton") == "wine" else "prefix")


def wine_user(environ: dict[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    if env.get("BFME_RUNNER", "proton") == "wine":
        return env.get("USER") or getpass.getuser()
    return "steamuser"  # Proton always names the user steamuser


def game_folders(environ: dict[str, str] | None = None) -> list[GameFolders]:
    prefix = prefix_dir(environ)
    roaming = prefix / "drive_c" / "users" / wine_user(environ) / "AppData" / "Roaming"
    names = dict(GAMES)
    return [GameFolders(key, names[key], prefix / "drive_c" / folder, roaming / user_data)
            for key, (folder, user_data) in GAME_DIRS.items()]
