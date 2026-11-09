"""The home screen: a card for each installed program, with a button to open it."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk  # noqa: E402

from ...control.controller import Controller
from ...engine.programs import PROGRAMS, Program
from ..widgets import clear, pill, program_icon

# What the page says when there is no card to show. A complete setup always has one, so this is only a safety net.
NOTHING_INSTALLED = "Nothing is installed. Use the download button at the top to install a program."
CARD_ICON_SIZE = 64
# The window floats its icon buttons in the top right corner of the page: 6 pixels from the top, and 34 high.
CORNER_CLEARANCE = 46
QUICK_EXIT_NOTE = "Closed after a few seconds. If it didn't open, see Troubleshoot."


class HomePage:
    """One card for each program that is installed. Installing and removing programs is the Programs page's job."""

    def __init__(self, controller: Controller, version: Callable[[], str]) -> None:
        self.controller, self.version = controller, version
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=18,
            vexpand=True,
            valign=Gtk.Align.CENTER,
            halign=Gtk.Align.CENTER,
            margin_start=24,
            margin_end=24,
            margin_top=CORNER_CLEARANCE,
            margin_bottom=CORNER_CLEARANCE,
        )
        self.version_label = Gtk.Label(
            css_classes=["caption", "dim-label"], halign=Gtk.Align.CENTER, margin_top=6, margin_bottom=12
        )
        self.box.append(self.content)
        self.box.append(self.version_label)

    def refresh(self) -> None:
        clear(self.content)
        self.version_label.set_text(f"Version {self.version()}")
        line = self.controller.model.games_line
        if line:
            self.content.append(
                Gtk.Label(label=line, wrap=True, justify=Gtk.Justification.CENTER, css_classes=["heading"])
            )
        installed = [info for info in PROGRAMS if self.controller.model.is_installed(info.key)]
        if not installed:
            self.content.append(
                Gtk.Label(
                    label=NOTHING_INSTALLED,
                    wrap=True,
                    justify=Gtk.Justification.CENTER,
                    css_classes=["dim-label"],
                    max_width_chars=40,
                )
            )
            return
        cards = Gtk.Box(spacing=16, homogeneous=True, halign=Gtk.Align.CENTER)
        for info in installed:
            cards.append(self._card(info))
        self.content.append(cards)

    def _card(self, info: Program) -> Gtk.Widget:
        name = info.key
        state = self.controller.apps.state[name]
        inner = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=10,
            margin_top=18,
            margin_bottom=18,
            margin_start=18,
            margin_end=18,
        )
        inner.append(program_icon(info, CARD_ICON_SIZE))
        inner.append(Gtk.Label(label=info.title, css_classes=["title-2"]))
        inner.append(
            Gtk.Label(
                label=info.summary,
                wrap=True,
                justify=Gtk.Justification.CENTER,
                css_classes=["dim-label"],
                max_width_chars=20,
            )
        )
        if state == "running":
            running = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER, margin_top=4, margin_bottom=4)
            running.append(Gtk.Spinner(spinning=True))
            running.append(Gtk.Label(label="Running"))
            inner.append(running)
        else:
            inner.append(pill("Open", lambda n=name: self.controller.open_app(n)))
        if state == "quick":
            inner.append(
                Gtk.Label(
                    label=QUICK_EXIT_NOTE,
                    wrap=True,
                    justify=Gtk.Justification.CENTER,
                    css_classes=["caption", "warning"],
                    max_width_chars=26,
                )
            )
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["card"])
        card.append(inner)
        return card
