"""The wizard window (variant A, "Pages": one thing on screen at a time). Renders the model; holds no setup logic."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, GObject, Gtk  # noqa: E402

from .controller import Controller
from .model import STEPS, description_of, title_of

APP_ID = "com.jgbmichalski.BfmeInstaller"
INTRO = "This installs Proton, the launcher and the Arena. It takes a few minutes."


def first_icon(*names: str) -> str | None:
    """The first icon the current theme has, so a missing icon never shows as a blurry placeholder."""
    theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
    return next((n for n in names if theme.has_icon(n)), None)


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


class WizardWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, controller_factory) -> None:
        super().__init__(application=app, title="BFME Installer")
        self.set_default_size(640, 560)
        self.controller: Controller = controller_factory(self.render)
        self.model = self.controller.model

        self.toasts = Adw.ToastOverlay()
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        toolbar.set_content(self.stack)
        self.toasts.set_child(toolbar)
        self.set_content(self.toasts)

        self._build_checking()
        self._build_welcome()
        self._build_run()
        self._build_problem()
        self._build_finish()

        self.connect("close-request", self._on_close_request)
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

    def _build_finish(self) -> None:
        page = Adw.StatusPage(
            icon_name=first_icon("emblem-ok-symbolic", "object-select-symbolic"),
            title="You're all set",
            description="Open the launcher to install your games. Start the Arena from its own button to play online.",
        )
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER)
        box.append(pill("Open the Launcher", self.controller_call("open_launcher")))
        box.append(pill("Open the Arena", self.controller_call("open_arena"), suggested=False))
        page.set_child(box)
        self.stack.add_named(page, "finish")

    def controller_call(self, name: str):
        return lambda: getattr(self.controller, name)()

    # --------------------------------------------------------------- render
    def render(self) -> None:
        m = self.model
        if m.state == "checking":
            self.stack.set_visible_child_name("checking")
        elif m.state == "done":
            self.stack.set_visible_child_name("finish")
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
    def __init__(self, runner) -> None:
        super().__init__(application_id=APP_ID)
        self.runner = runner
        self.connect("activate", self._activate)

    def _activate(self, _app) -> None:
        window = self.props.active_window
        if window is None:
            window = WizardWindow(self, lambda on_change: Controller(self.runner, on_change))
            window.controller.start()
        window.present()
