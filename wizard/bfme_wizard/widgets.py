"""Small GTK helpers shared by the window and its pages."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk  # noqa: E402


def first_icon(*names: str) -> str:
    """The first icon the current theme has, so a missing icon never shows as a blurry placeholder."""
    theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
    return next((n for n in names if theme.has_icon(n)), "image-missing")


def pill(label: str, callback, *, suggested: bool = True) -> Gtk.Button:
    button = Gtk.Button(label=label, halign=Gtk.Align.CENTER)
    button.add_css_class("pill")
    if suggested:
        button.add_css_class("suggested-action")
    button.connect("clicked", lambda *_: callback())
    return button


def clear(box: Gtk.Box) -> None:
    child = box.get_first_child()
    while child is not None:
        nxt = child.get_next_sibling()
        box.remove(child)
        child = nxt
