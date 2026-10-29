"""The window: the icon buttons in the corner of its page, the pages they open, and what it does while a program is being removed.

Every test builds the real window (no main loop is needed to look at what it would show), so they need GTK and a display.
"""
import glob
import os

import pytest

from bfme_wizard.controller import Controller
from bfme_wizard.runner import ScriptRunner
from tests.helpers import buttons, descendants, labels, make_script, wait_for
from tests.test_controller import FAKE

IDLE = "#!/usr/bin/env bash\nexit 0\n"
ALL = {"launcher": "installed", "arena": "installed", "aotr": "installed"}
# The icon buttons that lead to the other pages, by tooltip, left to right.
ICON_BUTTONS = ("Install or remove programs", "Game folders", "Troubleshoot")
NEAR = 12      # how far from the corner of the page the icon buttons may sit, in pixels


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


@pytest.fixture
def make_window(gtk):
    """Builds windows for the test and destroys them afterwards."""
    from bfme_wizard import ui
    made = []

    def make(script=IDLE, installed=None, state="done"):
        win = ui.WizardWindow(shared_app(), lambda on_change: Controller(ScriptRunner(make_script(script)), on_change))
        made.append(win)
        win.model.installed = dict(installed if installed is not None else ALL)
        win.model.state = state
        win.render()
        return win

    yield make
    for win in made:
        win.destroy()


@pytest.fixture
def win(make_window):
    return make_window()


@pytest.fixture
def dialogs(gtk, monkeypatch):
    """Collects the dialogs the window presents instead of showing them."""
    from gi.repository import Adw
    presented = []
    monkeypatch.setattr(Adw.AlertDialog, "present", lambda dialog, parent=None: presented.append(dialog))
    return presented


@pytest.fixture
def toasts(monkeypatch):
    """Returns a function that collects the titles of the toasts a window shows instead of showing them."""
    def collect(win):
        titles = []
        monkeypatch.setattr(win.toasts, "add_toast", lambda toast: titles.append(toast.get_title()))
        return titles
    return collect


@pytest.fixture
def fake_dir(tmp_path, monkeypatch):
    """Returns a function that makes the fake script see these flags."""
    monkeypatch.setenv("FAKE_DIR", str(tmp_path))

    def flags(*names):
        for flag in names:
            (tmp_path / flag).touch()
    return flags


def corner_buttons(win, Gtk):
    """The three icon buttons of the main page, by their tooltip. Looks everywhere on the page, so it finds them wherever
    they were put, and fails if one is there twice or is missing."""
    found = {}
    for button in buttons(win.root_page.get_child(), Gtk):
        tip = button.get_tooltip_text()
        if tip in ICON_BUTTONS:
            assert tip not in found, f"{tip} is on the page twice"
            found[tip] = button
    assert sorted(found) == sorted(ICON_BUTTONS)
    return found


def layout(win, width=640, height=560):
    """Lays the main page out at this size, as the window does when it shows it, without showing anything. Returns a
    function that gives the rectangle (x, y, width, height) of a widget, in the page's own coordinates."""
    page = win.root_page.get_child()
    page.allocate(width, height, -1, None)

    def rect(widget):
        found, bounds = widget.compute_bounds(page)
        assert found, f"{widget} was not laid out"
        return bounds.get_x(), bounds.get_y(), bounds.get_width(), bounds.get_height()

    return rect


# The icon buttons that lead to the other pages. They float in the top right corner of the page, under the header bar,
# and are not in the header bar.

def test_there_are_three_in_one_row_with_troubleshoot_in_the_corner(win, gtk):
    found = corner_buttons(win, gtk)
    rect = layout(win)
    assert sorted(found, key=lambda tip: rect(found[tip])[0]) == list(ICON_BUTTONS)    # left to right
    assert len({rect(button)[1] for button in found.values()}) == 1                    # one row


def test_none_of_them_is_in_the_header_bar(win, gtk):
    assert [b.get_tooltip_text() for b in buttons(win.header, gtk) if b.get_tooltip_text()] == []


def test_they_float_in_the_top_right_corner_of_the_page_under_the_header_bar(win, gtk):
    found = corner_buttons(win, gtk)
    rect = layout(win)
    page_x, page_y, page_w, page_h = rect(win.stack)       # the page is what is under the header bar and the banners
    _x, header_y, _w, header_h = rect(win.header)
    assert page_y >= header_y + header_h
    for tip, button in found.items():
        x, y, w, h = rect(button)
        assert x >= page_x, tip
        assert x + w <= page_x + page_w, tip
        assert y >= page_y, tip                 # under the header bar, on the page
        assert y + h <= page_y + page_h, tip
    x, y, w, _h = rect(found["Troubleshoot"])
    assert page_x + page_w - (x + w) <= NEAR       # at the right edge of the page...
    assert y - page_y <= NEAR                      # ...and at its top


def test_troubleshoot_stays_where_it_is_when_the_other_two_come_and_go(win, gtk):
    win.model.begin_plan(["launcher"])
    places = set()
    for state in ("done", "running", "idle", "done", "failed"):
        win.model.state = state
        win.render()
        places.add(layout(win)(corner_buttons(win, gtk)["Troubleshoot"]))
    assert len(places) == 1


def test_they_are_on_the_main_page_only_not_on_the_pages_they_open(win, gtk):
    for show, page in ((win.show_programs, lambda: win.programs.view), (win.show_troubleshoot, lambda: win.troubleshoot.view)):
        show()
        assert {b.get_tooltip_text() for b in buttons(page(), gtk)} & set(ICON_BUTTONS) == set()
        win.nav.pop()


def things_on_the_page(win, rect, Gtk):
    """What the visible page shows or lets the player press, as [(description, rectangle)], not counting the icon buttons.
    A label counts for the room its text takes: a centred label has a box as wide as the page, but its text does not."""
    from gi.repository import Adw
    kinds = (Gtk.Label, Gtk.Button, Gtk.CheckButton, Gtk.Image, Gtk.ProgressBar, Gtk.Spinner, Adw.Avatar)
    page = win.stack.get_visible_child()
    own = set()
    for button in corner_buttons(win, Gtk).values():
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


def test_nothing_on_any_page_is_under_them_at_any_size_the_window_can_have(win, gtk):
    win.model.begin_plan(["launcher"])
    page = win.root_page.get_child()
    across, down = gtk.Orientation.HORIZONTAL, gtk.Orientation.VERTICAL
    least_w = page.measure(across, -1)[0]
    least_h = page.measure(down, least_w)[0]               # the smallest the window can be made, as it is now
    for state in ("checking", "idle", "running", "waiting", "cancelled", "failed", "blocked", "removing", "done"):
        win.model.state = state
        win.model.removing = "arena" if state == "removing" else None
        win.render()
        for width, height in ((640, 560), (640, 700), (least_w, least_h), (800, least_h)):
            rect = layout(win, width, height)
            for tip, button in corner_buttons(win, gtk).items():
                if not button.get_visible():
                    continue
                bx, by, bw, bh = rect(button)
                for what, (x, y, w, h) in things_on_the_page(win, rect, gtk):
                    assert not (x < bx + bw and bx < x + w and y < by + bh and by < y + h), \
                        f"{state} at {width}x{height}: {what} at {(round(x), round(y), round(w), round(h))} is under the {tip} button"


def test_the_home_content_stays_centred_above_the_version_line_while_it_keeps_clear_of_them(win):
    # Keeping room at the top for the buttons must not push the cards down: the same room is kept at the bottom.
    rect = layout(win)
    _x, page_top, _w, _h = rect(win.stack)
    _x, content_y, _w, content_h = rect(win.home.content)
    _x, version_y, _w, _h = rect(win.home.version_label)
    room_below = version_y - win.home.version_label.get_margin_top()      # where the room left for the content ends
    assert content_y + content_h / 2 == pytest.approx((page_top + room_below) / 2, abs=1)


@pytest.mark.parametrize("tip, icons_name", [("Install or remove programs", "PROGRAMS_ICONS"),
                                             ("Game folders", "FOLDERS_ICONS"),
                                             ("Troubleshoot", "TROUBLESHOOT_ICONS")])
def test_each_has_an_icon_and_no_text(win, gtk, tip, icons_name):
    from bfme_wizard import ui
    button = corner_buttons(win, gtk)[tip]
    assert button.get_icon_name() in getattr(ui, icons_name)
    assert button.get_label() is None


def test_the_icons_are_the_ones_the_flatpaks_runtime_has(gtk):
    # The host's icon theme has more than the GNOME runtime: a name only the host knows shows a broken image there.
    runtime = glob.glob(os.path.expanduser("~/.local/share/flatpak/runtime/org.gnome.Platform/x86_64/*/*/files/share/icons/Adwaita/symbolic"))
    if not runtime:
        pytest.skip("the GNOME runtime is not installed here")
    from bfme_wizard import ui
    available = {os.path.basename(p)[:-4] for p in glob.glob(runtime[0] + "/**/*.svg", recursive=True)}
    for icons in (ui.PROGRAMS_ICONS, ui.FOLDERS_ICONS, ui.TROUBLESHOOT_ICONS):
        assert icons[0] in available, f"{icons[0]} is first in its list, so it is the one most players see"


def test_the_old_menu_button_is_gone(win, gtk):
    assert not [w for w in descendants(win.root_page.get_child()) if isinstance(w, gtk.MenuButton)]


@pytest.mark.parametrize("state", ["checking", "idle", "running", "waiting", "cancelled", "failed", "blocked", "removing", "done"])
def test_troubleshoot_is_always_there_and_the_other_two_belong_to_the_home_screen(win, gtk, state):
    win.model.begin_plan(["launcher"])          # the run page shows a step of the plan
    win.model.state = state
    win.model.removing = "arena" if state == "removing" else None
    win.render()
    shown = {tip: b.get_visible() for tip, b in corner_buttons(win, gtk).items()}
    home = state == "done"
    assert shown == {"Install or remove programs": home, "Game folders": home, "Troubleshoot": True}


def test_the_old_buttons_are_gone_from_the_home_screen(win, gtk):
    assert {b.get_label() for b in buttons(win.home.box, gtk)} == {"Open"}


# Pages

@pytest.mark.parametrize("tip, title, attribute", [("Install or remove programs", "Programs", "programs"),
                                                   ("Troubleshoot", "Troubleshoot", "troubleshoot"),
                                                   ("Game folders", "Game folders", None)])
def test_the_buttons_open_their_pages_and_going_back_forgets_them(win, gtk, tip, title, attribute):
    corner_buttons(win, gtk)[tip].emit("clicked")
    assert win.nav.get_visible_page().get_title() == title
    if attribute:
        assert getattr(win, attribute) is not None
    win.nav.pop()
    if attribute:
        assert getattr(win, attribute) is None
    assert win.nav.get_visible_page() is win.root_page


def test_a_second_press_does_not_stack_another_copy(win):
    win.show_programs()
    win.show_programs()
    assert win.nav.get_navigation_stack().get_n_items() == 2


def test_popping_a_page_does_not_forget_the_one_underneath_it(win):
    # No button leads from one pushed page to another today, but the bookkeeping must be exact: a page that is still
    # in the stack and forgotten would be pushed a second time, and never refreshed.
    win.show_troubleshoot()
    win.show_programs()
    win.nav.pop()
    assert win.programs is None
    assert win.troubleshoot is not None
    win.show_troubleshoot()                                   # still open: nothing new is pushed
    assert win.nav.get_navigation_stack().get_n_items() == 2
    win.nav.pop()
    assert win.troubleshoot is None


def test_installing_from_the_programs_page_goes_back_to_the_main_page_and_installs_that_program(make_window):
    win = make_window(installed={"launcher": "installed", "arena": "installed"})
    asked = []
    win.controller.install = asked.append
    win.show_programs()
    win.install_program("aotr")
    assert win.nav.get_visible_page() is win.root_page
    assert asked == [["aotr"]]
    win.install_program("arena")       # the Arena installs with the AIO Launcher
    assert asked[-1] == ["launcher"]


@pytest.mark.parametrize("state", ["idle", "cancelled", "running", "waiting", "failed", "blocked"])
def test_the_programs_page_does_not_outlive_the_home_screen(win, state):
    # The last program was removed, or the setup is being started over: there is nothing to manage.
    win.model.begin_plan(["launcher"])
    win.show_programs()
    win.model.state = state
    win.render()
    assert win.nav.get_visible_page() is win.root_page
    assert win.programs is None


def test_the_programs_page_stays_while_the_setup_is_looked_at_again(win):
    win.show_programs()
    for state in ("checking", "done"):
        win.model.state = state
        win.render()
        assert win.nav.get_visible_page().get_title() == "Programs", state


def test_its_rows_hold_still_while_the_answer_is_awaited(win):
    # After a removal the controller forgets what it knew and asks again. For that moment the model says nothing is
    # installed, which must not flash across the rows ("Not installed" three times) before the real answer is there.
    win.show_programs()
    before = [(r.get_title(), r.get_subtitle()) for r in win.programs.rows()]
    win.model.installed.clear()                 # what Controller.start does
    win.model.state = "checking"
    win.render()
    assert [(r.get_title(), r.get_subtitle()) for r in win.programs.rows()] == before
    assert not win._programs_page.get_can_pop()      # it is still the removal finishing: no way out yet
    win.model.installed.update(launcher="installed", arena="installed")      # the answer: Age of the Ring is gone
    win.model.state = "done"
    win.render()
    assert [r.get_subtitle()[:13] for r in win.programs.rows()] == ["Installed", "Installed", "Not installed"]
    assert win._programs_page.get_can_pop()


def test_the_page_cannot_be_left_while_a_program_is_removed(win):
    win.show_programs()
    for state in ("removing", "checking"):
        win.model.state, win.model.removing = state, "arena" if state == "removing" else None
        win.render()
        assert not win._programs_page.get_can_pop(), state
    win.model.state = "done"
    win.render()
    assert win._programs_page.get_can_pop()


def test_its_rows_follow_the_model(make_window):
    win = make_window(installed={"launcher": "installed", "arena": "installed"})
    win.show_programs()
    titles = lambda: [(r.get_title(), r.get_subtitle()) for r in win.programs.rows()]
    assert titles()[2][0] == "Age of the Ring"
    win.model.installed["aotr"] = "installed"
    win.render()
    assert titles()[2] == ("Age of the Ring", "Installed")


# Removal

def dialog_for(win, dialogs, program):
    win.confirm_remove(program)
    return dialogs[-1]


def row_button(row, Gtk):
    return [b.get_label() for b in buttons(row, Gtk)][0]


@pytest.mark.parametrize("program, heading", [("launcher", "Remove the AIO Launcher?"), ("arena", "Remove the Arena?"),
                                              ("aotr", "Remove Age of the Ring?")])
def test_the_confirmation_names_the_program_says_what_stays_and_offers_a_way_out(win, dialogs, program, heading):
    from gi.repository import Adw
    dialog = dialog_for(win, dialogs, program)
    assert dialog.get_heading() == heading
    assert "not touched" in dialog.get_body()
    assert "install it again from the Programs page" in dialog.get_body()
    assert "Close the AIO Launcher, the Arena and Age of the Ring first" in dialog.get_body()
    assert dialog.get_response_label("remove") == "Remove"
    assert dialog.get_response_appearance("remove") == Adw.ResponseAppearance.DESTRUCTIVE
    assert (dialog.get_default_response(), dialog.get_close_response()) == ("cancel", "cancel")


def test_the_reset_dialog_also_names_the_aio_launcher_among_the_programs_to_close(win, dialogs):
    win.confirm_reset()
    assert "Close the AIO Launcher, the Arena and Age of the Ring first" in dialogs[-1].get_body()


def test_a_removal_toast_says_the_aio_launcher_in_full(win, toasts):
    win.controller.remove = lambda program, on_done: on_done(True) or True
    shown = toasts(win)
    win._do_remove("launcher")
    assert shown[-1] == "The AIO Launcher was removed."


def test_what_stays_is_named_with_the_aio_launcher_in_full(win, dialogs):
    # Age of the Ring has a launcher of its own, so "the Launcher" in these sentences could be either one.
    assert "The AIO Launcher, the games and Age of the Ring are not touched." in dialog_for(win, dialogs, "arena").get_body()
    assert "The AIO Launcher, the Arena and the games you installed with the AIO Launcher are not touched." in \
        dialog_for(win, dialogs, "aotr").get_body()


def test_age_of_the_ring_says_how_much_room_it_gives_back_and_what_it_keeps(win, dialogs):
    dialog = dialog_for(win, dialogs, "aotr")
    assert "22 GB" in dialog.get_body()
    assert "Your settings for it are kept" in dialog.get_body()


def test_cancel_removes_nothing_and_remove_asks_the_controller(win, dialogs):
    asked = []
    win.controller.remove = lambda program, on_done: asked.append(program) or True
    dialog = dialog_for(win, dialogs, "arena")
    dialog.emit("response", "cancel")
    assert asked == []
    dialog.emit("response", "remove")
    assert asked == ["arena"]


def test_a_removal_that_cannot_start_says_why(win, toasts):
    win.controller.apps.state["launcher"] = "running"
    shown = toasts(win)
    win._do_remove("arena")
    assert "still running" in shown[-1]


def test_the_whole_removal_with_a_real_script_ends_on_the_home_screen_with_a_toast(make_window, gtk, fake_dir, toasts):
    fake_dir("prefix", "launcher", "arena", "aotr")
    win = make_window(FAKE, state="checking")
    win.controller.start()
    wait_for(8000, lambda: win.model.state == "done" and not win.controller.runner.busy)
    win.show_programs()
    shown = toasts(win)
    win._do_remove("arena")
    assert win.model.state == "removing"
    assert win.stack.get_visible_child_name() == "removing"
    assert not win._programs_page.get_can_pop()
    wait_for(8000, lambda: win.model.state == "done" and not win.controller.runner.busy)
    assert shown == ["The Arena was removed."]
    assert win.nav.get_visible_page().get_title() == "Programs"     # still there, now with the Arena as missing
    assert win._programs_page.get_can_pop()
    assert [(r.get_title(), row_button(r, gtk)) for r in win.programs.rows()] == \
        [("AIO Launcher", "Remove"), ("Arena", "Install"), ("Age of the Ring", "Remove")]
    assert labels(win.home.content, gtk, "title-2") == ["AIO Launcher", "Age of the Ring"]


def test_removing_the_last_program_lands_on_the_start_page(make_window, fake_dir):
    fake_dir("prefix", "aotr")
    win = make_window(FAKE, state="checking")
    win.controller.start()
    wait_for(8000, lambda: win.model.state == "done" and not win.controller.runner.busy)
    win.show_programs()
    win._do_remove("aotr")
    wait_for(8000, lambda: win.model.state == "idle" and not win.controller.runner.busy)
    assert win.nav.get_visible_page() is win.root_page
    assert win.stack.get_visible_child_name() == "start"
    assert win.start.view.get_title() == "Choose what to install"      # the game environment is still ready


def test_a_removal_that_fails_says_so_and_nothing_changes(make_window, fake_dir, toasts):
    fake_dir("prefix", "launcher", "arena", "remove-fails")
    win = make_window(FAKE, state="checking")
    win.controller.start()
    wait_for(8000, lambda: win.model.state == "done" and not win.controller.runner.busy)
    shown = toasts(win)
    win._do_remove("launcher")
    wait_for(8000, lambda: win.model.state == "done" and not win.controller.runner.busy)
    assert shown == ["Could not remove the AIO Launcher: Could not remove it"]
    assert win.model.is_installed("launcher")


def test_the_page_shown_while_it_runs_says_what_is_going(win):
    win.model.state, win.model.removing = "removing", "aotr"
    win.render()
    assert win.stack.get_visible_child_name() == "removing"
    assert win.removing_page.get_title() == "Removing Age of the Ring..."


def test_closing_the_window_in_the_middle_of_a_removal_asks_first(win, dialogs):
    win.model.state, win.model.removing = "removing", "arena"
    assert win._on_close_request(win)                  # the window stays
    dialog = dialogs[-1]
    assert dialog.get_heading() == "A program is still being removed"
    assert (dialog.get_default_response(), dialog.get_response_label("stop")) == ("wait", "Close anyway")


def test_closing_the_window_otherwise_just_closes(win, dialogs):
    assert not win._on_close_request(win)
    win.model.begin_plan(["launcher"])
    win.model.state = "running"
    assert win._on_close_request(win)
    assert dialogs[-1].get_heading() == "Setup is still running"
