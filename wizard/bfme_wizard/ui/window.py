"""The wizard window. Builds its pages, shows the one the model is in, and opens the others on top."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ..control.controller import Controller
from ..engine.programs import program
from ..services.updater import Updater
from .actions import WindowActions
from .dialogs import confirm
from .pages.busy import BusyPage
from .pages.game_folders import GameFoldersPage
from .pages.home import HomePage
from .pages.problem import ProblemPage
from .pages.programs import ProgramsPage
from .pages.running import RunningPage
from .pages.start import StartPage
from .pages.troubleshoot import TroubleshootPage
from .update_banner import UpdateBanner
from .widgets import icon_button

# Icons of the corner buttons, best first: the host's icon theme and the Flatpak runtime's are not the same set, and a name
# only the host has shows a broken image inside the Flatpak. The first of each is in the GNOME runtime.
PROGRAMS_ICONS = ("folder-download-symbolic", "system-software-install-symbolic", "document-save-symbolic")

FOLDERS_ICONS = ("folder-symbolic", "folder-open-symbolic", "system-file-manager-symbolic")

# A lifebuoy: help when something goes wrong. Not a gear (that says Settings), not a warning sign (that says alarm).
TROUBLESHOOT_ICONS = (
    "help-browser-symbolic",
    "applications-engineering-symbolic",
    "dialog-question-symbolic",
    "help-about-symbolic",
)


class WizardWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, controller_factory) -> None:
        super().__init__(application=app, title="BFME Installer")
        self.set_default_size(640, 560)
        self.controller: Controller = controller_factory(self.render)
        self.model = self.controller.model
        self.actions = WindowActions(self)

        self.toasts = Adw.ToastOverlay()
        toolbar = Adw.ToolbarView()
        self.header = Adw.HeaderBar()
        toolbar.add_top_bar(self.header)
        self.check_banner = Adw.Banner(title="Your system needs a change.", button_label="Troubleshoot")
        self.check_banner.connect("button-clicked", lambda *_: self.show_troubleshoot())
        toolbar.add_top_bar(self.check_banner)
        self.update_banner = UpdateBanner(self)
        toolbar.add_top_bar(self.update_banner.view)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        # The buttons that lead to the other pages float in the top right corner of the page, under the header bar. They are
        # laid over the page, not above it, so the page keeps all its room. Troubleshoot is there on every page, as the menu it
        # replaced was, and is the one in the corner. The other two belong to the home screen, so they only show while there is
        # one. (6 pixels from the corner puts the lifebuoy right under the window's close button.)
        self.corner = Gtk.Box(spacing=6, halign=Gtk.Align.END, valign=Gtk.Align.START, margin_top=6, margin_end=6)
        self.programs_button = icon_button(PROGRAMS_ICONS, "Install or remove programs", self.show_programs)
        self.folders_button = icon_button(FOLDERS_ICONS, "Game folders", self.show_game_folders)
        self.troubleshoot_button = icon_button(TROUBLESHOOT_ICONS, "Troubleshoot", self.show_troubleshoot)

        for button in (self.programs_button, self.folders_button, self.troubleshoot_button):
            self.corner.append(button)

        self.folders_button.set_visible(False)
        self.programs_button.set_visible(False)
        page = Gtk.Overlay(child=self.stack)
        page.add_overlay(self.corner)
        toolbar.set_content(page)
        self.nav = Adw.NavigationView()
        self.root_page = Adw.NavigationPage.new(toolbar, "BFME Installer")
        self.nav.add(self.root_page)
        self.nav.connect("popped", self._on_popped)
        self.troubleshoot: TroubleshootPage | None = None
        self._troubleshoot_page: Adw.NavigationPage | None = None
        self.programs: ProgramsPage | None = None
        self._programs_page: Adw.NavigationPage | None = None
        self.toasts.set_child(self.nav)
        self.set_content(self.toasts)

        # The pages of the main view, one for each state of the model.
        self.checking = BusyPage("Checking your setup...")
        self.removing = BusyPage("Removing...")
        self.start = StartPage(self.controller)
        self.running = RunningPage(self.controller)
        self.problem = ProblemPage(self.controller, self.actions)
        self.home = HomePage(self.controller, lambda: self.updater.local or "dev")

        for name, view in (
            ("checking", self.checking.view),
            ("removing", self.removing.view),
            ("start", self.start.view),
            ("run", self.running.view),
            ("problem", self.problem.view),
            ("home", self.home.box),
        ):
            self.stack.add_named(view, name)

        self.connect("close-request", self._on_close_request)
        self.updater.check()
        GLib.timeout_add(120, self.running.pulse)

    @property
    def updater(self) -> Updater:
        return self.update_banner.updater

    # The pages opened on top

    def show_troubleshoot(self) -> None:
        if self.troubleshoot is not None:
            return

        self.troubleshoot = TroubleshootPage(self.controller, self.actions)
        self._troubleshoot_page = Adw.NavigationPage.new(self.troubleshoot.view, "Troubleshoot")
        self.nav.push(self._troubleshoot_page)

    def show_game_folders(self) -> None:
        if self.nav.get_visible_page().get_title() == "Game folders":
            return

        self.nav.push(Adw.NavigationPage.new(GameFoldersPage(self.actions.open_folder).view, "Game folders"))

    def show_programs(self) -> None:
        if self.programs is not None:
            return

        self.programs = ProgramsPage(
            self.controller,
            install=self.actions.install_program,
            remove=self.actions.confirm_remove,
            open_app=self.controller.open_app,
        )
        self._programs_page = Adw.NavigationPage.new(self.programs.view, "Programs")
        self.nav.push(self._programs_page)

    def _on_popped(self, _nav, page) -> None:
        if page is self._troubleshoot_page:
            self.troubleshoot = None
        elif page is self._programs_page:
            self.programs = None

    # Rendering the model

    def render(self) -> None:
        self.update_banner.refresh()
        self.check_banner.set_revealed(self.model.state == "done" and bool(self.model.problems))
        self._render_corner()

        if self.troubleshoot is not None:
            self.troubleshoot.refresh()

        self._render_programs_page()
        m = self.model

        if m.state == "checking":
            self.stack.set_visible_child_name("checking")
        elif m.state == "removing":
            self.removing.set_title(f"Removing {program(m.removing).name}...")
            self.stack.set_visible_child_name("removing")
        elif m.state == "done":
            self.home.refresh()
            self.stack.set_visible_child_name("home")
        elif m.state == "running":
            self.running.refresh()
            self.stack.set_visible_child_name("run")
        elif m.state in ("blocked", "failed"):
            self.problem.refresh()
            self.stack.set_visible_child_name("problem")
        else:  # idle, cancelled: the start page
            if self.stack.get_visible_child_name() != "start":
                self.start.enter()  # it comes into view: tick what is remembered, and leave the player's own ticks alone after
            else:
                self.start.refresh()

            self.stack.set_visible_child_name("start")

    def _render_corner(self) -> None:
        home = self.model.state == "done"
        self.programs_button.set_visible(home)
        self.folders_button.set_visible(home)

    def _render_programs_page(self) -> None:
        """The Programs page is for the home screen. After a removal the setup is looked at again, and the page stays through
        that, as it was: for that moment the model knows nothing, and showing it would flash "Not installed" on every row.
        It goes when there is no home screen to come back to (the last program was removed)."""
        if self.programs is None:
            return

        state = self.model.state

        if state in ("done", "removing"):
            self.programs.refresh()
        elif state != "checking":
            self.nav.pop_to_page(self.root_page)
            return

        self._programs_page.set_can_pop(state == "done")

    # Closing

    def _on_close_request(self, _window) -> bool:
        """Ask first while something would be cut off half way. True keeps the window open until the player decides."""
        if self.model.state == "removing":
            heading = "A program is still being removed"
            body = (
                "If you close the window now, the removal stops half way and some of its files stay behind. "
                "Wait for it to finish."
            )
            action = "Close anyway"
        elif self.model.state == "running":
            heading = "Setup is still running"
            body = "If you close the window now, setup stops. Everything finished so far is kept, and you can resume later."
            action = "Stop and close"
        else:
            return False

        confirm(self, heading, body, action, self._stop_and_close, cancel="Keep going")
        return True

    def _stop_and_close(self) -> None:
        self.controller.stop_now()
        self.destroy()
