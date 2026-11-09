"""Dialogs the window shows, built from what they say. No state of their own."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from ..services import whatsnew


def show_whats_new(window: Gtk.Window, notes: list[tuple[str, str]]) -> Adw.AlertDialog:
    """The changelog's notes for each new version, newest first, in one dialog."""
    parts = []

    for version, text in notes:
        body = whatsnew.markup(text)

        # With more than one version, each says which it is.
        if len(notes) > 1:
            body = f"<big><b>{version}</b></big>\n{body}"

        parts.append(body)

    label = Gtk.Label(
        label="\n\n".join(parts), use_markup=True, wrap=True, xalign=0, selectable=True, margin_start=6, margin_end=6
    )
    scroll = Gtk.ScrolledWindow(
        child=label,
        hscrollbar_policy=Gtk.PolicyType.NEVER,
        min_content_height=320,
        propagate_natural_height=True,
        max_content_height=420,
    )
    dialog = Adw.AlertDialog(heading=f"What's new in {notes[0][0]}", extra_child=scroll)
    dialog.add_response("close", "Close")
    dialog.present(window)
    return dialog


def confirm(
    window: Gtk.Window,
    heading: str,
    body: str,
    action: str,
    on_yes: Callable[[], None],
    cancel: str = "Cancel",
) -> Adw.AlertDialog:
    """Ask before something that cannot be undone. `action` is the label of the destructive button; `on_yes` runs when it
    is pressed. Closing the dialog or pressing `cancel` does nothing."""
    dialog = Adw.AlertDialog(heading=heading, body=body)
    dialog.add_response("cancel", cancel)
    dialog.add_response("yes", action)
    dialog.set_response_appearance("yes", Adw.ResponseAppearance.DESTRUCTIVE)
    dialog.set_default_response("cancel")
    dialog.set_close_response("cancel")

    def answered(_dialog: Adw.AlertDialog, response: str) -> None:
        if response == "yes":
            on_yes()

    dialog.connect("response", answered)
    dialog.present(window)
    return dialog
