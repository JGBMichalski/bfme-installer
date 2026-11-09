"""The home screen: a card with Open for each installed program."""

from tests.fake_jobs import idle_controller
from tests.helpers import buttons, labels, status


def feed(model, *events):
    for event in events:
        model.feed_event(event)


# The home screen shows the programs that are installed, each with a button to open it. Installing and removing
# programs is the Programs page's job, and the buttons for the other pages float in the corner of the window's page.

ALL = status("aio-launcher", "arena", "aotr")


def home_page(installed):
    from bfme_wizard.ui.pages.home import HomePage

    c = idle_controller()
    c.model.status = installed
    page = HomePage(c, lambda: "1.0.0")
    page.refresh()
    return c, page


def titles(Gtk, installed):
    _c, page = home_page(installed)
    return labels(page.content, Gtk, "title-2")


def test_only_the_installed_programs_have_a_card(gtk):
    assert titles(gtk, ALL) == ["AIO Launcher", "Arena", "Age of the Ring"]
    assert titles(gtk, status("aio-launcher", "arena")) == ["AIO Launcher", "Arena"]
    assert titles(gtk, status("aotr")) == ["Age of the Ring"]
    assert titles(gtk, status("arena")) == ["Arena"]
    assert titles(gtk, status("aio-launcher", "aotr")) == ["AIO Launcher", "Age of the Ring"]


def test_a_program_that_is_not_there_leaves_no_trace_of_itself(gtk):
    _c, page = home_page(status("aio-launcher"))
    text = " ".join(labels(page.content, gtk))
    for word in ("Arena", "Age of the Ring", "Not installed", "Comes with"):
        assert word not in text


def test_every_card_has_one_open_button_and_it_starts_its_own_program(gtk):
    c, page = home_page(ALL)
    opened = []
    c.open_app = opened.append
    found = buttons(page.content, gtk)
    assert [b.get_label() for b in found] == ["Open"] * 3
    for button in found:
        button.emit("clicked")
    assert opened == ["aio-launcher", "arena", "aotr"]


def test_nothing_to_install_or_to_navigate_is_left_on_the_page(gtk):
    # Install belongs to the Programs page; Game folders and Settings are buttons in the corner of the window's page.
    _c, page = home_page(ALL)
    assert {b.get_label() for b in buttons(page.box, gtk)} == {"Open"}


def test_a_running_program_shows_that_and_a_quick_exit_says_so_softly(gtk):
    c, page = home_page(ALL)
    c.apps.state.update({"aio-launcher": "running", "arena": "quick"})
    page.refresh()
    assert [b.get_label() for b in buttons(page.content, gtk)] == ["Open", "Open"]  # not the running one
    text = labels(page.content, gtk)
    assert "Running" in text
    assert any("Closed after a few seconds" in line for line in text)


def test_with_nothing_installed_it_points_at_the_button_that_installs(gtk):
    # Not reachable through a real status (the setup is not complete then), but the page must not be a blank.
    _c, page = home_page(status())
    assert labels(page.content, gtk, "title-2") == []
    assert any("download button" in line for line in labels(page.content, gtk))


def test_the_version_is_at_the_bottom(gtk):
    _c, page = home_page(ALL)
    assert "Version 1.0.0" in labels(page.box, gtk, "caption")
