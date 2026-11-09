"""Utilities the tests share: a way to wait for the main loop, and what the manifest says. The `gtk` fixture is in
conftest.py, the stand-in jobs in fake_jobs.py."""

import re
import struct
from pathlib import Path

from gi.repository import GLib

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "flatpak" / "com.jgbmichalski.BfmeInstaller.yml"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# What the shortcuts call each program's shortcut and icon in the Flatpak (`<app id>.<this>`). The manifest must export
# the icons under the same names, which the tests check from both sides.
EXPORT_SUFFIX = {"aio-launcher": "AioLauncher", "arena": "Arena", "aotr": "Aotr"}


def wait_for(loop_ms, condition):
    """Run the main loop until the condition holds, or give up after loop_ms."""
    loop = GLib.MainLoop()

    def tick():
        if condition():
            loop.quit()
            return False
        return True

    GLib.timeout_add(50, tick)
    GLib.timeout_add(loop_ms, loop.quit)
    loop.run()


def descendants(widget):
    """Every widget under this one, depth first."""
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from descendants(child)
        child = child.get_next_sibling()


def buttons(widget, Gtk):
    """Every button under the widget (and the widget itself, if it is one), in order."""
    found = [widget] if isinstance(widget, Gtk.Button) else []
    return found + [w for w in descendants(widget) if isinstance(w, Gtk.Button)]


def labels(widget, Gtk, css_class=None):
    """The text of every label under the widget, optionally only those with a style class."""
    return [
        w.get_label()
        for w in descendants(widget)
        if isinstance(w, Gtk.Label) and (css_class is None or w.has_css_class(css_class))
    ]


def png_size(path):
    """(width, height) of a PNG, read from its header. Raises AssertionError when the file is not a PNG."""
    data = Path(path).read_bytes()
    assert data[:8] == PNG_SIGNATURE and data[12:16] == b"IHDR", f"{path} is not a PNG"
    return struct.unpack(">II", data[16:24])


def manifest_app_id():
    return re.search(r"^id: (\S+)", MANIFEST.read_text(), re.M).group(1)


def manifest_icon_exports():
    """{picture file name: (width of its folder, height of its folder, exported name)}, from the manifest's install commands.

    For example {"aio-launcher.png": (128, 128, "com.jgbmichalski.BfmeInstaller.AioLauncher")}.
    """
    found = {}
    pattern = r"install -Dm644 bfme_wizard/icons/(\S+\.png) /app/share/icons/hicolor/(\d+)x(\d+)/apps/(\S+)\.png"
    for name, width, height, exported in re.findall(pattern, MANIFEST.read_text()):
        found[name] = (int(width), int(height), exported)
    return found


def status(*installed, prefix_ready=False, **fields):
    """A SetupStatus with these program and game keys installed. Complete as the engine works it out, unless given."""
    from bfme_wizard.engine.events import SetupStatus
    from bfme_wizard.engine.games import GAMES
    from bfme_wizard.engine.programs import program

    programs = set()
    games = set()

    for key in installed:
        if key in [game.key for game in GAMES]:
            games.add(key)
        else:
            programs.add(key)

    if "complete" not in fields:
        any_program = False

        for key in programs:
            if not program(key).is_tool:
                any_program = True

        fields["complete"] = prefix_ready and any_program

    return SetupStatus(prefix_ready=prefix_ready, programs=frozenset(programs), games=frozenset(games), **fields)


def context(paths, emit=None, cancel=None, config=None, proton="fake-proton"):
    """A Context for calling an action directly, with Proton at `proton` (umu's PROTONPATH)."""
    from bfme_wizard.engine.config import Config
    from bfme_wizard.engine.context import Context
    from bfme_wizard.engine.proton import Proton

    config = config or Config()
    return Context(paths, config=config, emit=emit, cancel=cancel, proton=Proton(paths, config, proton))
