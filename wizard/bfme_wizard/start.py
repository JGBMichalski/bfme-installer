"""The start page, where the player chooses programs. It returns after a stop, with a Resume button."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from .controller import Controller
from .widgets import first_icon, pill

# (program, title, description) in install order. The Arena comes with the AIO Launcher.
CHOICES = [
    ("launcher", "All-in-One Launcher",
     "Install, patch and play the BFME games. Includes the Online Arena for multiplayer."),
    ("aotr", "Age of the Ring",
     "A large mod with its own launcher and its own copy of the games. You download it from ModDB, about 14 GB."),
]
FRESH = ("Set up BFME on Linux", "Choose what to install.")
READY = ("Choose what to install", "Your game environment is ready.")
PAUSED = ("Setup paused", "Resume where you left off, or change what to install.")


class StartPage:
    def __init__(self, controller: Controller) -> None:
        self.controller = controller
        self.view = Adw.StatusPage(
            css_classes=["compact"],
            icon_name=first_icon("system-software-install-symbolic", "folder-download-symbolic", "emblem-system-symbolic"),
        )
        group = Adw.PreferencesGroup()
        self._checks: dict[str, Gtk.CheckButton] = {}
        for program, title, subtitle in CHOICES:
            check = Gtk.CheckButton(valign=Gtk.Align.CENTER, css_classes=["selection-mode"])
            check.connect("toggled", lambda *_: self.refresh())
            row = Adw.ActionRow(title=title, subtitle=GLib.markup_escape_text(subtitle), activatable_widget=check)
            row.add_prefix(check)
            group.add(row)
            self._checks[program] = check
        self.button = pill("Install", self._install)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        box.append(group)
        box.append(self.button)
        clamp = Adw.Clamp(maximum_size=520)
        clamp.set_child(box)
        self.view.set_child(clamp)

    @property
    def selected(self) -> tuple[str, ...]:
        """Ticked programs, in install order."""
        return tuple(program for program, check in self._checks.items() if check.get_active())

    def enter(self) -> None:
        """Tick the remembered choice."""
        chosen = set(self.controller.model.selection)
        for program, check in self._checks.items():
            check.set_active(program in chosen)
        self.refresh()

    def refresh(self) -> None:
        """Update text and buttons. Never changes the ticks."""
        m = self.controller.model
        title, description = PAUSED if m.paused else READY if m.environment_ready else FRESH
        self.view.set_title(title)
        self.view.set_description(description)
        self.button.set_label("Resume" if m.resumes(self.selected) else "Install")
        # The script ignores clicks while busy.
        self.button.set_sensitive(bool(self.selected) and not self.controller.checking)

    def _install(self) -> None:
        self.controller.install(self.selected)
