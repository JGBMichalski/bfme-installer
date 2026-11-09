"""The games in the game environment: where each one's files, settings and maps are. No GTK."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .paths import Paths


@dataclass(frozen=True)
class Game:
    key: str
    name: str
    folder: str  # under drive_c
    user_data_folder: str  # under AppData/Roaming, made on the game's first start
    exe: str  # the game's program in its folder; a game counts as installed once it is there
    installed_by: str  # the key of the program that installs it
    maps_folder: str = "Maps"  # in the user-data folder

    def game_dir(self, paths: Paths) -> Path:
        return paths.drive_c / self.folder

    def user_data(self, paths: Paths) -> Path:
        return paths.roaming / self.user_data_folder

    def installed(self, paths: Paths) -> bool:
        return (self.game_dir(paths) / self.exe).is_file()

    def has_folders(self, paths: Paths) -> bool:
        """Whether there is a game folder to open."""
        return self.game_dir(paths).is_dir()

    def maps_target(self, paths: Paths) -> Path:
        """First existing of: the maps folder, the user-data folder, the game folder."""
        user_data = self.user_data(paths)

        for path in (user_data / self.maps_folder, user_data, self.game_dir(paths)):
            if path.is_dir():
                return path

        return self.game_dir(paths)


# Every game, in order: the three the AIO Launcher installs, then Age of the Ring's own copies of them in
# C:\AgeoftheRing. Age of the Ring keeps its settings and maps in AppData\Roaming\Age of the Ring, in a lowercase "maps"
# folder its launcher makes.
GAMES: tuple[Game, ...] = (
    Game(
        key="bfme1",
        name="BFME",
        folder="BFME1",
        user_data_folder="My Battle for Middle-earth Files",
        exe="lotrbfme.exe",
        installed_by="aio-launcher",
    ),
    Game(
        key="bfme2",
        name="BFME 2",
        folder="BFME2",
        user_data_folder="My Battle for Middle-earth II Files",
        exe="lotrbfme2.exe",
        installed_by="aio-launcher",
    ),
    Game(
        key="rotwk",
        name="Rise of the Witch-king",
        folder="RotWK",
        user_data_folder="My Rise of the Witch-king Files",
        exe="lotrbfme2ep1.exe",
        installed_by="aio-launcher",
    ),
    Game(
        key="aotr-games",
        name="Age of the Ring",
        folder="AgeoftheRing",
        user_data_folder="Age of the Ring",
        exe="AotR_Launcher.exe",
        installed_by="aotr",
        maps_folder="maps",
    ),
)
