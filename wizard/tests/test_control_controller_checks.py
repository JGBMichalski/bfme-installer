"""The controller with the stand-in jobs: the quiet system checks on the home screen, and the reset."""

import pytest

from bfme_wizard.control.controller import Controller
from bfme_wizard.control.runner import JobRunner
from tests.fake_jobs import FakeJobs
from tests.helpers import wait_for


def feed(model, *events):
    for event in events:
        model.feed_event(event)


# The controller running the stand-in jobs


@pytest.fixture
def fake(tmp_path):
    """A complete setup with BFME 2 installed, whose system check passes."""
    jobs = FakeJobs(tmp_path)
    jobs.flag("prefix", "aio-launcher", "bfme2", "checks-pass")
    return jobs


@pytest.fixture
def c(fake):
    return Controller(JobRunner(), lambda: None, jobs=fake)


def settle(c, state, ms=8000):
    wait_for(ms, lambda: c.model.state == state and not c.runner.busy)
    assert c.model.state == state


def test_opening_on_a_complete_setup_runs_the_checks_quietly(c):
    c.start()
    settle(c, "done")
    assert c.model.games == ["BFME 2"]
    assert c.model.problems == []
    assert [r[0] for r in c.model.check_rows] == ["cpu", "disk"]


def test_a_failed_check_is_found_without_leaving_the_home_screen(c, fake):
    fake.flag("broken")
    states = []
    c._on_change = lambda: states.append(c.model.state)
    c.start()
    settle(c, "done")
    assert [p.message for p in c.model.problems] == ["the 32-bit Flatpak extensions are not installed"]
    assert c.model.error is None  # a failing check is not a setup error
    assert "blocked" not in states
    fake.unflag("broken")
    assert c.run_checks()  # "Check again"
    wait_for(8000, lambda: not c.runner.busy)
    assert c.model.problems == []
    assert c.model.state == "done"


def test_check_again_does_nothing_while_a_job_runs(c):
    c.start()
    assert not c.run_checks()
    settle(c, "done")


def test_reset_deletes_then_shows_the_setup_again(c):
    c.start()
    settle(c, "done")
    results = []
    assert c.reset(results.append)
    assert c.model.state == "checking"
    wait_for(8000, lambda: results and c.model.state == "idle" and not c.runner.busy)
    assert results == [True]
    assert c.model.state == "idle"


def test_nothing_from_before_a_reset_is_remembered(c):
    c.start()
    settle(c, "done")
    assert c.model.games == ["BFME 2"]
    c.reset(lambda ok: None)
    wait_for(8000, lambda: c.model.state == "idle" and not c.runner.busy)
    assert c.model.games == []


def test_a_failed_reset_is_reported_and_the_state_is_looked_at_again(c, fake):
    fake.flag("reset-fails")
    c.start()
    settle(c, "done")
    results = []
    c.reset(results.append)
    wait_for(8000, lambda: results and not c.runner.busy)
    assert results == [False]
    assert c.model.state == "done"  # nothing was deleted: the home screen comes back


def test_reset_is_refused_while_things_run(c):
    c.start()
    settle(c, "done")
    c.model.state = "running"
    assert "setup is running" in c.blocked_reason()
    assert not c.reset(lambda ok: None)
    c.model.state = "done"
    c.apps.state["aio-launcher"] = "running"
    assert c.blocked_reason() == "A program is still running."
    c.apps.state["aio-launcher"] = "idle"
    assert c.blocked_reason() is None
