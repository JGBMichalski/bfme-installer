"""The Troubleshoot page: system checks, graphics, tools and reset."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from typing import TYPE_CHECKING

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ...control.controller import Controller
from ..widgets import first_icon

if TYPE_CHECKING:
    from ..actions import WindowActions

# The sandbox cannot see these. Advice only, never pass or fail. The drivers named depend on the chosen backend.
# (value, label) of each choice in Troubleshoot's Graphics section.
GPU_CHOICES: list[tuple[str | int, str]] = [
    ("auto", "Automatic"),
    ("dedicated", "Dedicated card"),
    ("integrated", "Built-in card"),
]


def cant_check(graphics: str) -> list[tuple[str, str, str]]:
    if graphics == "opengl":
        drivers = (
            "Graphics drivers",
            "The launchers/applications need working OpenGL drivers on your computer. If a game is slow "
            "or does not start, switch back to Vulkan on this page.",
            "glxinfo -B",
        )
    else:
        drivers = (
            "Graphics drivers",
            "The launchers/applications need working Vulkan drivers on your computer. On an older "
            "graphics card, switch to OpenGL on this page.",
            "vulkaninfo --summary",
        )
    return [
        (
            "Firewall",
            "If you cannot host or join games, check that your firewall (ufw or firewalld) allows them.",
            "sudo ufw status",
        ),
        drivers,
    ]


class TroubleshootPage:
    """Rebuilt only when its content changes, so expanded rows stay open."""

    def __init__(self, controller: Controller, actions: WindowActions) -> None:
        self.controller = controller
        self.actions = actions
        self.view = Adw.ToolbarView()
        self.view.add_top_bar(Adw.HeaderBar())
        self._key = None
        self.refresh()

    def refresh(self, force: bool = False) -> None:
        """Rebuild the page if what it shows changed, or when forced (a row the player changed must show what is saved)."""
        c = self.controller
        m = c.model
        key = (
            tuple(m.check_rows),
            c.checking,
            m.state,
            tuple(c.apps.state.values()),
            c.blocked_reason(),
            m.graphics,
            m.known.gpu,
            m.known.fps_counter,
            m.known.graphics_cards,
        )
        if key == self._key and not force:
            return
        self._key = key
        page = Adw.PreferencesPage()
        page.add(self._checks_group())
        page.add(self._graphics_group())
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

    def _graphics_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(
            title="Graphics",
            description="Vulkan is the default. OpenGL can work better on older graphics cards. Changes take effect the next "
            "time you open a program.",
        )
        m = self.controller.model
        free = self.controller.blocked_reason() is None
        opengl = m.graphics == "opengl"
        row = Adw.ActionRow(
            title="Backend",
            subtitle="OpenGL (WineD3D)" if opengl else "Vulkan (DXVK)",
        )
        button = Gtk.Button(
            label="Use Vulkan" if opengl else "Use OpenGL", valign=Gtk.Align.CENTER, css_classes=["flat"]
        )
        button.set_sensitive(self.controller.blocked_reason() is None)
        button.connect("clicked", lambda *_: self.actions.change_graphics("vulkan" if opengl else "opengl"))
        row.add_suffix(button)
        group.add(row)

        # The choice of card only means something on a computer that has two.
        if m.known.graphics_cards > 1:
            group.add(
                self._choice_row(
                    "Graphics card",
                    "Which card runs the games, on a computer with two.",
                    "gpu",
                    GPU_CHOICES,
                    m.known.gpu,
                    free,
                )
            )

        counter = Adw.SwitchRow(
            title="Show FPS",
            subtitle="The frame rate in the corner of the game. Vulkan only.",
            active=m.known.fps_counter,
            sensitive=free,
        )
        counter.connect(
            "notify::active", lambda row, _param: self.actions.change_option("fps-counter", int(row.get_active()))
        )
        group.add(counter)

        return group

    def _choice_row(
        self,
        title: str,
        subtitle: str,
        option: str,
        choices: list[tuple[str | int, str]],
        current: str | int,
        sensitive: bool,
    ) -> Adw.ComboRow:
        """A row to pick one of a few values. Picking one saves it."""
        labels = []
        selected = 0

        for index, (value, label) in enumerate(choices):
            labels.append(label)

            if value == current:
                selected = index

        row = Adw.ComboRow(
            title=title, subtitle=subtitle, model=Gtk.StringList.new(labels), selected=selected, sensitive=sensitive
        )

        # Connected after the current value is set, so building the row saves nothing.
        def picked(combo: Adw.ComboRow, _param) -> None:
            self.actions.change_option(option, choices[combo.get_selected()][0])

        row.connect("notify::selected", picked)
        return row

    def _cant_check_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(
            title="Can't be checked from here",
            description="This app runs in a sandbox and cannot see these. A green list above does not cover them.",
        )
        for title, advice, command in cant_check(self.controller.model.graphics):
            row = Adw.ActionRow(title=title, subtitle=GLib.markup_escape_text(advice), subtitle_lines=3)
            button = Gtk.Button(label="Copy command", valign=Gtk.Align.CENTER, css_classes=["flat"])
            button.connect("clicked", lambda _b, cmd=command: self.actions.copy(cmd, "Command copied"))
            row.add_suffix(button)
            group.add(row)
        return group

    def _tools_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Tools")
        for title, subtitle, action in (
            (
                "Copy diagnostics",
                "Version, your computer's desktop and graphics card, system checks and the end of the latest logs. Check it before you share it.",
                self.actions.copy_diagnostics,
            ),
            ("Open logs folder", "Opens the folder in your file manager.", self.actions.open_logs),
            (
                "Open settings file",
                "Opens config.env in your text editor. Changes apply the next time you open a program.",
                self.actions.open_config,
            ),
        ):
            row = Adw.ActionRow(title=title, subtitle=subtitle, subtitle_lines=2, activatable=True)
            row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
            row.connect("activated", lambda *_, a=action: a())
            group.add(row)
        reason = self.controller.blocked_reason()
        reset = Adw.ActionRow(
            title="Reset game environment",
            subtitle=GLib.markup_escape_text(
                reason or "Deletes the game environment and every game you installed, including Age of the Ring."
            ),
            subtitle_lines=2,
            activatable=reason is None,
            sensitive=reason is None,
        )
        reset.add_css_class("error")
        reset.add_suffix(Gtk.Image.new_from_icon_name("user-trash-symbolic"))
        reset.connect("activated", lambda *_: self.actions.confirm_reset())
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
            button = Gtk.Button(
                icon_name="edit-copy-symbolic",
                valign=Gtk.Align.CENTER,
                css_classes=["flat"],
                tooltip_text="Copy the command",
            )
            button.connect("clicked", lambda *_: self.actions.copy(fix, "Command copied"))
            row.add_suffix(button)
        return row
