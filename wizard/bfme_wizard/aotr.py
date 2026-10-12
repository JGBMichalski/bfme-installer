"""The page that walks a player through downloading Age of the Ring from ModDB and handing the file to the wizard.

ModDB only lets a web browser download the file (a bot check stands in front of it), so the player does that part.
The wizard opens the page, then asks for the downloaded file with the system file chooser. That chooser works inside
the Flatpak sandbox without any extra permission.
"""
from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

MODDB_URL = "https://www.moddb.com/mods/the-horse-lords-a-total-modification-for-bfme/downloads/age-of-the-ring-version-90"
DOWNLOAD_GB = 14
SPACE_GB = 40


class AotrInstallPage:
    def __init__(self, open_moddb: Callable[[], None], choose_file: Callable[[], None]) -> None:
        self.view = Adw.ToolbarView()
        self.view.add_top_bar(Adw.HeaderBar())
        page = Adw.PreferencesPage(
            title="Install Age of the Ring",
            description=(
                "Age of the Ring is a big mod with its own Launcher and its own copy of the games, so it does not "
                "touch the games you already have. ModDB only lets a web browser download it, so you download the "
                "file and this app does the rest."
            ),
        )

        need = Adw.PreferencesGroup(title="Before you start")
        need.add(Adw.ActionRow(
            title=f"The download is {DOWNLOAD_GB} GB",
            subtitle=f"Installing needs about {SPACE_GB} GB more free space, on top of the file you download.",
            subtitle_lines=3,
        ))
        page.add(need)

        steps = Adw.PreferencesGroup(title="Steps")
        first = Adw.ActionRow(
            title="1. Open the download page",
            subtitle="It opens in your web browser.", subtitle_lines=2,
        )
        button = Gtk.Button(label="Open ModDB", valign=Gtk.Align.CENTER, css_classes=["pill"])
        button.connect("clicked", lambda *_: open_moddb())
        first.add_suffix(button)
        steps.add(first)
        steps.add(Adw.ActionRow(
            title="2. Click Download Now",
            subtitle=(
                "Wait until your browser has finished the whole file. If ModDB asks you to prove you are "
                "human, do that first."
            ),
            subtitle_lines=4,
        ))
        third = Adw.ActionRow(
            title="3. Choose the file you downloaded",
            subtitle=GLib.markup_escape_text(
                "It is named like AotR_Standalone_9.3.0_Installer.zip and is usually in your Downloads folder. "
                "Do not unpack it."
            ),
            subtitle_lines=4,
        )
        choose = Gtk.Button(label="Choose file...", valign=Gtk.Align.CENTER, css_classes=["pill", "suggested-action"])
        choose.connect("clicked", lambda *_: choose_file())
        third.add_suffix(choose)
        steps.add(third)
        page.add(steps)

        after = Adw.PreferencesGroup()
        after.set_description("When the install is done you can delete the file you downloaded.")
        page.add(after)
        self.view.set_content(page)
