"""The wizard window. Renders the model one page at a time."""
from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk  # noqa: E402

from .aotr import MODDB_URL, AotrDownloadPage
from .catalog import program
from .controller import PROGRAM_OF, Controller
from .diagnostics import any_log, build_report, data_dir
from .home import GameFoldersPage, HomePage, TroubleshootPage
from .model import description_of, title_of
from .programs import ProgramsPage
from .start import StartPage
from .updater import make_updater
from .widgets import clear, first_icon, icon_button, pill

# Flatpak builds under another ID run beside this one.
APP_ID = os.environ.get("FLATPAK_ID") or "com.jgbmichalski.BfmeInstaller"

# Icons of the corner buttons, best first: the host's icon theme and the Flatpak runtime's are not the same set, and a name
# only the host has shows a broken image inside the Flatpak. The first of each is in the GNOME runtime.
PROGRAMS_ICONS = (
    "folder-download-symbolic",
    "system-software-install-symbolic",
    "document-save-symbolic"
)

FOLDERS_ICONS = (
    "folder-symbolic",
    "folder-open-symbolic",
    "system-file-manager-symbolic"
)

# A lifebuoy: help when something goes wrong. Not a gear (that says Settings), not a warning sign (that says alarm).
TROUBLESHOOT_ICONS = (
    "help-browser-symbolic",
    "applications-engineering-symbolic",
    "dialog-question-symbolic",
    "help-about-symbolic"
)


class WizardWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, controller_factory) -> None:
        super().__init__(application=app, title="BFME Installer")
        self.set_default_size(640, 560)
        self.controller: Controller = controller_factory(self.render)
        self.model = self.controller.model

        self.toasts = Adw.ToastOverlay()
        toolbar = Adw.ToolbarView()
        self.header = Adw.HeaderBar()
        toolbar.add_top_bar(self.header)
        self.check_banner = Adw.Banner(title="Your system needs a change.", button_label="Troubleshoot")
        self.check_banner.connect("button-clicked", lambda *_: self.show_troubleshoot())
        toolbar.add_top_bar(self.check_banner)
        self.updater = make_updater(self._render_update_banner)
        self.update_banner = Adw.Banner(use_markup=False)
        self.update_banner.connect("button-clicked", self._on_update_button)
        toolbar.add_top_bar(self.update_banner)
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

        self._build_checking()
        self._build_removing()
        self.start = StartPage(self.controller)
        self.stack.add_named(self.start.view, "start")
        self._build_run()
        self._build_problem()
        self.aotr = AotrDownloadPage(self.open_moddb, self.choose_aotr_zip, self.controller.back_home)
        self.stack.add_named(self.aotr.view, "aotr")
        self.home = HomePage(self.controller, lambda: self.updater.local or "dev")
        self.stack.add_named(self.home.box, "home")

        self.connect("close-request", self._on_close_request)
        self.updater.check()
        GLib.timeout_add(120, self._pulse)  # keeps the bar moving when a step reports no percentage

    def _spinner_page(self, title: str, name: str) -> Adw.StatusPage:
        page = Adw.StatusPage(title=title)
        spinner = Gtk.Spinner(spinning=True, halign=Gtk.Align.CENTER)
        spinner.set_size_request(32, 32)
        page.set_child(spinner)
        self.stack.add_named(page, name)
        return page

    def _build_checking(self) -> None:
        self._spinner_page("Checking your setup...", "checking")

    def _build_removing(self) -> None:
        self.removing_page = self._spinner_page("Removing...", "removing")

    def _build_run(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
        box.set_size_request(440, -1)
        self.run_count = Gtk.Label(css_classes=["dim-label"])
        self.run_title = Gtk.Label(css_classes=["title-1"], wrap=True, justify=Gtk.Justification.CENTER)
        self.run_desc = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        self.run_bar = Gtk.ProgressBar()
        self.run_note = Gtk.Label(css_classes=["dim-label"], ellipsize=3, max_width_chars=60)
        self.run_cancel = Gtk.Button(label="Cancel", halign=Gtk.Align.CENTER, margin_top=12)
        self.run_cancel.connect("clicked", lambda *_: self.controller.cancel())
        for widget in (self.run_count, self.run_title, self.run_desc, self.run_bar, self.run_note, self.run_cancel):
            box.append(widget)
        self.stack.add_named(box, "run")

    def _build_problem(self) -> None:
        self.problem = Adw.StatusPage()
        clamp = Adw.Clamp(maximum_size=520)
        self.problem_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        clamp.set_child(self.problem_box)
        self.problem.set_child(clamp)
        self.stack.add_named(self.problem, "problem")

    def _render_check_banner(self) -> None:
        m = self.model
        self.check_banner.set_revealed(m.state == "done" and bool(m.problems))

    def show_troubleshoot(self) -> None:
        if self.troubleshoot is not None:
            return
        self.troubleshoot = TroubleshootPage(
            self.controller, copy_text=self.copy, copy_diagnostics=self.copy_diagnostics,
            open_logs=self.open_logs, confirm_reset=self.confirm_reset, change_graphics=self.change_graphics,
        )
        self._troubleshoot_page = Adw.NavigationPage.new(self.troubleshoot.view, "Troubleshoot")
        self.nav.push(self._troubleshoot_page)

    def show_game_folders(self) -> None:
        if self.nav.get_visible_page().get_title() == "Game folders":
            return
        self.nav.push(Adw.NavigationPage.new(GameFoldersPage(self.open_folder).view, "Game folders"))

    def show_programs(self) -> None:
        if self.programs is not None:
            return
        self.programs = ProgramsPage(self.controller, install=self.install_program, remove=self.confirm_remove,
                                    open_app=self.controller.open_app)
        self._programs_page = Adw.NavigationPage.new(self.programs.view, "Programs")
        self.nav.push(self._programs_page)

    def _on_popped(self, _nav, page) -> None:
        if page is self._troubleshoot_page:
            self.troubleshoot = None
        elif page is self._programs_page:
            self.programs = None

    def install_program(self, key: str) -> None:
        """Install from the Programs page. The setup shows on the main page, so leave this one first."""
        self.nav.pop_to_page(self.root_page)
        self.controller.install([PROGRAM_OF[key]])

    def open_moddb(self) -> None:
        def opened(launcher: Gtk.UriLauncher, result: Gio.AsyncResult) -> None:
            try:
                launcher.launch_finish(result)
            except GLib.Error:
                toast = Adw.Toast.new("Could not open your browser.")
                toast.set_button_label("Copy link")
                toast.connect("button-clicked", lambda *_: self.copy(MODDB_URL, "Link copied"))
                self.toasts.add_toast(toast)

        Gtk.UriLauncher.new(MODDB_URL).launch(self, None, opened)

    def choose_aotr_zip(self) -> None:
        zips = Gtk.FileFilter()
        zips.set_name("Zip files")
        zips.add_pattern("*.zip")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(zips)
        dialog = Gtk.FileDialog(title="Choose the Age of the Ring download", filters=filters, default_filter=zips)
        downloads = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD)
        if downloads and os.path.isdir(downloads):
            dialog.set_initial_folder(Gio.File.new_for_path(downloads))

        def chosen(source: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
            try:
                picked = source.open_finish(result)
            except GLib.Error:
                return   # the player closed the chooser
            path = picked.get_path() if picked is not None else None
            if not path:
                self.toasts.add_toast(Adw.Toast.new("That file cannot be read from here."))
                return
            self.controller.choose_aotr_file(path)

        dialog.open(self, None, chosen)

    def copy_diagnostics(self) -> None:
        report = build_report(self.updater.local or "dev", self.model, data_dir() / "logs")
        self.copy(report, "Diagnostics copied. Check it before you share it.")

    def open_logs(self) -> None:
        logs = data_dir() / "logs"
        target = any_log(logs)
        if target is None:
            self.toasts.add_toast(Adw.Toast.new("There are no logs yet."))
            return

        def opened(launcher: Gtk.FileLauncher, result: Gio.AsyncResult) -> None:
            try:
                launcher.open_containing_folder_finish(result)
            except GLib.Error:
                self.toasts.add_toast(Adw.Toast.new(f"Could not open it. The logs are in {logs}"))

        Gtk.FileLauncher.new(Gio.File.new_for_path(str(target))).open_containing_folder(self, None, opened)

    def open_folder(self, folder) -> None:
        def opened(launcher: Gtk.FileLauncher, result: Gio.AsyncResult) -> None:
            try:
                launcher.launch_finish(result)
            except GLib.Error:
                toast = Adw.Toast.new(f"Could not open it. The folder is {folder}")
                toast.set_button_label("Copy path")
                toast.connect("button-clicked", lambda *_: self.copy(str(folder), "Path copied"))
                self.toasts.add_toast(toast)

        Gtk.FileLauncher.new(Gio.File.new_for_path(str(folder))).launch(self, None, opened)

    def confirm_reset(self) -> None:
        dialog = Adw.AlertDialog(
            heading="Delete the game environment?",
            body="This deletes the game environment, including every game you installed and Age of the Ring. "
                 "This cannot be undone.\n\nClose the AIO Launcher, the Arena and Age of the Ring first.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("reset", "Delete and set up again")
        dialog.set_response_appearance("reset", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda _d, response: self._do_reset() if response == "reset" else None)
        dialog.present(self)

    def confirm_remove(self, key: str) -> None:
        info = program(key)
        dialog = Adw.AlertDialog(
            heading=f"Remove {info.name}?",
            body=f"{info.removal}\n\nYou can install it again from the Programs page.\n\n"
                 "Close the AIO Launcher, the Arena and Age of the Ring first.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("remove", "Remove")
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda _d, response: self._do_remove(key) if response == "remove" else None)
        dialog.present(self)

    def _do_remove(self, key: str) -> None:
        name = program(key).name

        def done(ok: bool) -> None:
            if ok:
                text = f"{name[:1].upper()}{name[1:]} was removed."
            else:
                error = self.model.error   # still there: the setup is looked at again right after this
                text = f"Could not remove {name}: {error.message}" if error else f"Could not remove {name}."
            self.toasts.add_toast(Adw.Toast.new(text))

        if not self.controller.remove(key, done):
            self.toasts.add_toast(Adw.Toast.new(self.controller.blocked_reason() or "Not now."))

    def _do_reset(self) -> None:
        def done(ok: bool) -> None:
            text = "The game environment was deleted." if ok else "The reset failed. Open the logs folder from Troubleshoot."
            self.toasts.add_toast(Adw.Toast.new(text))

        if self.controller.reset(done):
            self.nav.pop_to_page(self.root_page)
        else:
            self.toasts.add_toast(Adw.Toast.new(self.controller.blocked_reason() or "Not now."))

    def change_graphics(self, backend: str) -> None:
        """Switch the graphics backend. The page shows the new one once the script has saved it."""
        def done(ok: bool) -> None:
            name = "OpenGL" if backend == "opengl" else "Vulkan"
            text = f"Now using {name}. It takes effect the next time you open a program."
            if not ok:
                text = f"Could not switch to {name}. Open the logs folder from Troubleshoot."
            self.toasts.add_toast(Adw.Toast.new(text))

        if not self.controller.set_graphics(backend, done):
            self.toasts.add_toast(Adw.Toast.new(self.controller.blocked_reason() or "Not now."))

    def _render_update_banner(self) -> None:
        u = self.updater
        if u.state == "idle" or self.model.state == "running":
            self.update_banner.set_revealed(False)
            return
        title, button = {
            "available": (f"Version {u.remote} is available (you have {u.local}).", "Update"),
            "updating": ("Updating..." if u.progress is None else f"Updating... {u.progress}%", None),
            "done": (f"Updated to {u.remote}. Close and reopen BFME Installer to use it.", "Close"),
            "empty": (f"Version {u.remote} is not ready to download yet. Try again in a few minutes.", "Try again"),
            "failed": (f"Could not update automatically. In a terminal, run: {u.manual_command}", "Copy command"),
        }[u.state]
        self.update_banner.set_title(title)
        self.update_banner.set_button_label(button)
        self.update_banner.set_revealed(True)

    def _on_update_button(self, _banner) -> None:
        state = self.updater.state
        if state in ("available", "empty"):
            self.updater.install()
        elif state == "done":
            self.close()
        elif state == "failed":
            self.copy(self.updater.manual_command, "Command copied")

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

    def render(self) -> None:
        self._render_update_banner()
        self._render_check_banner()
        self._render_corner()
        if self.troubleshoot is not None:
            self.troubleshoot.refresh()
        self._render_programs_page()
        m = self.model
        if m.state == "checking":
            self.stack.set_visible_child_name("checking")
        elif m.state == "removing":
            self.removing_page.set_title(f"Removing {program(m.removing).name}...")
            self.stack.set_visible_child_name("removing")
        elif m.state == "done":
            self.home.refresh()
            self.stack.set_visible_child_name("home")
        elif m.state == "running":
            self._render_run()
            self.stack.set_visible_child_name("run")
        elif m.state == "waiting":
            self.aotr.refresh(m.step_number, len(m.step_defs), self._leave_label())
            self.stack.set_visible_child_name("aotr")
        elif m.state in ("blocked", "failed"):
            self._render_problem()
            self.stack.set_visible_child_name("problem")
        else:  # idle, cancelled: the start page
            if self.stack.get_visible_child_name() != "start":
                self.start.enter()   # it comes into view: tick what is remembered, and leave the player's own ticks alone after
            else:
                self.start.refresh()
            self.stack.set_visible_child_name("start")

    def _leave_label(self) -> str:
        """Label of the button that leaves the plan."""
        return "Back to home" if self.model.has_home_screen else "Back to start"

    def _render_run(self) -> None:
        m = self.model
        defs = m.step_defs
        step_id = m.current or (defs[min(m.done_count, len(defs) - 1)][0])
        self.run_count.set_text(f"Step {m.step_number} of {len(defs)}")
        self.run_title.set_text(title_of(step_id))
        self.run_desc.set_text(description_of(step_id))
        if m.progress is not None:
            self.run_bar.set_fraction(m.progress / 100)
            self.run_note.set_text(f"{m.progress}%")
        else:
            self.run_note.set_text(m.last_check_message if step_id == "doctor" else "")
        self.run_cancel.set_label("Stopping after this step..." if m.cancel_requested else "Cancel")
        self.run_cancel.set_sensitive(not m.cancel_requested)

    def _pulse(self) -> bool:
        if self.model.state == "running" and self.model.progress is None:
            self.run_bar.pulse()
        return True

    def _render_problem(self) -> None:
        m = self.model
        clear(self.problem_box)
        if m.state == "blocked":
            self.problem.set_icon_name(first_icon("dialog-warning-symbolic", "dialog-error-symbolic"))
            self.problem.set_title("Your system needs a change")
            self.problem.set_description(
                "Only your system can install these, and this app is not allowed to. "
                "Run each command in a terminal, then press Recheck."
            )
            problems = m.problems
            if problems:
                group = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
                for problem in problems:
                    group.append(self._problem_row(problem.message, problem.command))
                self.problem_box.append(group)
            elif m.error:
                self.problem_box.append(Gtk.Label(label=m.error.message, wrap=True))
            if os.environ.get("FLATPAK_ID") and any(
                c.level == "fail" and cid == "flatpak-32bit" for cid, c in m.checks.items()
            ):
                # A running Flatpak mounts extensions at launch only. A fresh start is needed.
                self.problem_box.append(Gtk.Label(
                    label="After the command finishes, close this window and open BFME Installer again.",
                    wrap=True,
                ))
                self.problem_box.append(pill("Close", lambda: self.get_application().quit()))
            else:
                self.problem_box.append(pill("Recheck", self.controller.recheck))
        else:
            step = title_of(m.failed_step) if m.failed_step else "the setup"
            message = m.error.message if m.error else "The setup stopped unexpectedly."
            self.problem.set_icon_name(first_icon("dialog-error-symbolic", "dialog-warning-symbolic"))
            self.problem.set_title("Something went wrong")
            self.problem.set_description(f"{step}: {message}\n\nNothing was lost. You can try this step again.")
            self.problem_box.append(pill("Retry", self.controller.retry))
            # One row: four stacked buttons do not fit.
            others = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
            if m.job == "aotr":
                # Most Age of the Ring failures come from the file.
                others.append(pill("Choose another file", self.controller.choose_another_aotr_file, suggested=False))
            others.append(pill(self._leave_label(), self.controller.back_home, suggested=False))
            others.append(pill("Copy log", lambda: self.copy(m.log_text(), "Log copied"), suggested=False))
            self.problem_box.append(others)

    def _problem_row(self, message: str, command: str | None) -> Adw.ActionRow:
        row = Adw.ActionRow(title=GLib.markup_escape_text(message))
        if command:
            row.set_subtitle(GLib.markup_escape_text(command))
            row.set_subtitle_selectable(True)
            row.add_css_class("monospace")
            button = Gtk.Button(icon_name="edit-copy-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Copy the command")
            button.add_css_class("flat")
            button.connect("clicked", lambda *_: self.copy(command, "Command copied"))
            row.add_suffix(button)
        return row

    def copy(self, text: str, toast: str) -> None:
        self.get_clipboard().set_content(Gdk.ContentProvider.new_for_value(GObject.Value(str, text)))
        self.toasts.add_toast(Adw.Toast.new(toast))

    def _on_close_request(self, _window) -> bool:
        if self.model.state == "removing":
            return self._ask_before_closing(
                "A program is still being removed",
                "If you close the window now, the removal stops half way and some of its files stay behind. "
                "Wait for it to finish.",
                "Close anyway",
            )
        if self.model.state != "running":
            return False
        return self._ask_before_closing(
            "Setup is still running",
            "If you close the window now, setup stops. Everything finished so far is kept, and you can resume later.",
            "Stop and close",
        )

    def _ask_before_closing(self, heading: str, body: str, stop_label: str) -> bool:
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("wait", "Keep going")
        dialog.add_response("stop", stop_label)
        dialog.set_response_appearance("stop", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("wait")
        dialog.connect("response", self._on_close_response)
        dialog.present(self)
        return True  # keep the window open until the user decides

    def _on_close_response(self, _dialog, response: str) -> None:
        if response == "stop":
            self.controller.stop_now()
            self.destroy()


class WizardApp(Adw.Application):
    def __init__(self, runner, offer: str | None = None) -> None:
        super().__init__(application_id=APP_ID)
        self.runner = runner
        self.offer = offer   # the program a shortcut wanted to open, when it was not installed (any more)
        self.connect("activate", self._activate)

    def _activate(self, _app) -> None:
        window = self.props.active_window
        if window is None:
            window = WizardWindow(self, lambda on_change: Controller(self.runner, on_change, offer=self.offer))
            window.controller.start()
        window.present()
