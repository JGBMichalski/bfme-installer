"""The banner that offers a new release: Update, then Restart into it. Hidden while a setup runs."""

from __future__ import annotations

from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib  # noqa: E402

from ..services.updater import Updater

if TYPE_CHECKING:
    from .window import WizardWindow


class UpdateBanner:
    def __init__(self, window: WizardWindow) -> None:
        self.window = window
        self.updater = Updater.from_environment(self.refresh)
        self.view = Adw.Banner(use_markup=False)
        self.view.connect("button-clicked", self._pressed)

    def refresh(self) -> None:
        u = self.updater

        if u.state == "idle" or self.window.model.state == "running":
            self.view.set_revealed(False)
            return

        if u.state == "available":
            title, button = f"Version {u.remote} is available (you have {u.local}).", "Update"
        elif u.state == "updating":
            title, button = "Updating..." if u.progress is None else f"Updating... {u.progress}%", None
        elif u.state == "done":
            title, button = f"Updated to {u.remote}. Restart BFME Installer to use it.", "Restart"
        elif u.state == "empty":
            title, button = f"Version {u.remote} is not ready to download yet. Try again in a few minutes.", "Try again"
        else:  # failed
            title, button = f"Could not update automatically. In a terminal, run: {u.manual_command}", "Copy command"

        self.view.set_title(title)
        self.view.set_button_label(button)
        self.view.set_revealed(True)

    def _pressed(self, _banner) -> None:
        state = self.updater.state

        if state in ("available", "empty"):
            self.updater.install()
        elif state == "done":
            self.restart()
        elif state == "failed":
            self.window.actions.copy(self.updater.manual_command, "Command copied")

    def restart(self) -> None:
        """Start the new version, then quit. If it cannot be started, close and let the player reopen it."""
        try:
            Gio.Subprocess.new(self.updater.restart_command(), Gio.SubprocessFlags.NONE)
        except GLib.Error:
            self.window.close()
            return

        self.window.get_application().quit()
