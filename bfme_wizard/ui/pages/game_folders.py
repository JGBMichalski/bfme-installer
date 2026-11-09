"""The Game folders page: one group per game, with its game folder and its maps and user data."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ...engine.games import GAMES
from ...engine.paths import Paths
from ..widgets import first_icon


class GameFoldersPage:
    """Game folders page: one group per game, one row per folder."""

    def __init__(self, open_folder: Callable[[Path], None]) -> None:
        self.view = Adw.ToolbarView()
        self.view.add_top_bar(Adw.HeaderBar())
        page = Adw.PreferencesPage(
            title="Game folders",
            description="Open a folder in your file manager to add maps or copy files.",
        )
        any_installed = False
        # A game that is not installed has no folders to open, so it has no group.
        paths = Paths.of()

        for game in GAMES:
            if not game.has_folders(paths):
                continue

            group = Adw.PreferencesGroup(title=GLib.markup_escape_text(game.name))
            for title, subtitle, target in (
                ("Game folder", "Installed files and patches", game.game_dir(paths)),
                ("Maps and user data", "Maps, replays and settings", game.maps_target(paths)),
            ):
                row = Adw.ActionRow(title=title, subtitle=subtitle, activatable=True)
                row.add_suffix(Gtk.Image.new_from_icon_name("folder-open-symbolic"))
                row.connect("activated", lambda *_, t=target: open_folder(t))
                group.add(row)
            page.add(group)
            any_installed = True
        if not any_installed:
            self.view.set_content(
                Adw.StatusPage(
                    title="No games installed",
                    description="Install a game with the AIO Launcher, and its folders will be here.",
                    icon_name=first_icon("folder-symbolic", "folder-open-symbolic"),
                )
            )
            return
        self.view.set_content(page)
