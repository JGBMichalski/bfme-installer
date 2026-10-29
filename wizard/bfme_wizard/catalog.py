"""The programs a player can install, open and remove, with the words and the picture for each. No GTK.

The home screen's cards, the Programs page's rows and the confirmation before a removal all say the same things about the
same programs, so those things are written once, here.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Where the programs' pictures are: one PNG for each, named for its key. Files shipped with the wizard, so they show with no
# network.
ICONS_DIR = Path(__file__).resolve().parent / "icons"

# Age of the Ring 9.3.0. Shown to the player, so they know what they are in for before they start.
AOTR_DOWNLOAD_GB = 14
AOTR_INSTALLED_GB = 22


@dataclass(frozen=True)
class Program:
    key: str                  # what the setup script calls it
    title: str                # on a card and in a list
    name: str                 # in a sentence
    summary: str              # what it is
    removal: str              # what removing it deletes, and what it leaves alone
    before_install: str = ""  # what the player should know first

    @property
    def icon(self) -> Path:
        """The program's own picture. Read from ICONS_DIR when it is asked for, so a test can point it somewhere else."""
        return ICONS_DIR / f"{self.key}.png"


CATALOG: tuple[Program, ...] = (
    Program(
        "launcher", "AIO Launcher", "the AIO Launcher",
        "Install, patch and start your games",
        "Its files and settings are deleted. The games it installed, the Arena and Age of the Ring are not touched.",
    ),
    Program(
        "arena", "Arena", "the Arena",
        "Play online matches against other players",
        "Its files and settings are deleted. The AIO Launcher, the games and Age of the Ring are not touched.",
    ),
    Program(
        "aotr", "Age of the Ring", "Age of the Ring",
        "A large mod with its own launcher",
        f"It and its own copy of the games are deleted, which frees about {AOTR_INSTALLED_GB} GB. Your settings for it are "
        "kept. The AIO Launcher, the Arena and the games you installed with the AIO Launcher are not touched.",
        f"You download it first, about {AOTR_DOWNLOAD_GB} GB.",
    ),
)

# Extra programs, listed on the Tools page. They are not part of the setup, so the home screen has no card for them.
TOOLS: tuple[Program, ...] = (
    Program(
        "workshop", "Workshop Studio", "Workshop Studio",
        "Create workshop packages and publish them to the BFME Workshop",
        "Its folder is deleted. The AIO Launcher, the Arena, Age of the Ring and the games are not touched.",
        "About 300 MB to download.",
    ),
    Program(
        "mission-control", "Mission Control", "Mission Control",
        "For Arena operators, patch developers, event organizers and moderators",
        "Its folder is deleted. The AIO Launcher, the Arena, Age of the Ring and the games are not touched.",
        "About 300 MB to download.",
    ),
)

# Installing one of these installs the other when it is missing: the Arena only plays what the AIO Launcher installs.
INSTALLED_TOGETHER = {"launcher": "arena", "arena": "launcher"}


def program(key: str) -> Program:
    return next(p for p in (*CATALOG, *TOOLS) if p.key == key)
