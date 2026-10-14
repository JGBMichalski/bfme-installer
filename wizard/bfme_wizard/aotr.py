"""The step where the player downloads Age of the Ring from ModDB and picks the file.

A bot check blocks non-browser downloads. The system file chooser works in the Flatpak sandbox without extra permission.
"""
from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from .catalog import AOTR_DOWNLOAD_GB as DOWNLOAD_GB
from .widgets import pill

MODDB_URL = "https://www.moddb.com/mods/the-horse-lords-a-total-modification-for-bfme/downloads/age-of-the-ring-version-90"
SPACE_GB = 40
INTRO = (
    "It comes with its own launcher and its own copy of the games, so the games you already have stay as they are. "
    "ModDB only lets a web browser download it, so you do that part and this app does the rest."
)


class AotrDownloadPage:
    def __init__(self, open_moddb: Callable[[], None], choose_file: Callable[[], None],
                 leave: Callable[[], None]) -> None:
        self.view = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        clamp = Adw.Clamp(maximum_size=560, margin_top=16, margin_bottom=16, margin_start=18, margin_end=18)
        # Keep tight so Choose file stays visible at the default window height.
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.count = Gtk.Label(css_classes=["dim-label"])
        box.append(self.count)
        box.append(Gtk.Label(label="Download Age of the Ring", css_classes=["title-1"], wrap=True,
                             justify=Gtk.Justification.CENTER))
        box.append(Gtk.Label(
            label=f"The download is {DOWNLOAD_GB} GB, and installing needs about {SPACE_GB} GB more free space.",
            css_classes=["heading"], wrap=True, justify=Gtk.Justification.CENTER,
        ))
        box.append(Gtk.Label(label=INTRO, wrap=True, justify=Gtk.Justification.CENTER, css_classes=["dim-label"]))

        steps = Adw.PreferencesGroup()
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
                "Do not unpack it. When the install is done you can delete it."
            ),
            subtitle_lines=4,
        )
        choose = Gtk.Button(label="Choose file...", valign=Gtk.Align.CENTER, css_classes=["pill", "suggested-action"])
        choose.connect("clicked", lambda *_: choose_file())
        third.add_suffix(choose)
        steps.add(third)
        box.append(steps)

        # The download is 14 GB, so the player may want to leave.
        self.leave_button = pill("Not now", leave, suggested=False)
        box.append(self.leave_button)
        clamp.set_child(box)
        self.view.set_child(clamp)

    def refresh(self, number: int, total: int, leave_label: str) -> None:
        self.count.set_text(f"Step {number} of {total}")
        self.leave_button.set_label(leave_label)
