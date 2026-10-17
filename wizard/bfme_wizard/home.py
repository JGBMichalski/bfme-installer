"""The home screen cards, the Game folders page and the Troubleshoot page. They show the model and call back into the window."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from .catalog import CATALOG, Program
from .controller import Controller
from .model import games_line
from .paths import game_folders
from .widgets import clear, first_icon, pill, program_icon

# What the page says when there is no card to show. A complete setup always has one, so this is only a safety net.
NOTHING_INSTALLED = "Nothing is installed. Use the download button at the top to install a program."
CARD_ICON_SIZE = 64
# The window floats its icon buttons in the top right corner of the page: 6 pixels from the top, and 34 high.
CORNER_CLEARANCE = 46
QUICK_EXIT_NOTE = "Closed after a few seconds. If it didn't open, see Troubleshoot."
# The sandbox cannot see these. Advice only, never pass or fail.
CANT_CHECK = [
    ("Firewall", "If you cannot host or join games, check that your firewall (ufw or firewalld) allows them.", "sudo ufw status"),
    ("Graphics drivers", "The launchers/applications need working Vulkan drivers on your computer.", "vulkaninfo --summary"),
]


class HomePage:
    """One card for each program that is installed. Installing and removing programs is the Programs page's job."""

    def __init__(self, controller: Controller, version: Callable[[], str]) -> None:
        self.controller, self.version = controller, version
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, vexpand=True, valign=Gtk.Align.CENTER,
                               halign=Gtk.Align.CENTER, margin_start=24, margin_end=24,
                               margin_top=CORNER_CLEARANCE, margin_bottom=CORNER_CLEARANCE)
        self.version_label = Gtk.Label(css_classes=["caption", "dim-label"], halign=Gtk.Align.CENTER,
                                       margin_top=6, margin_bottom=12)
        self.box.append(self.content)
        self.box.append(self.version_label)

    def refresh(self) -> None:
        clear(self.content)
        self.version_label.set_text(f"Version {self.version()}")
        line = games_line(self.controller.model)
        if line:
            self.content.append(Gtk.Label(label=line, wrap=True, justify=Gtk.Justification.CENTER,
                                          css_classes=["heading"]))
        installed = [info for info in CATALOG if self.controller.model.is_installed(info.key)]
        if not installed:
            self.content.append(Gtk.Label(label=NOTHING_INSTALLED, wrap=True, justify=Gtk.Justification.CENTER,
                                          css_classes=["dim-label"], max_width_chars=40))
            return
        cards = Gtk.Box(spacing=16, homogeneous=True, halign=Gtk.Align.CENTER)
        for info in installed:
            cards.append(self._card(info))
        self.content.append(cards)

    def _card(self, info: Program) -> Gtk.Widget:
        name = info.key
        state = self.controller.apps.state[name]
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=18, margin_bottom=18, margin_start=18, margin_end=18)
        inner.append(program_icon(info, CARD_ICON_SIZE))
        inner.append(Gtk.Label(label=info.title, css_classes=["title-2"]))
        inner.append(Gtk.Label(label=info.summary, wrap=True, justify=Gtk.Justification.CENTER, css_classes=["dim-label"], max_width_chars=20))
        if state == "running":
            running = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER, margin_top=4, margin_bottom=4)
            running.append(Gtk.Spinner(spinning=True))
            running.append(Gtk.Label(label="Running"))
            inner.append(running)
        else:
            inner.append(pill("Open", lambda n=name: self.controller.open_app(n)))
        if state == "quick":
            inner.append(Gtk.Label(label=QUICK_EXIT_NOTE, wrap=True, justify=Gtk.Justification.CENTER,
                                   css_classes=["caption", "warning"], max_width_chars=26))
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["card"])
        card.append(inner)
        return card


class GameFoldersPage:
    """Game folders page: one group per game, one row per folder."""

    def __init__(self, open_folder: Callable[[Path], None]) -> None:
        self.view = Adw.ToolbarView()
        self.view.add_top_bar(Adw.HeaderBar())
        page = Adw.PreferencesPage(
            title="Game folders",
            description="Open a folder in your file manager to add maps or copy files.",
        )
        any_installed = False
        # A game that is not installed has no folders to open, so it has no group.
        for folders in (f for f in game_folders() if f.installed):
            group = Adw.PreferencesGroup(title=GLib.markup_escape_text(folders.name))
            for title, subtitle, target in (
                ("Game folder", "Installed files and patches", folders.game),
                ("Maps and user data", "Maps, replays and settings", folders.maps_target()),
            ):
                row = Adw.ActionRow(title=title, subtitle=subtitle, activatable=True)
                row.add_suffix(Gtk.Image.new_from_icon_name("folder-open-symbolic"))
                row.connect("activated", lambda *_, t=target: open_folder(t))
                group.add(row)
            page.add(group)
            any_installed = True
        if not any_installed:
            self.view.set_content(Adw.StatusPage(
                title="No games installed", description="Install a game with the AIO Launcher, and its folders will be here.",
                icon_name=first_icon("folder-symbolic", "folder-open-symbolic"),
            ))
            return
        self.view.set_content(page)


class TroubleshootPage:
    """Rebuilt only when its content changes, so expanded rows stay open."""

    def __init__(self, controller: Controller, *, copy_text: Callable[[str, str], None], copy_diagnostics: Callable[[], None],
                 open_logs: Callable[[], None], confirm_reset: Callable[[], None]) -> None:
        self.controller = controller
        self._cb = dict(copy_text=copy_text, copy_diagnostics=copy_diagnostics, open_logs=open_logs, confirm_reset=confirm_reset)
        self.view = Adw.ToolbarView()
        self.view.add_top_bar(Adw.HeaderBar())
        self._key = None
        self.refresh()

    def refresh(self) -> None:
        c = self.controller
        key = (tuple(c.model.check_rows), c.checking, c.model.state, tuple(c.apps.state.values()), c.blocked_reason())
        if key == self._key:
            return
        self._key = key
        page = Adw.PreferencesPage()
        page.add(self._checks_group())
        page.add(self._cant_check_group())
        page.add(self._tools_group())
        self.view.set_content(page)

    def _checks_group(self) -> Adw.PreferencesGroup:
        c, m = self.controller, self.controller.model
        group = Adw.PreferencesGroup(title="System checks")
        rows = m.check_rows
        if not rows:
            group.set_description("Not checked yet.")
        else:
            for _cid, level, message, fix in rows:
                if level != "ok":
                    group.add(self._check_row(level, message, fix))
            passed = [r for r in rows if r[1] == "ok"]
            if passed:
                fold = Adw.ExpanderRow(title=f"{len(passed)} check{'s' if len(passed) != 1 else ''} passed")
                fold.add_prefix(self._icon("ok"))
                for _cid, level, message, fix in passed:
                    fold.add_row(self._check_row(level, message, fix))
                group.add(fold)
        again = Gtk.Button(halign=Gtk.Align.END, css_classes=["pill"], margin_top=8)
        if c.checking:
            body = Gtk.Box(spacing=8)
            body.append(Gtk.Spinner(spinning=True))
            body.append(Gtk.Label(label="Checking..."))
            again.set_child(body)
        else:
            again.set_label("Check again")
        again.set_sensitive(not c.checking and m.state != "running")
        again.connect("clicked", lambda *_: c.run_checks())
        group.add(again)
        return group

    def _cant_check_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(
            title="Can't be checked from here",
            description="This app runs in a sandbox and cannot see these. A green list above does not cover them.",
        )
        for title, advice, command in CANT_CHECK:
            row = Adw.ActionRow(title=title, subtitle=GLib.markup_escape_text(advice), subtitle_lines=3)
            button = Gtk.Button(label="Copy command", valign=Gtk.Align.CENTER, css_classes=["flat"])
            button.connect("clicked", lambda _b, cmd=command: self._cb["copy_text"](cmd, "Command copied"))
            row.add_suffix(button)
            group.add(row)
        return group

    def _tools_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Tools")
        for title, subtitle, action in (
            ("Copy diagnostics", "Version, your computer's desktop and graphics card, system checks and the end of the latest logs. Check it before you share it.", "copy_diagnostics"),
            ("Open logs folder", "Opens the folder in your file manager.", "open_logs"),
        ):
            row = Adw.ActionRow(title=title, subtitle=subtitle, subtitle_lines=2, activatable=True)
            row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
            row.connect("activated", lambda *_, a=action: self._cb[a]())
            group.add(row)
        reason = self.controller.blocked_reason()
        reset = Adw.ActionRow(
            title="Reset game environment",
            subtitle=GLib.markup_escape_text(reason or "Deletes the game environment and every game you installed, including Age of the Ring."),
            subtitle_lines=2, activatable=reason is None, sensitive=reason is None,
        )
        reset.add_css_class("error")
        reset.add_suffix(Gtk.Image.new_from_icon_name("user-trash-symbolic"))
        reset.connect("activated", lambda *_: self._cb["confirm_reset"]())
        group.add(reset)
        return group

    @staticmethod
    def _icon(level: str) -> Gtk.Image:
        name = {"ok": "emblem-ok-symbolic", "warn": "dialog-warning-symbolic", "fail": "dialog-error-symbolic"}[level]
        image = Gtk.Image.new_from_icon_name(first_icon(name, "dialog-information-symbolic"))
        image.add_css_class({"ok": "success", "warn": "warning", "fail": "error"}[level])
        return image

    def _check_row(self, level: str, message: str, fix: str | None) -> Adw.ActionRow:
        row = Adw.ActionRow(title=GLib.markup_escape_text(message), title_lines=3)
        row.add_prefix(self._icon(level))
        if level == "fail" and fix:
            row.set_subtitle(GLib.markup_escape_text(fix))
            row.set_subtitle_lines(5)
            row.add_css_class("monospace")
            button = Gtk.Button(icon_name="edit-copy-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"], tooltip_text="Copy the command")
            button.connect("clicked", lambda *_: self._cb["copy_text"](fix, "Command copied"))
            row.add_suffix(button)
        return row
