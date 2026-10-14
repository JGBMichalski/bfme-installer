"""The Programs page: install a program that is missing, or remove one that is installed.

It only shows the model and asks the window to act. The window asks the player to confirm a removal, because that deletes files.
"""
from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from .catalog import CATALOG, INSTALLED_TOGETHER, Program, program
from .controller import Controller
from .widgets import program_icon

ROW_ICON_SIZE = 40
DESCRIPTION = (
    "Install a program you skipped, or remove one you no longer use. "
    "Removing a program does not touch the games you installed with the AIO Launcher."
)


def _join(names: list[str]) -> str:
    """"the Arena", "the AIO Launcher and the Arena", "the AIO Launcher, the Arena and Age of the Ring"."""
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


class ProgramsPage:
    def __init__(self, controller: Controller, *, install: Callable[[str], None], remove: Callable[[str], None]) -> None:
        self.controller = controller
        self._install, self._remove = install, remove
        self.view = Adw.ToolbarView()
        self.view.add_top_bar(Adw.HeaderBar())
        self._key: tuple | None = None
        self._rows: list[Adw.ActionRow] = []
        self.refresh()

    def rows(self) -> list[Adw.ActionRow]:
        """The rows as they are now, one per program."""
        return list(self._rows)

    def refresh(self) -> None:
        """Rebuild the rows when what they show has changed, and not on every line of output: a button pressed or a dialog
        opened from a row must not be pulled away from under the player."""
        c, m = self.controller, self.controller.model
        key = (tuple(m.is_installed(p.key) for p in CATALOG), tuple(c.apps.state[p.key] for p in CATALOG),
               m.state, m.removing, c.checking)
        if key == self._key:
            return
        self._key = key
        running = [p for p in CATALOG if c.apps.state[p.key] == "running"]
        group = Adw.PreferencesGroup()
        self._rows = [self._row(info, running) for info in CATALOG]
        for row in self._rows:
            group.add(row)
        page = Adw.PreferencesPage(description=DESCRIPTION)
        page.add(group)
        self.view.set_content(page)

    def _row(self, info: Program, running: list[Program]) -> Adw.ActionRow:
        c, m = self.controller, self.controller.model
        row = Adw.ActionRow(title=info.title)
        row.add_prefix(program_icon(info, ROW_ICON_SIZE))
        if m.removing == info.key:
            row.set_subtitle("Removing...")
            row.add_suffix(Gtk.Spinner(spinning=True, valign=Gtk.Align.CENTER))
            return row
        if m.is_installed(info.key):
            row.set_subtitle(GLib.markup_escape_text(self._installed_text(info, running)))
            button = Gtk.Button(label="Remove", valign=Gtk.Align.CENTER, css_classes=["destructive-action"])
            # Removing ends the whole Wine session, so it also has to wait for a program that is not the one being removed.
            button.set_sensitive(c.blocked_reason() is None)
            button.connect("clicked", lambda *_: self._remove(info.key))
        else:
            row.set_subtitle(GLib.markup_escape_text(self._missing_text(info)))
            button = Gtk.Button(label="Install", valign=Gtk.Align.CENTER, css_classes=["suggested-action"])
            button.set_sensitive(not c.checking)   # the script ignores a click while it is busy
            button.connect("clicked", lambda *_: self._install(info.key))
        row.add_suffix(button)
        return row

    @staticmethod
    def _installed_text(info: Program, running: list[Program]) -> str:
        if info in running:
            return "Running. Close it to remove it."
        if running:
            return f"Installed. Close {_join([p.name for p in running])} to remove it."
        return "Installed"

    def _missing_text(self, info: Program) -> str:
        text = f"Not installed. {info.summary}."
        if info.before_install:
            text += f" {info.before_install}"
        partner = INSTALLED_TOGETHER.get(info.key)
        if partner and not self.controller.model.is_installed(partner):
            text += f" Installs {program(partner).name} too."
        return text
