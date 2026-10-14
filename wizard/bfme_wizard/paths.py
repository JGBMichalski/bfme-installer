"""Where the game folders are inside the game environment. No GTK.

Mirrors BASE, PREFIX and WINE_USER in scripts/bfme-linux-setup.sh.
"""
from __future__ import annotations

import getpass
import os
from dataclasses import dataclass
from pathlib import Path

from .diagnostics import data_dir
from .model import GAMES

# Per game: folder under drive_c, and the user-data folder under AppData/Roaming made on first start.
GAME_DIRS = {
    "bfme1": ("BFME1", "My Battle for Middle-earth Files"),
    "bfme2": ("BFME2", "My Battle for Middle-earth II Files"),
    "rotwk": ("RotWK", "My Rise of the Witch-king Files"),
}
# Age of the Ring is not a game of this list: it has its own copies of the games in C:\AgeoftheRing, and keeps its settings and
# maps in AppData\Roaming\Age of the Ring (the registry's UserDataLeafName for its Rise of the Witch-king copy), not in a
# "My ... Files" folder. Its maps folder is lowercase, as the Age of the Ring Launcher makes it.
AOTR = ("aotr", "Age of the Ring", "AgeoftheRing", "Age of the Ring", "maps")


@dataclass(frozen=True)
class GameFolders:
    key: str
    name: str
    game: Path
    user_data: Path
    maps_dir: str = "Maps"    # the folder for maps inside user_data; the games' is "Maps", Age of the Ring's is "maps"

    @property
    def installed(self) -> bool:
        return self.game.is_dir()

    def maps_target(self) -> Path:
        """First existing of: the maps folder, the user-data folder, the game folder."""
        for path in (self.user_data / self.maps_dir, self.user_data, self.game):
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
    return "steamuser"  # Proton always uses steamuser


def game_folders(environ: dict[str, str] | None = None) -> list[GameFolders]:
    prefix = prefix_dir(environ)
    roaming = prefix / "drive_c" / "users" / wine_user(environ) / "AppData" / "Roaming"
    names = dict(GAMES)
    games = [GameFolders(key, names[key], prefix / "drive_c" / folder, roaming / user_data)
             for key, (folder, user_data) in GAME_DIRS.items()]
    key, name, folder, user_data, maps_dir = AOTR
    return games + [GameFolders(key, name, prefix / "drive_c" / folder, roaming / user_data, maps_dir)]
