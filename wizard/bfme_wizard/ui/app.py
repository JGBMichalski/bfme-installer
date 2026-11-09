"""The application: one window, and the notes of what is new after an update."""

from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw  # noqa: E402

from ..control.controller import Controller
from ..engine.paths import Paths
from ..services import whatsnew
from .dialogs import show_whats_new
from .window import WizardWindow

# Flatpak builds under another ID run beside this one.
APP_ID = os.environ.get("FLATPAK_ID") or "com.jgbmichalski.BfmeInstaller"


class WizardApp(Adw.Application):
    def __init__(self, runner, offer: str | None = None, jobs=None) -> None:
        super().__init__(application_id=APP_ID)
        self.runner = runner
        self.offer = offer  # the program a shortcut wanted to open, when it was not installed (any more)
        self.jobs = jobs  # engine/jobs.py unless given; dev/screenshots.py gives a stand-in
        self.connect("activate", self._activate)

    def _activate(self, _app) -> None:
        """Activate the application, creating and presenting the main window if it does not already exist."""
        window = self.props.active_window
        if window is None:

            def controller(on_change):
                if self.jobs is None:
                    return Controller(self.runner, on_change, offer=self.offer)

                return Controller(self.runner, on_change, offer=self.offer, jobs=self.jobs)

            window = WizardWindow(self, controller)
            window.controller.start()
            window.present()
            # Once, after an update: what changed since the version the player last saw.
            notes = whatsnew.WhatsNew(Paths.of(), window.updater.local).to_show()

            if notes:
                show_whats_new(window, notes)

            return

        window.present()
