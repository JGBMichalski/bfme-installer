"""The page a running setup shows: step n of N, what it does, and its progress."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk  # noqa: E402

from ...control.controller import Controller
from ...control.model import description_of, speed_text, title_of


class RunningPage:
    def __init__(self, controller: Controller) -> None:
        self.controller = controller
        self.view = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=12, valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER
        )
        self.view.set_size_request(440, -1)
        self.count = Gtk.Label(css_classes=["dim-label"])
        self.title = Gtk.Label(css_classes=["title-1"], wrap=True, justify=Gtk.Justification.CENTER)
        self.description = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        self.bar = Gtk.ProgressBar()
        self.note = Gtk.Label(css_classes=["dim-label"], ellipsize=3, max_width_chars=60)
        self.cancel = Gtk.Button(label="Cancel", halign=Gtk.Align.CENTER, margin_top=12)
        self.cancel.connect("clicked", lambda *_: self.controller.cancel())

        for widget in (self.count, self.title, self.description, self.bar, self.note, self.cancel):
            self.view.append(widget)

    def refresh(self) -> None:
        m = self.controller.model
        defs = m.step_defs
        step_id = m.current or (defs[min(m.done_count, len(defs) - 1)][0])
        self.count.set_text(f"Step {m.step_number} of {len(defs)}")
        self.title.set_text(title_of(step_id))
        self.description.set_text(description_of(step_id))

        if m.progress is not None:
            self.bar.set_fraction(m.progress / 100)
            note = f"{m.progress}%"

            if m.speed is not None:
                note += f" · {speed_text(m.speed)}"

            self.note.set_text(note)
        elif m.speed is not None:
            self.note.set_text(speed_text(m.speed))  # a download of unknown size
        elif step_id == "doctor":
            self.note.set_text(m.last_check_message)
        else:
            self.note.set_text("")

        if m.cancel_requested:
            self.cancel.set_label("Stopping after this step...")
        else:
            self.cancel.set_label("Cancel")

        self.cancel.set_sensitive(not m.cancel_requested)

    def pulse(self) -> bool:
        """Keeps the bar moving when a step reports no percentage. A timeout callback: it runs again while it returns
        True."""
        m = self.controller.model

        if m.state == "running" and m.progress is None:
            self.bar.pulse()

        return True
