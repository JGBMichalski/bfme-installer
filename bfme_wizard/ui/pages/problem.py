"""The page for a setup that cannot go on: the system needs a change (with the commands to run), or a step failed."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ...control.controller import Controller
from ...control.steps import STEPS
from ..widgets import clear, first_icon, pill

if TYPE_CHECKING:
    from ..actions import WindowActions


class ProblemPage:
    def __init__(self, controller: Controller, actions: WindowActions) -> None:
        self.controller = controller
        self.actions = actions
        self.view = Adw.StatusPage()
        clamp = Adw.Clamp(maximum_size=520)
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        clamp.set_child(self.box)
        self.view.set_child(clamp)

    def refresh(self) -> None:
        clear(self.box)

        if self.controller.model.state == "blocked":
            self._blocked()
        else:
            self._failed()

    def _blocked(self) -> None:
        m = self.controller.model
        self.view.set_icon_name(first_icon("dialog-warning-symbolic", "dialog-error-symbolic"))
        self.view.set_title("Your system needs a change")
        self.view.set_description(
            "Only your system can install these, and this app is not allowed to. "
            "Run each command in a terminal, then press Recheck."
        )
        problems = m.problems

        if problems:
            group = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])

            for problem in problems:
                group.append(self._row(problem.message, problem.command))

            self.box.append(group)
        elif m.error:
            self.box.append(Gtk.Label(label=m.error.message, wrap=True))

        missing_32bit = False

        for check_id, check in m.checks.items():
            if check_id == "flatpak-32bit" and check.level == "fail":
                missing_32bit = True

        # A running Flatpak mounts extensions at launch only. A fresh start is needed.
        if os.environ.get("FLATPAK_ID") and missing_32bit:
            self.box.append(
                Gtk.Label(
                    label="After the command finishes, close this window and open BFME Installer again.", wrap=True
                )
            )
            self.box.append(pill("Close", self.actions.quit))
        else:
            self.box.append(pill("Recheck", self.controller.recheck))

    def _failed(self) -> None:
        m = self.controller.model
        step = "the setup"

        if m.failed_step:
            step = STEPS.title_of(m.failed_step)

        message = "The setup stopped unexpectedly."

        if m.error:
            message = m.error.message

        self.view.set_icon_name(first_icon("dialog-error-symbolic", "dialog-warning-symbolic"))
        self.view.set_title("Something went wrong")
        self.view.set_description(f"{step}: {message}\n\nNothing was lost. You can try this step again.")
        self.box.append(pill("Retry", self.controller.retry))

        # One row: four stacked buttons do not fit.
        leave = "Back to start"

        if m.has_home_screen:
            leave = "Back to home"

        others = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
        others.append(pill(leave, self.controller.back_home, suggested=False))
        others.append(pill("Copy log", lambda: self.actions.copy(m.log_text(), "Log copied"), suggested=False))
        self.box.append(others)

    def _row(self, message: str, command: str | None) -> Adw.ActionRow:
        row = Adw.ActionRow(title=GLib.markup_escape_text(message))

        if command:
            row.set_subtitle(GLib.markup_escape_text(command))
            row.set_subtitle_selectable(True)
            row.add_css_class("monospace")
            button = Gtk.Button(
                icon_name="edit-copy-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Copy the command"
            )
            button.add_css_class("flat")
            button.connect("clicked", lambda *_: self.actions.copy(command, "Command copied"))
            row.add_suffix(button)

        return row
