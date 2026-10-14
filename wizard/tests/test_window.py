"""The window: the icon buttons in the corner of its page, the pages they open, and what it does while a program is being removed.

Every test builds the real window (no main loop is needed to look at what it would show), so they need GTK and a display.
"""
import os
import tempfile
import unittest
from unittest import mock

from bfme_wizard.controller import Controller
from bfme_wizard.runner import ScriptRunner
from tests.helpers import buttons, descendants, gtk_or_skip, labels, make_script, wait_for
from tests.test_controller import FAKE

IDLE = "#!/usr/bin/env bash\nexit 0\n"
ALL = {"launcher": "installed", "arena": "installed", "aotr": "installed"}
# The icon buttons that lead to the other pages, by tooltip, left to right.
ICON_BUTTONS = ("Install or remove programs", "Game folders", "Troubleshoot")


_APP = None


def shared_app():
    """One application for the whole module: an application ID can be registered once per process."""
    global _APP
    if _APP is None:
        from gi.repository import Adw, Gio
        Adw.init()
        _APP = Adw.Application(application_id="org.example.BfmeWindowTest", flags=Gio.ApplicationFlags.NON_UNIQUE)
        _APP.register(None)
    return _APP


class presented_dialogs:
    """Collects the dialogs the window presents instead of showing them."""

    def __enter__(self):
        from gi.repository import Adw
        self.dialogs = []
        self._patch = mock.patch.object(Adw.AlertDialog, "present", lambda dialog, parent=None: self.dialogs.append(dialog))
        self._patch.start()
        return self.dialogs

    def __exit__(self, *exc):
        self._patch.stop()


class WindowCase(unittest.TestCase):
    def window(self, script=IDLE, installed=None, state="done"):
        self.Gtk = gtk_or_skip(self)
        from gi.repository import Adw
        from bfme_wizard import ui
        app = shared_app()
        win = ui.WizardWindow(app, lambda on_change: Controller(ScriptRunner(make_script(script)), on_change))
        self.addCleanup(win.destroy)
        win.model.installed = dict(installed if installed is not None else ALL)
        win.model.state = state
        win.render()
        self.Adw, self.ui = Adw, ui
        return win

    def corner_buttons(self, win):
        """The three icon buttons of the main page, by their tooltip. Looks everywhere on the page, so it finds them wherever
        they were put, and fails if one is there twice or is missing."""
        found = {}
        for button in buttons(win.root_page.get_child(), self.Gtk):
            tip = button.get_tooltip_text()
            if tip in ICON_BUTTONS:
                self.assertNotIn(tip, found, f"{tip} is on the page twice")
                found[tip] = button
        self.assertEqual(sorted(found), sorted(ICON_BUTTONS))
        return found

    def layout(self, win, width=640, height=560):
        """Lays the main page out at this size, as the window does when it shows it, without showing anything. Returns a
        function that gives the rectangle (x, y, width, height) of a widget, in the page's own coordinates."""
        page = win.root_page.get_child()
        page.allocate(width, height, -1, None)

        def rect(widget):
            found, bounds = widget.compute_bounds(page)
            self.assertTrue(found, f"{widget} was not laid out")
            return bounds.get_x(), bounds.get_y(), bounds.get_width(), bounds.get_height()

        return rect


class CornerButtons(WindowCase):
    """The icon buttons that lead to the other pages. They float in the top right corner of the page, under the header bar,
    and are not in the header bar."""

    NEAR = 12      # how far from the corner of the page they may sit, in pixels

    def test_there_are_three_in_one_row_with_troubleshoot_in_the_corner(self):
        win = self.window()
        found = self.corner_buttons(win)
        rect = self.layout(win)
        self.assertEqual(sorted(found, key=lambda tip: rect(found[tip])[0]), list(ICON_BUTTONS))    # left to right
        self.assertEqual(len({rect(button)[1] for button in found.values()}), 1)                    # one row

    def test_none_of_them_is_in_the_header_bar(self):
        win = self.window()
        self.assertEqual([b.get_tooltip_text() for b in buttons(win.header, self.Gtk) if b.get_tooltip_text()], [])

    def test_they_float_in_the_top_right_corner_of_the_page_under_the_header_bar(self):
        win = self.window()
        found = self.corner_buttons(win)
        rect = self.layout(win)
        page_x, page_y, page_w, page_h = rect(win.stack)       # the page is what is under the header bar and the banners
        _x, header_y, _w, header_h = rect(win.header)
        self.assertGreaterEqual(page_y, header_y + header_h)
        for tip, button in found.items():
            x, y, w, h = rect(button)
            with self.subTest(tip):
                self.assertGreaterEqual(x, page_x)
                self.assertLessEqual(x + w, page_x + page_w)
                self.assertGreaterEqual(y, page_y)                 # under the header bar, on the page
                self.assertLessEqual(y + h, page_y + page_h)
        x, y, w, _h = rect(found["Troubleshoot"])
        self.assertLessEqual(page_x + page_w - (x + w), self.NEAR)       # at the right edge of the page...
        self.assertLessEqual(y - page_y, self.NEAR)                      # ...and at its top

    def test_troubleshoot_stays_where_it_is_when_the_other_two_come_and_go(self):
        win = self.window()
        win.model.begin_plan(["launcher"])
        places = set()
        for state in ("done", "running", "idle", "done", "failed"):
            win.model.state = state
            win.render()
            places.add(self.layout(win)(self.corner_buttons(win)["Troubleshoot"]))
        self.assertEqual(len(places), 1)

    def test_they_are_on_the_main_page_only_not_on_the_pages_they_open(self):
        win = self.window()
        for show, page in ((win.show_programs, lambda: win.programs.view), (win.show_troubleshoot, lambda: win.troubleshoot.view)):
            show()
            self.assertEqual({b.get_tooltip_text() for b in buttons(page(), self.Gtk)} & set(ICON_BUTTONS), set())
            win.nav.pop()

    def things_on_the_page(self, win, rect):
        """What the visible page shows or lets the player press, as [(description, rectangle)], not counting the icon buttons.
        A label counts for the room its text takes: a centred label has a box as wide as the page, but its text does not."""
        Gtk = self.Gtk
        kinds = (Gtk.Label, Gtk.Button, Gtk.CheckButton, Gtk.Image, Gtk.ProgressBar, Gtk.Spinner, self.Adw.Avatar)
        page = win.stack.get_visible_child()
        own = set()
        for button in self.corner_buttons(win).values():
            own.update([button, *descendants(button)])

        def shown(widget):
            while widget is not page:
                if not widget.get_visible():
                    return False
                widget = widget.get_parent()
            return True

        found = []
        for widget in descendants(page):
            if not isinstance(widget, kinds) or widget in own or not shown(widget):
                continue
            x, y, w, h = rect(widget)
            if isinstance(widget, Gtk.Label):
                offset_x, offset_y = widget.get_layout_offsets()
                text = widget.get_layout().get_pixel_extents()[1]
                x, y, w, h = x + offset_x + text.x, y + offset_y + text.y, text.width, text.height
            if w > 0 and h > 0:
                name = widget.get_label() if isinstance(widget, (Gtk.Label, Gtk.Button)) else type(widget).__name__
                found.append((f"{type(widget).__name__} {name!r}", (x, y, w, h)))
        return found

    def test_nothing_on_any_page_is_under_them_at_any_size_the_window_can_have(self):
        win = self.window()
        win.model.begin_plan(["launcher"])
        page = win.root_page.get_child()
        across, down = self.Gtk.Orientation.HORIZONTAL, self.Gtk.Orientation.VERTICAL
        least_w = page.measure(across, -1)[0]
        least_h = page.measure(down, least_w)[0]               # the smallest the window can be made, as it is now
        for state in ("checking", "idle", "running", "waiting", "cancelled", "failed", "blocked", "removing", "done"):
            win.model.state = state
            win.model.removing = "arena" if state == "removing" else None
            win.render()
            for width, height in ((640, 560), (640, 700), (least_w, least_h), (800, least_h)):
                rect = self.layout(win, width, height)
                for tip, button in self.corner_buttons(win).items():
                    if not button.get_visible():
                        continue
                    bx, by, bw, bh = rect(button)
                    for what, (x, y, w, h) in self.things_on_the_page(win, rect):
                        with self.subTest(f"{state} at {width}x{height}: {what} against {tip}"):
                            self.assertFalse(x < bx + bw and bx < x + w and y < by + bh and by < y + h,
                                             f"{what} at {(round(x), round(y), round(w), round(h))} is under the {tip} button")

    def test_the_home_content_stays_centred_above_the_version_line_while_it_keeps_clear_of_them(self):
        # Keeping room at the top for the buttons must not push the cards down: the same room is kept at the bottom.
        win = self.window()
        rect = self.layout(win)
        _x, page_top, _w, _h = rect(win.stack)
        _x, content_y, _w, content_h = rect(win.home.content)
        _x, version_y, _w, _h = rect(win.home.version_label)
        room_below = version_y - win.home.version_label.get_margin_top()      # where the room left for the content ends
        self.assertAlmostEqual(content_y + content_h / 2, (page_top + room_below) / 2, delta=1)

    def test_each_has_an_icon_and_no_text(self):
        win = self.window()
        from bfme_wizard import ui
        for tip, icons in (("Install or remove programs", ui.PROGRAMS_ICONS), ("Game folders", ui.FOLDERS_ICONS),
                           ("Troubleshoot", ui.TROUBLESHOOT_ICONS)):
            button = self.corner_buttons(win)[tip]
            self.assertIn(button.get_icon_name(), icons, tip)
            self.assertIsNone(button.get_label(), tip)

    def test_the_icons_are_the_ones_the_flatpaks_runtime_has(self):
        # The host's icon theme has more than the GNOME runtime: a name only the host knows shows a broken image there.
        import glob
        gtk_or_skip(self)
        runtime = glob.glob(os.path.expanduser("~/.local/share/flatpak/runtime/org.gnome.Platform/x86_64/*/*/files/share/icons/Adwaita/symbolic"))
        if not runtime:
            self.skipTest("the GNOME runtime is not installed here")
        from bfme_wizard import ui
        available = {os.path.basename(p)[:-4] for p in glob.glob(runtime[0] + "/**/*.svg", recursive=True)}
        for icons in (ui.PROGRAMS_ICONS, ui.FOLDERS_ICONS, ui.TROUBLESHOOT_ICONS):
            self.assertIn(icons[0], available, f"{icons[0]} is first in its list, so it is the one most players see")

    def test_the_old_menu_button_is_gone(self):
        win = self.window()
        self.assertFalse([w for w in descendants(win.root_page.get_child()) if isinstance(w, self.Gtk.MenuButton)])

    def test_troubleshoot_is_always_there_and_the_other_two_belong_to_the_home_screen(self):
        win = self.window()
        win.model.begin_plan(["launcher"])          # the run page shows a step of the plan
        for state in ("checking", "idle", "running", "waiting", "cancelled", "failed", "blocked", "removing", "done"):
            with self.subTest(state):
                win.model.state = state
                win.model.removing = "arena" if state == "removing" else None
                win.render()
                shown = {tip: b.get_visible() for tip, b in self.corner_buttons(win).items()}
                home = state == "done"
                self.assertEqual(shown, {"Install or remove programs": home, "Game folders": home, "Troubleshoot": True})

    def test_the_old_buttons_are_gone_from_the_home_screen(self):
        win = self.window()
        self.assertEqual({b.get_label() for b in buttons(win.home.box, self.Gtk)}, {"Open"})


class Pages(WindowCase):
    def test_the_buttons_open_their_pages_and_going_back_forgets_them(self):
        win = self.window()
        for tip, title, attribute in (("Install or remove programs", "Programs", "programs"),
                                      ("Troubleshoot", "Troubleshoot", "troubleshoot"),
                                      ("Game folders", "Game folders", None)):
            with self.subTest(tip):
                self.corner_buttons(win)[tip].emit("clicked")
                self.assertEqual(win.nav.get_visible_page().get_title(), title)
                if attribute:
                    self.assertIsNotNone(getattr(win, attribute))
                win.nav.pop()
                if attribute:
                    self.assertIsNone(getattr(win, attribute))
                self.assertIs(win.nav.get_visible_page(), win.root_page)

    def test_a_second_press_does_not_stack_another_copy(self):
        win = self.window()
        win.show_programs()
        win.show_programs()
        self.assertEqual(win.nav.get_navigation_stack().get_n_items(), 2)

    def test_popping_a_page_does_not_forget_the_one_underneath_it(self):
        # No button leads from one pushed page to another today, but the bookkeeping must be exact: a page that is still
        # in the stack and forgotten would be pushed a second time, and never refreshed.
        win = self.window()
        win.show_troubleshoot()
        win.show_programs()
        win.nav.pop()
        self.assertIsNone(win.programs)
        self.assertIsNotNone(win.troubleshoot)
        win.show_troubleshoot()                                   # still open: nothing new is pushed
        self.assertEqual(win.nav.get_navigation_stack().get_n_items(), 2)
        win.nav.pop()
        self.assertIsNone(win.troubleshoot)

    def test_installing_from_the_programs_page_goes_back_to_the_main_page_and_installs_that_program(self):
        win = self.window(installed={"launcher": "installed", "arena": "installed"})
        asked = []
        win.controller.install = asked.append
        win.show_programs()
        win.install_program("aotr")
        self.assertIs(win.nav.get_visible_page(), win.root_page)
        self.assertEqual(asked, [["aotr"]])
        win.install_program("arena")       # the Arena installs with the AIO Launcher
        self.assertEqual(asked[-1], ["launcher"])

    def test_the_programs_page_does_not_outlive_the_home_screen(self):
        # The last program was removed, or the setup is being started over: there is nothing to manage.
        for state in ("idle", "cancelled", "running", "waiting", "failed", "blocked"):
            with self.subTest(state):
                win = self.window()
                win.model.begin_plan(["launcher"])
                win.show_programs()
                win.model.state = state
                win.render()
                self.assertIs(win.nav.get_visible_page(), win.root_page)
                self.assertIsNone(win.programs)

    def test_the_programs_page_stays_while_the_setup_is_looked_at_again(self):
        win = self.window()
        win.show_programs()
        for state in ("checking", "done"):
            win.model.state = state
            win.render()
            self.assertEqual(win.nav.get_visible_page().get_title(), "Programs", state)

    def test_its_rows_hold_still_while_the_answer_is_awaited(self):
        # After a removal the controller forgets what it knew and asks again. For that moment the model says nothing is
        # installed, which must not flash across the rows ("Not installed" three times) before the real answer is there.
        win = self.window()
        win.show_programs()
        before = [(r.get_title(), r.get_subtitle()) for r in win.programs.rows()]
        win.model.installed.clear()                 # what Controller.start does
        win.model.state = "checking"
        win.render()
        self.assertEqual([(r.get_title(), r.get_subtitle()) for r in win.programs.rows()], before)
        self.assertFalse(win._programs_page.get_can_pop())      # it is still the removal finishing: no way out yet
        win.model.installed.update(launcher="installed", arena="installed")      # the answer: Age of the Ring is gone
        win.model.state = "done"
        win.render()
        self.assertEqual([r.get_subtitle()[:13] for r in win.programs.rows()], ["Installed", "Installed", "Not installed"])
        self.assertTrue(win._programs_page.get_can_pop())

    def test_the_page_cannot_be_left_while_a_program_is_removed(self):
        win = self.window()
        win.show_programs()
        for state in ("removing", "checking"):
            win.model.state, win.model.removing = state, "arena" if state == "removing" else None
            win.render()
            self.assertFalse(win._programs_page.get_can_pop(), state)
        win.model.state = "done"
        win.render()
        self.assertTrue(win._programs_page.get_can_pop())

    def test_its_rows_follow_the_model(self):
        win = self.window(installed={"launcher": "installed", "arena": "installed"})
        win.show_programs()
        titles = lambda: [(r.get_title(), r.get_subtitle()) for r in win.programs.rows()]
        self.assertEqual(titles()[2][0], "Age of the Ring")
        win.model.installed["aotr"] = "installed"
        win.render()
        self.assertEqual(titles()[2], ("Age of the Ring", "Installed"))


class Removal(WindowCase):
    def dialog_for(self, win, program):
        with presented_dialogs() as dialogs:
            win.confirm_remove(program)
        return dialogs[-1]

    def test_the_confirmation_names_the_program_says_what_stays_and_offers_a_way_out(self):
        win = self.window()
        for program, heading in (("launcher", "Remove the AIO Launcher?"), ("arena", "Remove the Arena?"),
                                 ("aotr", "Remove Age of the Ring?")):
            with self.subTest(program):
                dialog = self.dialog_for(win, program)
                self.assertEqual(dialog.get_heading(), heading)
                self.assertIn("not touched", dialog.get_body())
                self.assertIn("install it again from the Programs page", dialog.get_body())
                self.assertIn("Close the AIO Launcher, the Arena and Age of the Ring first", dialog.get_body())
                self.assertEqual(dialog.get_response_label("remove"), "Remove")
                self.assertEqual(dialog.get_response_appearance("remove"), self.Adw.ResponseAppearance.DESTRUCTIVE)
                self.assertEqual((dialog.get_default_response(), dialog.get_close_response()), ("cancel", "cancel"))

    def test_the_reset_dialog_also_names_the_aio_launcher_among_the_programs_to_close(self):
        win = self.window()
        with presented_dialogs() as dialogs:
            win.confirm_reset()
        self.assertIn("Close the AIO Launcher, the Arena and Age of the Ring first", dialogs[-1].get_body())

    def test_a_removal_toast_says_the_aio_launcher_in_full(self):
        win = self.window()
        win.controller.remove = lambda program, on_done: on_done(True) or True
        with mock.patch.object(win.toasts, "add_toast") as toast:
            win._do_remove("launcher")
        self.assertEqual(toast.call_args[0][0].get_title(), "The AIO Launcher was removed.")

    def test_what_stays_is_named_with_the_aio_launcher_in_full(self):
        # Age of the Ring has a launcher of its own, so "the Launcher" in these sentences could be either one.
        win = self.window()
        self.assertIn("The AIO Launcher, the games and Age of the Ring are not touched.", self.dialog_for(win, "arena").get_body())
        self.assertIn("The AIO Launcher, the Arena and the games you installed with the AIO Launcher are not touched.",
                      self.dialog_for(win, "aotr").get_body())

    def test_age_of_the_ring_says_how_much_room_it_gives_back_and_what_it_keeps(self):
        dialog = self.dialog_for(self.window(), "aotr")
        self.assertIn("22 GB", dialog.get_body())
        self.assertIn("Your settings for it are kept", dialog.get_body())

    def test_cancel_removes_nothing_and_remove_asks_the_controller(self):
        win = self.window()
        asked = []
        win.controller.remove = lambda program, on_done: asked.append(program) or True
        dialog = self.dialog_for(win, "arena")
        dialog.emit("response", "cancel")
        self.assertEqual(asked, [])
        dialog.emit("response", "remove")
        self.assertEqual(asked, ["arena"])

    def test_a_removal_that_cannot_start_says_why(self):
        win = self.window()
        win.controller.apps.state["launcher"] = "running"
        with mock.patch.object(win.toasts, "add_toast") as toast:
            win._do_remove("arena")
        self.assertIn("still running", toast.call_args[0][0].get_title())

    def test_the_whole_removal_with_a_real_script_ends_on_the_home_screen_with_a_toast(self):
        self.addCleanup(os.environ.pop, "FAKE_DIR", None)
        os.environ["FAKE_DIR"] = tempfile.mkdtemp()
        for flag in ("prefix", "launcher", "arena", "aotr"):
            open(os.path.join(os.environ["FAKE_DIR"], flag), "w").close()
        win = self.window(FAKE, state="checking")
        win.controller.start()
        wait_for(8000, lambda: win.model.state == "done" and not win.controller.runner.busy)
        win.show_programs()
        toasts = []
        with mock.patch.object(win.toasts, "add_toast", side_effect=lambda t: toasts.append(t.get_title())):
            win._do_remove("arena")
            self.assertEqual(win.model.state, "removing")
            self.assertEqual(win.stack.get_visible_child_name(), "removing")
            self.assertFalse(win._programs_page.get_can_pop())
            wait_for(8000, lambda: win.model.state == "done" and not win.controller.runner.busy)
        self.assertEqual(toasts, ["The Arena was removed."])
        self.assertEqual(win.nav.get_visible_page().get_title(), "Programs")     # still there, now with the Arena as missing
        self.assertTrue(win._programs_page.get_can_pop())
        self.assertEqual([(r.get_title(), self.row_button(r)) for r in win.programs.rows()],
                         [("AIO Launcher", "Remove"), ("Arena", "Install"), ("Age of the Ring", "Remove")])
        self.assertEqual(labels(win.home.content, self.Gtk, "title-2"), ["AIO Launcher", "Age of the Ring"])

    def row_button(self, row):
        return [b.get_label() for b in buttons(row, self.Gtk)][0]

    def test_removing_the_last_program_lands_on_the_start_page(self):
        self.addCleanup(os.environ.pop, "FAKE_DIR", None)
        os.environ["FAKE_DIR"] = tempfile.mkdtemp()
        for flag in ("prefix", "aotr"):
            open(os.path.join(os.environ["FAKE_DIR"], flag), "w").close()
        win = self.window(FAKE, state="checking")
        win.controller.start()
        wait_for(8000, lambda: win.model.state == "done" and not win.controller.runner.busy)
        win.show_programs()
        win._do_remove("aotr")
        wait_for(8000, lambda: win.model.state == "idle" and not win.controller.runner.busy)
        self.assertIs(win.nav.get_visible_page(), win.root_page)
        self.assertEqual(win.stack.get_visible_child_name(), "start")
        self.assertEqual(win.start.view.get_title(), "Choose what to install")      # the game environment is still ready

    def test_a_removal_that_fails_says_so_and_nothing_changes(self):
        self.addCleanup(os.environ.pop, "FAKE_DIR", None)
        os.environ["FAKE_DIR"] = tempfile.mkdtemp()
        for flag in ("prefix", "launcher", "arena", "remove-fails"):
            open(os.path.join(os.environ["FAKE_DIR"], flag), "w").close()
        win = self.window(FAKE, state="checking")
        win.controller.start()
        wait_for(8000, lambda: win.model.state == "done" and not win.controller.runner.busy)
        toasts = []
        with mock.patch.object(win.toasts, "add_toast", side_effect=lambda t: toasts.append(t.get_title())):
            win._do_remove("launcher")
            wait_for(8000, lambda: win.model.state == "done" and not win.controller.runner.busy)
        self.assertEqual(toasts, ["Could not remove the AIO Launcher: Could not remove it"])
        self.assertTrue(win.model.is_installed("launcher"))

    def test_the_page_shown_while_it_runs_says_what_is_going(self):
        win = self.window()
        win.model.state, win.model.removing = "removing", "aotr"
        win.render()
        self.assertEqual(win.stack.get_visible_child_name(), "removing")
        self.assertEqual(win.removing_page.get_title(), "Removing Age of the Ring...")

    def test_closing_the_window_in_the_middle_of_a_removal_asks_first(self):
        win = self.window()
        win.model.state, win.model.removing = "removing", "arena"
        with presented_dialogs() as dialogs:
            self.assertTrue(win._on_close_request(win))                  # the window stays
        dialog = dialogs[-1]
        self.assertEqual(dialog.get_heading(), "A program is still being removed")
        self.assertEqual((dialog.get_default_response(), dialog.get_response_label("stop")), ("wait", "Close anyway"))

    def test_closing_the_window_otherwise_just_closes(self):
        win = self.window()
        self.assertFalse(win._on_close_request(win))
        win.model.begin_plan(["launcher"])
        win.model.state = "running"
        with presented_dialogs() as dialogs:
            self.assertTrue(win._on_close_request(win))
        self.assertEqual(dialogs[-1].get_heading(), "Setup is still running")


if __name__ == "__main__":
    unittest.main()
