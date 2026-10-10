"""The wizard window. One page at a time, then the home screen once the setup is complete. Renders the model."""
from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk  # noqa: E402

from .controller import Controller
from .diagnostics import any_log, build_report, data_dir
from .home import GameFoldersPage, HomePage, TroubleshootPage
from .model import STEPS, description_of, title_of
from .updater import make_updater
from .widgets import clear, first_icon, pill

# Inside a Flatpak the app ID is whatever it was built as, so a copy built under another ID can run beside this one.
APP_ID = os.environ.get("FLATPAK_ID") or "com.jgbmichalski.BfmeInstaller"
INTRO = "This installs Proton, the launcher and the Arena. Workshop Studio is available from the home screen. It takes a few minutes."


class WizardWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, controller_factory, offer: str | None = None) -> None:
        super().__init__(application=app, title="BFME Installer")
        self.set_default_size(640, 560)
        self.controller: Controller = controller_factory(self.render)
        self.model = self.controller.model

        self.toasts = Adw.ToastOverlay()
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.pack_end(self._build_menu())
        toolbar.add_top_bar(header)
        # A system check failed: say so above the home screen and point at Troubleshoot.
        self.check_banner = Adw.Banner(title="Your system needs a change.", button_label="Troubleshoot")
        self.check_banner.connect("button-clicked", lambda *_: self.show_troubleshoot())
        toolbar.add_top_bar(self.check_banner)
        # The app updating itself (see updater.py). Hidden until there is something to say.
        self.updater = make_updater(self._render_update_banner)
        self.update_banner = Adw.Banner(use_markup=False)
        self.update_banner.connect("button-clicked", self._on_update_button)
        toolbar.add_top_bar(self.update_banner)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        toolbar.set_content(self.stack)
        self.nav = Adw.NavigationView()
        self.nav.add(Adw.NavigationPage.new(toolbar, "BFME Installer"))
        self.nav.connect("popped", lambda *_: setattr(self, "troubleshoot", None))
        self.troubleshoot: TroubleshootPage | None = None
        self.toasts.set_child(self.nav)
        self.set_content(self.toasts)

        self._build_checking()
        self._build_welcome()
        self._build_run()
        self._build_problem()
        self.home = HomePage(self.controller, lambda: self.updater.local or "dev", offer, self.show_troubleshoot, self.show_game_folders)
        self.stack.add_named(self.home.box, "home")

        self.connect("close-request", self._on_close_request)
        self.updater.check()
        GLib.timeout_add(120, self._pulse)  # keeps the bar moving when a step reports no percentage

    # ---------------------------------------------------------------- pages
    def _build_checking(self) -> None:
        page = Adw.StatusPage(title="Checking your setup...")
        spinner = Gtk.Spinner(spinning=True, halign=Gtk.Align.CENTER)
        spinner.set_size_request(32, 32)
        page.set_child(spinner)
        self.stack.add_named(page, "checking")

    def _build_welcome(self) -> None:
        self.welcome = Adw.StatusPage(
            icon_name=first_icon("system-software-install-symbolic", "folder-download-symbolic", "emblem-system-symbolic")
        )
        self.welcome_button = pill("Install", self.controller_call("install"))
        self.welcome.set_child(self.welcome_button)
        self.stack.add_named(self.welcome, "welcome")

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

    def _build_menu(self) -> Gtk.MenuButton:
        """The header menu: Troubleshoot is reachable from every page, even while the setup runs."""
        popover = Gtk.Popover()
        item = Gtk.Button(label="Troubleshoot", css_classes=["flat"])
        item.connect("clicked", lambda *_: (popover.popdown(), self.show_troubleshoot()))
        popover.set_child(item)
        button = Gtk.MenuButton(icon_name="open-menu-symbolic", tooltip_text="Menu")
        button.set_popover(popover)
        return button

    def controller_call(self, name: str):
        return lambda: getattr(self.controller, name)()

    # --------------------------------------------------------------- render
    # --------------------------------------------------------------- troubleshoot
    def _render_check_banner(self) -> None:
        m = self.model
        self.check_banner.set_revealed(m.state == "done" and bool(m.problems))

    def show_troubleshoot(self) -> None:
        if self.troubleshoot is not None:
            return
        self.troubleshoot = TroubleshootPage(
            self.controller, copy_text=self.copy, copy_diagnostics=self.copy_diagnostics,
            open_logs=self.open_logs, confirm_reset=self.confirm_reset,
        )
        self.nav.push(Adw.NavigationPage.new(self.troubleshoot.view, "Troubleshoot"))

    def show_game_folders(self) -> None:
        if self.nav.get_visible_page().get_title() == "Game folders":
            return
        self.nav.push(Adw.NavigationPage.new(GameFoldersPage(self.open_folder).view, "Game folders"))

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
            body="This deletes the game environment, including every game you installed. This cannot be undone.\n\n"
                 "Close the Launcher and the Arena first.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("reset", "Delete and set up again")
        dialog.set_response_appearance("reset", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda _d, response: self._do_reset() if response == "reset" else None)
        dialog.present(self)

    def _do_reset(self) -> None:
        def done(ok: bool) -> None:
            text = "The game environment was deleted." if ok else "The reset failed. Open the logs folder from Troubleshoot."
            self.toasts.add_toast(Adw.Toast.new(text))

        if self.controller.reset(done):
            while self.nav.get_visible_page().get_title() != "BFME Installer":
                self.nav.pop()
        else:
            self.toasts.add_toast(Adw.Toast.new(self.controller.blocked_reason() or "Not now."))

    # --------------------------------------------------------------- updating the app itself
    def _render_update_banner(self) -> None:
        u = self.updater
        # Not while the setup is running: the banner would compete with the progress screen.
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

    def render(self) -> None:
        self._render_update_banner()
        self._render_check_banner()
        if self.troubleshoot is not None:
            self.troubleshoot.refresh()
        m = self.model
        if m.state == "checking":
            self.stack.set_visible_child_name("checking")
        elif m.state == "done":
            self.home.refresh()
            self.stack.set_visible_child_name("home")
        elif m.state == "running":
            self._render_run()
            self.stack.set_visible_child_name("run")
        elif m.state in ("blocked", "failed"):
            self._render_problem()
            self.stack.set_visible_child_name("problem")
        else:  # idle, cancelled
            self._render_welcome()
            self.stack.set_visible_child_name("welcome")

    def _render_welcome(self) -> None:
        m = self.model
        self.welcome.set_title("Setup paused" if m.paused else "Set up BFME on Linux")
        self.welcome.set_description("Resume where you left off." if m.paused else INTRO)
        self.welcome_button.set_label("Resume" if m.paused else "Install")

    def _render_run(self) -> None:
        m = self.model
        step_id = m.current or (STEPS[min(m.done_count, len(STEPS) - 1)][0])
        self.run_count.set_text(f"Step {m.step_number} of {len(STEPS)}")
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
                # A running Flatpak mounts its extensions once, at launch, so installing them now cannot be seen from
                # inside this window. Only a fresh start picks them up.
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
            self.problem_box.append(pill("Copy log", lambda: self.copy(m.log_text(), "Log copied"), suggested=False))

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

    # --------------------------------------------------------------- closing
    def _on_close_request(self, _window) -> bool:
        if self.model.state != "running":
            return False
        dialog = Adw.AlertDialog(
            heading="Setup is still running",
            body="If you close the window now, setup stops. Everything finished so far is kept, and you can resume later.",
        )
        dialog.add_response("wait", "Keep going")
        dialog.add_response("stop", "Stop and close")
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
        self.offer = offer   # the app a menu entry wanted to open before the setup was complete
        self.connect("activate", self._activate)

    def _activate(self, _app) -> None:
        window = self.props.active_window
        if window is None:
            window = WizardWindow(self, lambda on_change: Controller(self.runner, on_change), self.offer)
            window.controller.start()
        window.present()
