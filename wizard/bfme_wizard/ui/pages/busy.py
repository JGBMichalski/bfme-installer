"""A page that only says what is going on, with a spinner: checking the setup, removing a program."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402


class BusyPage:
    def __init__(self, title: str) -> None:
        self.view = Adw.StatusPage(title=title)
        spinner = Gtk.Spinner(spinning=True, halign=Gtk.Align.CENTER)
        spinner.set_size_request(32, 32)
        self.view.set_child(spinner)

    def set_title(self, title: str) -> None:
        self.view.set_title(title)
