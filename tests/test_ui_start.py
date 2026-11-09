"""The start page, where the player chooses what to install."""

import pytest

from bfme_wizard.engine.events import Cancelled
from tests.fake_jobs import idle_controller
from tests.helpers import status, wait_for


def feed(model, *events):
    for event in events:
        model.feed_event(event)


# Start page


@pytest.fixture
def start(gtk):
    from bfme_wizard.ui.pages.start import StartPage

    c = idle_controller()
    return c, StartPage(c)


def test_nothing_is_ticked_and_nothing_can_start_until_the_player_chooses(start):
    c, page = start
    page.enter()
    assert (page.selected, page.button.get_label(), page.button.get_sensitive()) == ((), "Install", False)
    page._checks["aotr"].set_active(True)
    assert (page.selected, page.button.get_sensitive()) == (("aotr",), True)
    page._checks["aio-launcher"].set_active(True)
    assert page.selected == ("aio-launcher", "aotr")  # install order, not tick order


def test_install_waits_while_the_script_is_busy_and_comes_back_after(start):
    # Pressed meanwhile it would do nothing, so the button says so by being inactive.
    c, page = start
    page.enter()
    page._checks["aio-launcher"].set_active(True)
    assert page.button.get_sensitive()
    assert c.run_checks()
    page.refresh()
    assert not page.button.get_sensitive()
    wait_for(8000, lambda: not c.runner.busy)
    page.refresh()
    assert page.button.get_sensitive()


def test_a_shortcut_ticks_its_program(start):
    c, page = start
    c.model.plan.choose(["aotr"])
    page.enter()
    assert (page.selected, page.button.get_sensitive()) == (("aotr",), True)


def test_the_players_ticks_survive_a_refresh(start):
    c, page = start
    page.enter()
    page._checks["aio-launcher"].set_active(True)
    page.refresh()  # the window renders on every change; only enter() takes the choice from the model
    assert page.selected == ("aio-launcher",)


def test_after_a_stop_the_same_choice_says_resume_and_another_says_install(start):
    c, page = start
    c.model.status = status()
    c.model.begin_plan(["aio-launcher", "aotr"])
    c.model.begin_job("environment")
    feed(c.model, Cancelled())
    c.model.finish_install(130)
    page.enter()
    assert (page.selected, page.button.get_label(), page.view.get_title()) == (
        ("aio-launcher", "aotr"),
        "Resume",
        "Setup paused",
    )
    page._checks["aotr"].set_active(False)
    assert page.button.get_label() == "Install"


def test_the_page_says_when_the_game_environment_is_ready(start):
    c, page = start
    page.enter()
    assert page.view.get_title() == "Set up BFME on Linux"
    c.model.status = status(prefix_ready=True)
    page.refresh()
    assert page.view.get_title() == "Choose what to install"


def test_the_button_installs_what_is_ticked(start):
    c, page = start
    asked = []
    c.install = asked.append
    page.enter()
    page._checks["aio-launcher"].set_active(True)
    page._checks["aotr"].set_active(True)
    page.button.emit("clicked")
    assert asked == [("aio-launcher", "aotr")]
