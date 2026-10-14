"""GTK helpers shared by the window and its pages."""
from __future__ import annotations

from functools import lru_cache

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from .catalog import Program


def first_icon(*names: str) -> str:
    """First icon the theme has, to avoid a blurry placeholder."""
    theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
    return next((n for n in names if theme.has_icon(n)), "image-missing")


@lru_cache(maxsize=None)
def read_picture(path: str) -> Gdk.Texture:
    """A picture from a file, read once and kept: the home screen is rebuilt on every change, and must not read files each time.

    Raises GLib.Error when the file cannot be read. A failure is not kept, so a file that turns up later is found.
    """
    return Gdk.Texture.new_from_filename(path)


def program_icon(info: Program, size: int) -> Adw.Avatar:
    """A program's own picture, drawn as a circle `size` pixels across.

    Without a usable file it is a coloured circle with the program's initials, so a missing or damaged file never shows as a
    broken-image box. The circle clips to the widget's own box, so the widget is centred and not stretched by its container.
    """
    try:
        picture = read_picture(str(info.icon))
    except GLib.Error:
        picture = None
    return Adw.Avatar(size=size, text=info.title, show_initials=True, custom_image=picture,
                      halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)


def pill(label: str, callback, *, suggested: bool = True) -> Gtk.Button:
    button = Gtk.Button(label=label, halign=Gtk.Align.CENTER)
    button.add_css_class("pill")
    if suggested:
        button.add_css_class("suggested-action")
    button.connect("clicked", lambda *_: callback())
    return button


def icon_button(icons: tuple[str, ...], label: str, callback) -> Gtk.Button:
    """A flat button with only an icon. The label is its tooltip and its name for screen readers."""
    button = Gtk.Button(icon_name=first_icon(*icons), tooltip_text=label, css_classes=["flat"])
    button.update_property([Gtk.AccessibleProperty.LABEL], [label])
    button.connect("clicked", lambda *_: callback())
    return button


def clear(box: Gtk.Box) -> None:
    child = box.get_first_child()
    while child is not None:
        nxt = child.get_next_sibling()
        box.remove(child)
        child = nxt
