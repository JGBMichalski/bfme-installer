"""What's new: the changelog's notes for the versions a player has not seen yet, shown once after an update. No GTK.

The build puts CHANGELOG.md in the app. The last version whose notes were shown is kept in the data folder.
"""

from __future__ import annotations

import re
from pathlib import Path

from .engine.paths import Paths
from .updater import parse_version

CHANGELOG = Path("/app/share/bfme-installer/CHANGELOG.md")
LAST_VERSION_FILE = "last-version"


def sections(text: str) -> list[tuple[str, str]]:
    """(version, notes) for each "## [x.y.z]" section of the changelog, in the order they appear: newest first."""
    found = []
    version = None
    lines: list[str] = []

    for line in text.splitlines():
        heading = re.match(r"## \[(\d+\.\d+\.\d+)\]", line)

        if heading or line.startswith("## "):
            if version is not None:
                found.append((version, "\n".join(lines).strip()))

            version = heading.group(1) if heading else None
            lines = []
        elif version is not None:
            lines.append(line)

    if version is not None:
        found.append((version, "\n".join(lines).strip()))

    return found


def notes_since(text: str, seen: str | None, current: str) -> list[tuple[str, str]]:
    """The sections newer than `seen`, up to and including `current`, newest first. Without `seen`, only `current`'s."""
    current_number = parse_version(current)
    seen_number = parse_version(seen) if seen else None
    out = []

    for version, notes in sections(text):
        number = parse_version(version)

        if number is None or number > current_number:
            continue

        if seen_number is None and number != current_number:
            continue

        if seen_number is not None and number <= seen_number:
            continue

        out.append((version, notes))

    return out


class WhatsNew:
    """The notes a player has not seen yet. The last version whose notes were shown is kept in the data folder."""

    def __init__(self, paths: Paths, current: str | None, changelog: Path = CHANGELOG) -> None:
        self.paths = paths
        self.current = current
        self.changelog = changelog

    @property
    def marker(self) -> Path:
        return self.paths.base / LAST_VERSION_FILE

    def to_show(self) -> list[tuple[str, str]]:
        """The notes to show now, once: empty for a development build, a first install, or a version already shown."""
        paths = self.paths
        current = self.current

        if parse_version(current) is None:
            return []

        seen = None

        if self.marker.is_file():
            seen = self.marker.read_text().strip()

        if seen == current:
            return []

        # No marker: a first install shows nothing; an update from a version that kept none (2.x) shows this version's
        # notes.
        first_install = seen is None and not paths.config.exists() and not paths.prefix.exists()

        paths.base.mkdir(parents=True, exist_ok=True)
        self.marker.write_text(current + "\n")

        if first_install:
            return []

        try:
            text = self.changelog.read_text(encoding="utf-8")
        except OSError:
            return []

        return notes_since(text, seen, current)


def markup(notes: str) -> str:
    """A changelog section as Pango markup: headings in bold, bullets, **bold** and `code`. Links keep only their text."""
    out = []

    for line in notes.splitlines():
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
        text = re.sub(r"`([^`]+)`", r"<tt>\1</tt>", text)

        if text.startswith("### "):
            text = f"<b>{text[4:]}</b>"
        elif text.startswith("- "):
            text = "• " + text[2:]

        out.append(text)

    return "\n".join(out)
