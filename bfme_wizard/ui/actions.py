"""What the pages ask the window to do: tell the player something, copy, open a file or folder, ask before deleting,
and start the controller's work with a toast for how it went."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk  # noqa: E402

from ..engine.paths import Paths
from ..engine.programs import program
from ..services.diagnostics import Diagnostics
from .dialogs import confirm

if TYPE_CHECKING:
    from .window import WizardWindow

CLOSE_FIRST = "Close the AIO Launcher, the Arena and Age of the Ring first."


class WindowActions:
    def __init__(self, window: WizardWindow) -> None:
        self.window = window
        self.controller = window.controller

    # Telling the player

    def toast(self, text: str) -> Adw.Toast:
        toast = Adw.Toast.new(text)
        self.window.toasts.add_toast(toast)
        return toast

    def copy(self, text: str, toast: str) -> None:
        self.window.get_clipboard().set_content(Gdk.ContentProvider.new_for_value(GObject.Value(str, text)))
        self.toast(toast)

    def not_now(self) -> None:
        """The controller refused: say why."""
        self.toast(self.controller.blocked_reason() or "Not now.")

    def quit(self) -> None:
        self.window.get_application().quit()

    # Files and folders

    def copy_diagnostics(self) -> None:
        paths = Paths.of()
        report = Diagnostics(paths.logs, paths=paths).report(self.window.updater.local or "dev", self.controller.model)
        self.copy(report, "Diagnostics copied. Check it before you share it.")

    def open_logs(self) -> None:
        logs = Paths.of().logs
        target = Diagnostics(logs).any_log()

        if target is None:
            self.toast("There are no logs yet.")
            return

        def opened(launcher: Gtk.FileLauncher, result: Gio.AsyncResult) -> None:
            try:
                launcher.open_containing_folder_finish(result)
            except GLib.Error:
                self.toast(f"Could not open it. The logs are in {logs}")

        Gtk.FileLauncher.new(Gio.File.new_for_path(str(target))).open_containing_folder(self.window, None, opened)

    def open_config(self) -> None:
        config = Paths.of().config

        if not config.is_file():
            self.toast("There is no settings file yet. The first setup creates it.")
            return

        self._open(config, "file")

    def open_folder(self, folder: Path) -> None:
        self._open(folder, "folder")

    def _open(self, path: Path, what: str) -> None:
        """Open a file or folder with the player's program for it. When that fails, say where it is."""

        def opened(launcher: Gtk.FileLauncher, result: Gio.AsyncResult) -> None:
            try:
                launcher.launch_finish(result)
            except GLib.Error:
                toast = self.toast(f"Could not open it. The {what} is {path}")
                toast.set_button_label("Copy path")
                toast.connect("button-clicked", lambda *_: self.copy(str(path), "Path copied"))

        Gtk.FileLauncher.new(Gio.File.new_for_path(str(path))).launch(self.window, None, opened)

    # The controller's work

    def install_program(self, key: str) -> None:
        """Install from the Programs page. The setup shows on the main page, so leave this one first."""
        self.window.nav.pop_to_page(self.window.root_page)
        self.controller.install([program(key).job])

    def confirm_remove(self, key: str) -> None:
        info = program(key)
        confirm(
            self.window,
            f"Remove {info.name}?",
            f"{info.removal}\n\nYou can install it again from the Programs page.\n\n{CLOSE_FIRST}",
            "Remove",
            lambda: self.remove(key),
        )

    def remove(self, key: str) -> None:
        name = program(key).name

        def done(ok: bool) -> None:
            if ok:
                self.toast(f"{name[:1].upper()}{name[1:]} was removed.")
                return

            error = self.controller.model.error  # still there: the setup is looked at again right after this

            if error:
                self.toast(f"Could not remove {name}: {error.message}")
            else:
                self.toast(f"Could not remove {name}.")

        if not self.controller.remove(key, done):
            self.not_now()

    def confirm_reset(self) -> None:
        confirm(
            self.window,
            "Delete the game environment?",
            "This deletes the game environment, including every game you installed and Age of the Ring. "
            f"This cannot be undone.\n\n{CLOSE_FIRST}",
            "Delete and set up again",
            self.reset,
        )

    def reset(self) -> None:
        def done(ok: bool) -> None:
            if ok:
                self.toast("The game environment was deleted.")
            else:
                self.toast("The reset failed. Open the logs folder from Troubleshoot.")

        if self.controller.reset(done):
            self.window.nav.pop_to_page(self.window.root_page)
        else:
            self.not_now()

    def change_graphics(self, backend: str) -> None:
        """Switch the graphics backend. The page shows the new one once the setup has saved it."""
        name = "OpenGL" if backend == "opengl" else "Vulkan"

        def done(ok: bool) -> None:
            if ok:
                self.toast(f"Now using {name}. It takes effect the next time you open a program.")
            else:
                self.toast(f"Could not switch to {name}. Open the logs folder from Troubleshoot.")

        if not self.controller.set_graphics(backend, done):
            self.not_now()

    def change_option(self, option: str, value: str | int) -> None:
        """Save one of the other graphics settings. The page shows it once the setup has saved it."""

        def done(ok: bool) -> None:
            if ok:
                self.toast("Saved. It takes effect the next time you open a program.")
            else:
                self.toast("Could not save the setting. Open the logs folder from Troubleshoot.")

        if not self.controller.set_option(option, value, done):
            self.not_now()

            # Put the row back to what is saved.
            if self.window.troubleshoot is not None:
                self.window.troubleshoot.refresh(force=True)
