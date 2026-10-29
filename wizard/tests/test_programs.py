"""The Programs page: one row per program, with Install when it is missing and Remove when it is installed."""
from bfme_wizard.controller import Controller
from bfme_wizard.runner import ScriptRunner
from tests.helpers import buttons, descendants, make_script, wait_for

IDLE = "#!/usr/bin/env bash\nexit 0\n"
ALL = {"launcher": "installed", "arena": "installed", "aotr": "installed"}


def make_page(installed, model_state="done", removing=None, apps=None):
    """The page, its controller, every row (the programs, then the tools) and what its buttons asked for."""
    from gi.repository import Adw
    from bfme_wizard.programs import ProgramsPage
    c = Controller(ScriptRunner(make_script(IDLE)), lambda: None)
    c.model.installed = dict(installed)
    c.model.state = model_state
    c.model.removing = removing
    c.apps.state.update(apps or {})
    asked = []
    page = ProgramsPage(c, install=lambda p: asked.append(("install", p)), remove=lambda p: asked.append(("remove", p)),
                        open_app=lambda p: asked.append(("open", p)))
    rows = [w for w in descendants(page.view) if isinstance(w, Adw.ActionRow)]
    return c, page, rows, asked


def program_rows(installed, **state):
    """The rows of the programs, before the tools."""
    return make_page(installed, **state)[2][:3]


def rows_of(page):
    """The rows as they are now (a refresh builds new ones)."""
    from gi.repository import Adw
    return [w for w in descendants(page.view) if isinstance(w, Adw.ActionRow)]


def test_a_row_for_every_program_in_the_order_of_the_home_screen(gtk):
    rows = program_rows(ALL)
    assert [r.get_title() for r in rows] == ["AIO Launcher", "Arena", "Age of the Ring"]


def test_an_installed_program_offers_remove_and_a_missing_one_offers_install(gtk):
    rows = program_rows({"launcher": "installed", "arena": "installed"})
    assert [[b.get_label() for b in buttons(r, gtk)] for r in rows] == [["Remove"], ["Remove"], ["Install"]]


def test_install_looks_like_the_main_action_and_remove_like_the_dangerous_one(gtk):
    rows = program_rows({"launcher": "installed"})
    remove, = buttons(rows[0], gtk)
    install, = buttons(rows[2], gtk)
    assert remove.has_css_class("destructive-action") and not remove.has_css_class("suggested-action")
    assert install.has_css_class("suggested-action") and not install.has_css_class("destructive-action")


def test_the_buttons_ask_for_their_own_program(gtk):
    _c, _page, rows, asked = make_page({"launcher": "installed", "aotr": "installed"})
    for row in rows[:3]:
        for button in buttons(row, gtk):
            button.emit("clicked")
    assert asked == [("remove", "launcher"), ("install", "arena"), ("remove", "aotr")]


def test_each_row_says_whether_the_program_is_there(gtk):
    rows = program_rows({"launcher": "installed", "arena": "installed"})
    assert rows[0].get_subtitle() == "Installed"
    assert rows[1].get_subtitle() == "Installed"
    assert rows[2].get_subtitle().startswith("Not installed.")
    assert "14 GB" in rows[2].get_subtitle()       # Age of the Ring is a big download the player makes first


def test_a_missing_program_says_what_installing_it_installs_with_it(gtk):
    # The Arena only plays what the AIO Launcher installs, so the setup installs them together.
    rows = program_rows({})
    assert "Installs the Arena too" in rows[0].get_subtitle()
    assert "Installs the AIO Launcher too" in rows[1].get_subtitle()
    rows = program_rows({"launcher": "installed"})
    assert "too" not in rows[1].get_subtitle()                      # the AIO Launcher is there: nothing else comes
    rows = program_rows({"arena": "installed"})
    assert "too" not in rows[0].get_subtitle()


def test_a_program_that_is_open_cannot_be_removed_and_the_others_say_what_to_close(gtk):
    # Removing one ends the whole Wine session, which would close the open one too: nothing can go until it is closed.
    rows = program_rows(ALL, apps={"arena": "running"})
    assert rows[1].get_subtitle() == "Running. Close it to remove it."
    assert rows[0].get_subtitle() == "Installed. Close the Arena to remove it."
    assert rows[2].get_subtitle() == "Installed. Close the Arena to remove it."
    assert [[b.get_sensitive() for b in buttons(r, gtk)] for r in rows] == [[False], [False], [False]]


def test_with_two_programs_open_it_names_both_in_the_order_of_the_page(gtk):
    rows = program_rows(ALL, apps={"aotr": "running", "launcher": "running"})
    assert rows[1].get_subtitle() == "Installed. Close the AIO Launcher and Age of the Ring to remove it."


def test_a_missing_program_can_still_be_installed_while_another_is_open(gtk):
    # Only removing is dangerous to what is open.
    rows = program_rows({"launcher": "installed", "arena": "installed"}, apps={"launcher": "running"})
    install, = buttons(rows[2], gtk)
    assert (install.get_label(), install.get_sensitive()) == ("Install", True)


def test_nothing_can_be_changed_while_the_script_is_busy(gtk):
    c, page, _rows, _asked = make_page({"launcher": "installed"})
    assert c.run_checks()
    page.refresh()
    found = [b for r in rows_of(page) for b in buttons(r, gtk)]
    assert sorted(b.get_label() for b in found) == ["Install"] * 4 + ["Remove"]
    assert [b.get_sensitive() for b in found] == [False] * 5
    wait_for(8000, lambda: not c.runner.busy)
    page.refresh()
    assert all(b.get_sensitive() for r in rows_of(page) for b in buttons(r, gtk))


def test_the_program_being_removed_shows_it_and_everything_else_waits(gtk):
    rows = program_rows(ALL, model_state="removing", removing="arena")
    assert rows[1].get_subtitle() == "Removing..."
    assert buttons(rows[1], gtk) == []                 # no button to press twice
    assert any(isinstance(w, gtk.Spinner) for w in descendants(rows[1]))
    others = [b for r in (rows[0], rows[2]) for b in buttons(r, gtk)]
    assert [b.get_sensitive() for b in others] == [False, False]


def test_the_page_says_that_games_are_safe(gtk):
    from gi.repository import Adw
    _c, page, _rows, _asked = make_page(ALL)
    preferences = next(w for w in descendants(page.view) if isinstance(w, Adw.PreferencesPage))
    assert "games you installed with the AIO Launcher" in preferences.get_description()


def test_it_is_rebuilt_only_when_what_it_shows_has_changed(gtk):
    # An open dialog or a pressed button must not be pulled away by the window rendering on every line of output.
    c, page, _rows, _asked = make_page(ALL)
    first = page.view.get_content()
    page.refresh()
    assert page.view.get_content() is first
    c.model.installed["aotr"] = "missing"
    page.refresh()
    assert page.view.get_content() is not first


# The tools

def test_the_tools_have_a_group_of_their_own_after_the_programs(gtk):
    from gi.repository import Adw
    _c, page, rows, _asked = make_page({})
    groups = [w for w in descendants(page.view) if isinstance(w, Adw.PreferencesGroup)]
    assert [g.get_title() for g in groups] == ["", "Tools"]
    assert [r.get_title() for r in rows[3:]] == ["Workshop Studio", "Mission Control"]


def test_a_tool_offers_install_or_open_and_remove(gtk):
    rows = make_page({"workshop": "installed"})[2][3:]
    assert [[b.get_label() for b in buttons(r, gtk)] for r in rows] == [["Open", "Remove"], ["Install"]]


def test_the_buttons_ask_for_their_own_tool(gtk):
    _c, _page, rows, asked = make_page({"workshop": "installed"})
    for row in rows[3:]:
        for button in buttons(row, gtk):
            button.emit("clicked")
    assert asked == [("open", "workshop"), ("remove", "workshop"), ("install", "mission-control")]


def test_a_running_tool_cannot_be_opened_again(gtk):
    rows = make_page({"workshop": "installed"}, apps={"workshop": "running"})[2][3:]
    assert not buttons(rows[0], gtk)[0].get_sensitive()


# The catalog: the programs are listed in three places that do not import each other. They must agree.

def test_the_catalog_covers_exactly_the_programs_the_rest_of_the_wizard_knows_in_the_order_it_shows_them():
    from bfme_wizard.apps import APPS
    from bfme_wizard.catalog import CATALOG
    from bfme_wizard.model import ALL_PROGRAMS
    assert [p.key for p in CATALOG] == list(ALL_PROGRAMS)
    assert sorted(APPS) == sorted(ALL_PROGRAMS)


def test_the_tools_are_known_to_the_rest_of_the_wizard():
    from bfme_wizard.apps import TOOL_APPS
    from bfme_wizard.catalog import TOOLS
    from bfme_wizard.model import JOB_STEPS, TOOLS as MODEL_TOOLS
    assert [p.key for p in TOOLS] == list(MODEL_TOOLS)
    assert sorted(TOOL_APPS) == sorted(MODEL_TOOLS)
    for key in MODEL_TOOLS:
        assert key in JOB_STEPS


def test_the_programs_that_install_together_are_programs():
    from bfme_wizard.catalog import INSTALLED_TOGETHER, program
    for key, partner in INSTALLED_TOGETHER.items():
        assert INSTALLED_TOGETHER[partner] == key    # it goes both ways
        assert (program(key).key, program(partner).key) == (key, partner)


def test_every_program_says_what_removing_it_leaves_alone():
    from bfme_wizard.catalog import CATALOG
    for info in CATALOG:
        assert "not touched" in info.removal
