"""Where everything lives: the data folder, the game environment (prefix) and the programs in it."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Per game: folder under drive_c, and the user-data folder under AppData/Roaming made on first start.
GAME_DIRS = {
    "bfme1": ("BFME", "BFME1", "My Battle for Middle-earth Files"),
    "bfme2": ("BFME 2", "BFME2", "My Battle for Middle-earth II Files"),
    "rotwk": ("Rise of the Witch-king", "RotWK", "My Rise of the Witch-king Files"),
}
# Age of the Ring has its own copies of the games in C:\AgeoftheRing, and keeps its settings and maps in AppData\Roaming\Age of the Ring.
AOTR = ("aotr", "Age of the Ring", "AgeoftheRing", "Age of the Ring", "maps")
TOOL_FILES = {
    "workshop": ("Workshop Studio", "WorkshopStudio.exe"),
    "mission-control": ("Mission Control", "MissionControl.exe"),
}

def data_dir(environ: dict[str, str] | None = None) -> Path:
    """BFME_HOME, else XDG_DATA_HOME/bfme-installer. In the Flatpak XDG_DATA_HOME is the app's own data folder."""
    env = os.environ if environ is None else environ

    if env.get("BFME_HOME"):
        return Path(env["BFME_HOME"])

    base = Path(env["XDG_DATA_HOME"]) if env.get("XDG_DATA_HOME") else Path(env.get("HOME") or Path.home()) / ".local/share"
    return base / "bfme-installer"


def menu_dir(environ: dict[str, str] | None = None) -> Path:
    """The host's menu folder. The Flatpak's own XDG_DATA_HOME is not the host's, so this ignores it."""
    env = os.environ if environ is None else environ
    return Path(env.get("HOME") or Path.home()) / ".local/share/applications"


@dataclass(frozen=True)
class GameFolders:
    key: str
    name: str
    game: Path
    user_data: Path
    maps_dir: str = "Maps"

    @property
    def installed(self) -> bool:
        return self.game.is_dir()

    def maps_target(self) -> Path:
        """First existing of: the maps folder, the user-data folder, the game folder."""
        for path in (self.user_data / self.maps_dir, self.user_data, self.game):
            if path.is_dir():
                return path

        return self.game


@dataclass(frozen=True)
class Paths:
    base: Path

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
        return self.drive_c / "users/steamuser/AppData/Roaming"   # Proton always names the user steamuser

    @property
    def launcher_exe(self) -> Path:
        return self.roaming / "BFME All In One Launcher/AllInOneLauncher.exe"

    @property
    def arena_exe(self) -> Path:
        return self.roaming / "BFME Competetive Arena/BfmeFoundationProject_OnlineArena.exe"

    @property
    def aotr_exe(self) -> Path:
        return self.drive_c / "AgeoftheRing/AotR_Launcher.exe"

    @property
    def aotr_unpack(self) -> Path:
        return self.downloads / "aotr"

    def tool_exe(self, tool: str) -> Path:
        folder, exe = TOOL_FILES[tool]
        return self.drive_c / "BFME Tools" / folder / exe

    def game_folders(self) -> list[GameFolders]:
        games = []

        for key, (name, folder, user_data) in GAME_DIRS.items():
            games.append(GameFolders(
                key=key,
                name=name,
                game=self.drive_c / folder,
                user_data=self.roaming / user_data,
            ))

        key, name, folder, user_data, maps_dir = AOTR
        games.append(GameFolders(
            key=key,
            name=name,
            game=self.drive_c / folder,
            user_data=self.roaming / user_data,
            maps_dir=maps_dir,
        ))

        return games


def paths(environ: dict[str, str] | None = None) -> Paths:
    return Paths(data_dir(environ))
