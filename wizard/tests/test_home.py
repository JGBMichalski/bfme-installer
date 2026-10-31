import contextlib
import io
import os
import time
from unittest import mock

import pytest

from bfme_wizard.__main__ import main, parse_args
from bfme_wizard.apps import AppLauncher
from bfme_wizard.controller import Controller
from bfme_wizard.diagnostics import any_log, build_report, newest_log, system_lines, tail
from bfme_wizard.engine.events import Cancelled, Check, Done, Fix, Status
from bfme_wizard.model import SetupModel, games_line
from bfme_wizard.runner import JobRunner
from tests.fake_jobs import FakeJobs, idle_controller
from tests.helpers import buttons, descendants, labels, wait_for


def feed(model, *events):
    for event in events:
        model.feed_event(event)



# The model: games, graphics and checks

def test_installed_games_in_a_fixed_order():
    m = SetupModel()
    feed(m, Status("rotwk", "installed"), Status("bfme1", "missing"), Status("bfme2", "installed"))
    assert m.games == ["BFME 2", "Rise of the Witch-king"]


def test_no_games_before_a_status_check():
    assert SetupModel().games == []


def test_just_finished_only_after_this_session_ran_the_setup():
    m = SetupModel()
    feed(m, Status("complete", "yes"))
    m.finish_status(0)
    assert (m.state, m.just_finished) == ("done", False)
    m.begin_plan(["aio-launcher"])
    m.begin_job("environment")
    feed(m, Done())
    assert m.finish_install(0) == "aio-launcher"
    assert not m.just_finished   # the AIO Launcher is still to come
    m.begin_job("aio-launcher")
    feed(m, Done())
    m.finish_install(0)
    assert m.just_finished
    m.begin_plan(["aio-launcher"])
    assert not m.just_finished


def test_the_backend_comes_from_the_status_and_defaults_to_vulkan():
    m = SetupModel()
    assert (m.graphics, m.graphics_label) == ("vulkan", "Vulkan (DXVK)")
    feed(m, Status("graphics", "opengl"))
    assert (m.graphics, m.graphics_label) == ("opengl", "OpenGL (WineD3D)")


def test_rows_hide_the_firewall_and_list_problems_first():
    m = SetupModel()
    feed(m, Check("cpu", "ok", "x86_64 processor"), Check("firewall", "warn", "firewall is active"),
          Check("flatpak-32bit", "fail", "the 32-bit parts are missing"),
          Fix("flatpak-32bit", "flatpak install --user flathub X"), Check("disk", "warn", "low disk"),
          Check("curl", "ok", "curl found"))
    assert [r[0] for r in m.check_rows] == ["flatpak-32bit", "disk", "cpu", "curl"]
    assert m.check_rows[0][3] == "flatpak install --user flathub X"
    assert [p.message for p in m.problems] == ["the 32-bit parts are missing"]


def test_a_quiet_check_keeps_the_state_and_forgets_old_results():
    m = SetupModel()
    m.state = "done"
    feed(m, Check("cpu", "fail", "old"))
    m.begin_quiet_check()
    assert (m.state, m.checks, m.fixes) == ("done", {}, {})


# The line about games on the home screen

LAUNCHER = {"aio-launcher": "installed", "arena": "installed"}


def games(installed, finished=False):
    m = SetupModel()
    m.installed = installed
    m.just_finished = finished
    return games_line(m)


def test_wording():
    assert games({**LAUNCHER, "bfme2": "installed"}) == ""
    assert games({**LAUNCHER, "bfme1": "installed", "bfme2": "installed", "rotwk": "installed"}) == ""
    assert games(LAUNCHER) == "No games installed yet. Open the AIO Launcher to install them."
    assert games(LAUNCHER, finished=True) == "Setup is complete. Open the AIO Launcher to install your games."
    assert games({**LAUNCHER, "bfme2": "installed"}, finished=True) == ""


def test_nothing_about_games_for_someone_who_did_not_install_the_aio_launcher():
    # Age of the Ring has its own copies of the games, and there is no AIO Launcher to open to install the others.
    assert games({"aotr": "installed"}) == ""
    assert games({"aotr": "installed"}, finished=True) == ""


TOOLS_IDLE = {"workshop": "idle", "mission-control": "idle"}


def opener(seconds=0.0, code=0, opened=None):
    """A stand-in for jobs.open_program: the program runs for `seconds`, then the job ends with `code`."""
    def open_program(program, emit, cancel):
        if opened is not None:
            opened.append(program)

        time.sleep(seconds)
        return code

    return open_program


def test_a_short_run_is_reported_softly_and_a_long_one_is_not():
    changes = []
    apps = AppLauncher(opener(0.3), lambda: changes.append(dict(apps.state)), quick_seconds=5)
    apps.start("aio-launcher")
    assert apps.state["aio-launcher"] == "running"
    wait_for(5000, lambda: apps.state["aio-launcher"] != "running")
    assert apps.state["aio-launcher"] == "quick"
    apps = AppLauncher(opener(0.6), lambda: None, quick_seconds=0.2)
    apps.start("arena")
    wait_for(5000, lambda: apps.state["arena"] != "running")
    assert apps.state["arena"] == "idle"


def test_both_apps_can_run_at_once_and_each_only_once():
    opened = []
    apps = AppLauncher(opener(1, opened=opened), lambda: None, quick_seconds=0)
    apps.start("aio-launcher"); apps.start("aio-launcher"); apps.start("arena")
    assert apps.state == {"aio-launcher": "running", "arena": "running", "aotr": "idle", **TOOLS_IDLE}
    assert apps.any_running
    wait_for(5000, lambda: not apps.any_running)
    assert apps.state == {"aio-launcher": "idle", "arena": "idle", "aotr": "idle", **TOOLS_IDLE}
    assert sorted(opened) == ["aio-launcher", "arena"]


def test_a_program_that_cannot_start_counts_as_closed_quickly():
    # The job fails before the program runs: it is not installed, say.
    apps = AppLauncher(opener(code=1), lambda: None, quick_seconds=0)
    apps.start("aio-launcher")
    wait_for(5000, lambda: apps.state["aio-launcher"] != "running")
    assert apps.state["aio-launcher"] == "quick"


def test_unknown_names_are_ignored():
    opened = []
    apps = AppLauncher(opener(opened=opened), lambda: None)
    apps.start("bad-exit")
    assert apps.state == {"aio-launcher": "idle", "arena": "idle", "aotr": "idle", **TOOLS_IDLE}
    assert opened == []


def test_a_tool_is_opened_by_its_name():
    opened = []
    apps = AppLauncher(opener(opened=opened), lambda: None)
    apps.start("mission-control")
    wait_for(5000, lambda: apps.state["mission-control"] != "running")
    assert opened == ["mission-control"]


# Diagnostics

def test_report_has_the_version_checks_fixes_and_log_tails(tmp_path):
    logs = tmp_path
    (logs / "aio-launcher-20260101-000000.log").write_text("old\n")
    time.sleep(0.02)
    (logs / "aio-launcher-20260102-000000.log").write_text("\n".join(f"line {i}" for i in range(100)))
    (logs / "arena-20260101-000000.log").write_text("arena says hi\n")
    m = SetupModel()
    m.installed = {"runner": "proton", "prefix": "ready", "aio-launcher": "installed", "arena": "installed", "bfme2": "installed"}
    feed(m, Check("cpu", "ok", "x86_64 processor"), Check("f", "fail", "parts missing"), Fix("f", "flatpak install X"))
    report = build_report("0.2.9", m, logs)
    for expected in ("Version: 0.2.9", "Runner: proton", "Graphics: unknown", "BFME 2 installed", "BFME unknown",
                     "[FAILED] parts missing", "fix: flatpak install X", "[ok] x86_64 processor",
                     "--- latest AIO Launcher log (aio-launcher-20260102-000000.log", "line 99", "arena says hi", "--- no prefix creation log ---"):
        assert expected in report
    assert "line 59" not in report   # only the last 40 lines
    assert "old\n" not in report     # only the newest log


def test_the_report_names_the_graphics_backend(tmp_path):
    m = SetupModel()
    m.installed = {"graphics": "opengl"}
    report = build_report("dev", m, tmp_path)
    assert "Graphics: OpenGL (WineD3D)" in report


def test_a_report_before_any_check_or_log_still_works(tmp_path):
    report = build_report("dev", SetupModel(), tmp_path)
    assert "(not run yet)" in report
    assert "--- no AIO Launcher log ---" in report


def test_the_report_says_what_computer_it_came_from(tmp_path):
    report = build_report("dev", SetupModel(), tmp_path, system=["Desktop: KDE, wayland session", "Graphics card: NVIDIA X"])
    assert "Desktop: KDE, wayland session\nGraphics card: NVIDIA X\n" in report


def test_system_lines_name_the_session_and_the_desktop():
    lines = system_lines({"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "KDE"})
    assert "Desktop: KDE, wayland session" in lines
    assert any(line.startswith("Graphics card: ") for line in lines)
    assert any(line.startswith("NVIDIA driver: ") for line in lines)
    assert any(line.startswith("Vulkan: ") for line in lines)


def test_system_lines_guess_the_session_without_a_session_type():
    assert "Desktop: unknown, x11 session" in system_lines({"DISPLAY": ":0"})
    assert "Desktop: unknown, wayland session" in system_lines({"WAYLAND_DISPLAY": "wayland-0"})
    assert "Desktop: unknown, unknown session" in system_lines({})


def test_log_helpers(tmp_path):
    d = tmp_path
    assert newest_log(d, "x") is None
    assert any_log(d) is None
    assert any_log(d / "missing") is None
    (d / "prefix-create.log").write_text("a\nb\nc")
    assert newest_log(d, "prefix-create").name == "prefix-create.log"
    assert any_log(d).name == "prefix-create.log"
    assert tail(d / "prefix-create.log", 2) == "b\nc"
    assert "could not read" in tail(d / "nope.log")


# Menu entries

# "launcher": shortcuts made before the AIO Launcher was called "aio-launcher".
@pytest.mark.parametrize("args, app", [(["--open", "aio-launcher"], "aio-launcher"), (["--open", "launcher"], "aio-launcher"),
                                       (["x", "--open", "arena"], "arena"), ([], None), (["--open"], None),
                                       (["--open", "bfme2"], None), (["aio-launcher"], None)])
def test_parse_args(args, app):
    assert parse_args(args) == app


def test_a_shortcut_whose_program_is_there_opens_it_without_a_window():
    with mock.patch("bfme_wizard.__main__.jobs.ready_to_open", return_value=True) as ready, \
            mock.patch("bfme_wizard.__main__.jobs.open_program", return_value=0) as open_program, \
            mock.patch("sys.argv", ["bfme-installer", "--open", "launcher"]):
        assert main() == 0

    ready.assert_called_once_with("aio-launcher")
    assert open_program.call_args.args[0] == "aio-launcher"


def test_a_shortcut_whose_program_is_gone_opens_the_wizard_offering_it(monkeypatch):
    from bfme_wizard import ui

    with mock.patch("bfme_wizard.__main__.jobs.ready_to_open", return_value=False), \
            mock.patch("bfme_wizard.__main__.jobs.open_program") as open_program, \
            mock.patch("bfme_wizard.__main__.has_display", return_value=True), \
            mock.patch.object(ui, "WizardApp") as app, \
            mock.patch("sys.argv", ["bfme-installer", "--open", "aotr"]):
        app.return_value.run.return_value = 0
        assert main() == 0

    open_program.assert_not_called()
    assert app.call_args.kwargs["offer"] == "aotr"


def test_without_a_display_it_says_so_and_stops():
    err = io.StringIO()

    with mock.patch("bfme_wizard.__main__.has_display", return_value=False), \
            mock.patch("sys.argv", ["bfme-installer"]), contextlib.redirect_stderr(err):
        assert main() == 1

    assert "No display found, so the setup wizard cannot open." in err.getvalue()


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
    assert c.model.error is None          # a failing check is not a setup error
    assert "blocked" not in states
    fake.unflag("broken")
    assert c.run_checks()            # "Check again"
    wait_for(8000, lambda: not c.runner.busy)
    assert c.model.problems == []
    assert c.model.state == "done"


def test_check_again_does_nothing_while_a_job_runs(c):
    c.start()
    assert not c.run_checks()
    settle(c, "done")


def test_reset_deletes_then_shows_the_setup_again(c):
    c.start(); settle(c, "done")
    results = []
    assert c.reset(results.append)
    assert c.model.state == "checking"
    wait_for(8000, lambda: results and c.model.state == "idle" and not c.runner.busy)
    assert results == [True]
    assert c.model.state == "idle"


def test_nothing_from_before_a_reset_is_remembered(c):
    c.start(); settle(c, "done")
    assert c.model.games == ["BFME 2"]
    c.reset(lambda ok: None)
    wait_for(8000, lambda: c.model.state == "idle" and not c.runner.busy)
    assert c.model.games == []


def test_a_failed_reset_is_reported_and_the_state_is_looked_at_again(c, fake):
    fake.flag("reset-fails")
    c.start(); settle(c, "done")
    results = []
    c.reset(results.append)
    wait_for(8000, lambda: results and not c.runner.busy)
    assert results == [False]
    assert c.model.state == "done"    # nothing was deleted: the home screen comes back


def test_reset_is_refused_while_things_run(c):
    c.start(); settle(c, "done")
    c.model.state = "running"
    assert "setup is running" in c.blocked_reason()
    assert not c.reset(lambda ok: None)
    c.model.state = "done"
    c.apps.state["aio-launcher"] = "running"
    assert c.blocked_reason() == "A program is still running."
    c.apps.state["aio-launcher"] = "idle"
    assert c.blocked_reason() is None


# Troubleshoot page

def test_the_advice_about_graphics_drivers_names_the_chosen_backend(gtk):
    from bfme_wizard.home import cant_check
    vulkan = {title: text for title, text, _command in cant_check("vulkan")}
    opengl = {title: text for title, text, _command in cant_check("opengl")}
    assert "working Vulkan drivers" in vulkan["Graphics drivers"]
    assert "working OpenGL drivers" in opengl["Graphics drivers"]
    assert "switch to OpenGL" in vulkan["Graphics drivers"]
    assert "switch back to Vulkan" in opengl["Graphics drivers"]


def troubleshoot_button_labels(Gtk, graphics):
    from bfme_wizard.home import TroubleshootPage
    c = idle_controller()
    c.model.state = "idle"
    c.model.installed = {"graphics": graphics}
    page = TroubleshootPage(
        c, copy_text=lambda *_a: None, copy_diagnostics=lambda: None, open_logs=lambda: None,
        confirm_reset=lambda: None, change_graphics=lambda _backend: None,
    )
    return [b.get_label() for b in buttons(page.view, Gtk)]


def test_the_row_offers_the_other_backend(gtk):
    assert "Use OpenGL" in troubleshoot_button_labels(gtk, "vulkan")
    assert "Use Vulkan" in troubleshoot_button_labels(gtk, "opengl")


# The home screen shows the programs that are installed, each with a button to open it. Installing and removing
# programs is the Programs page's job, and the buttons for the other pages float in the corner of the window's page.

ALL = {"aio-launcher": "installed", "arena": "installed", "aotr": "installed"}


def home_page(installed):
    from bfme_wizard.home import HomePage
    c = idle_controller()
    c.model.installed = installed
    page = HomePage(c, lambda: "1.0.0")
    page.refresh()
    return c, page


def titles(Gtk, installed):
    _c, page = home_page(installed)
    return labels(page.content, Gtk, "title-2")


def test_only_the_installed_programs_have_a_card(gtk):
    assert titles(gtk, ALL) == ["AIO Launcher", "Arena", "Age of the Ring"]
    assert titles(gtk, {"aio-launcher": "installed", "arena": "installed"}) == ["AIO Launcher", "Arena"]
    assert titles(gtk, {"aotr": "installed"}) == ["Age of the Ring"]
    assert titles(gtk, {"arena": "installed"}) == ["Arena"]
    assert titles(gtk, {"aio-launcher": "installed", "aotr": "installed"}) == ["AIO Launcher", "Age of the Ring"]


def test_a_program_that_is_not_there_leaves_no_trace_of_itself(gtk):
    _c, page = home_page({"aio-launcher": "installed"})
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
    # Install belongs to the Programs page; Game folders and Troubleshoot are buttons in the corner of the window's page.
    _c, page = home_page(ALL)
    assert {b.get_label() for b in buttons(page.box, gtk)} == {"Open"}


def test_a_running_program_shows_that_and_a_quick_exit_says_so_softly(gtk):
    c, page = home_page(ALL)
    c.apps.state.update({"aio-launcher": "running", "arena": "quick"})
    page.refresh()
    assert [b.get_label() for b in buttons(page.content, gtk)] == ["Open", "Open"]   # not the running one
    text = labels(page.content, gtk)
    assert "Running" in text
    assert any("Closed after a few seconds" in line for line in text)


def test_with_nothing_installed_it_points_at_the_button_that_installs(gtk):
    # Not reachable through a real status (the setup is not complete then), but the page must not be a blank.
    _c, page = home_page({})
    assert labels(page.content, gtk, "title-2") == []
    assert any("download button" in line for line in labels(page.content, gtk))


def test_the_version_is_at_the_bottom(gtk):
    _c, page = home_page(ALL)
    assert "Version 1.0.0" in labels(page.box, gtk, "caption")


# Game folders page

def folders_page(home, opened):
    from bfme_wizard.home import GameFoldersPage
    with mock.patch.dict(os.environ, {"BFME_HOME": str(home)}):
        return GameFoldersPage(opened.append)


def groups(page):
    from gi.repository import Adw
    return [w for w in descendants(page.view) if isinstance(w, Adw.PreferencesGroup)]


def test_only_the_installed_games_have_a_group_in_their_order_with_age_of_the_ring_last(gtk, tmp_path):
    drive = tmp_path / "prefix/drive_c"
    for folder in ("RotWK", "BFME1", "AgeoftheRing"):
        (drive / folder).mkdir(parents=True)
    page = folders_page(tmp_path, [])
    assert [g.get_title() for g in groups(page)] == ["BFME", "Rise of the Witch-king", "Age of the Ring"]


def test_a_game_that_is_not_installed_leaves_no_trace_of_itself(gtk, tmp_path):
    (tmp_path / "prefix/drive_c/BFME2").mkdir(parents=True)
    page = folders_page(tmp_path, [])
    text = " ".join(labels(page.view, gtk))
    for word in ("Not installed", "Rise of the Witch-king", "Age of the Ring"):
        assert word not in text
    assert [g.get_title() for g in groups(page)] == ["BFME 2"]


def test_with_no_game_installed_the_page_says_so_instead_of_being_empty(gtk, tmp_path):
    page = folders_page(tmp_path, [])
    assert groups(page) == []
    from gi.repository import Adw
    status = [w for w in descendants(page.view) if isinstance(w, Adw.StatusPage)]
    assert len(status) == 1
    assert status[0].get_title() == "No games installed"


def test_its_rows_open_its_program_folder_and_its_lowercase_maps_folder(gtk, tmp_path):
    drive = tmp_path / "prefix/drive_c"
    (drive / "AgeoftheRing").mkdir(parents=True)
    user = drive / "users/steamuser/AppData/Roaming/Age of the Ring"
    (user / "maps").mkdir(parents=True)
    opened = []
    page = folders_page(tmp_path, opened)
    from gi.repository import Adw
    rows = [w for w in descendants(groups(page)[0]) if isinstance(w, Adw.ActionRow)]
    assert [r.get_title() for r in rows] == ["Game folder", "Maps and user data"]
    for row in rows:
        row.emit("activated")
    assert opened == [drive / "AgeoftheRing", user / "maps"]
    assert [g.get_title() for g in groups(page)] == ["Age of the Ring"]   # the games are separate


# Start page

@pytest.fixture
def start(gtk):
    from bfme_wizard.start import StartPage
    c = idle_controller()
    return c, StartPage(c)


def test_nothing_is_ticked_and_nothing_can_start_until_the_player_chooses(start):
    c, page = start
    page.enter()
    assert (page.selected, page.button.get_label(), page.button.get_sensitive()) == ((), "Install", False)
    page._checks["aotr"].set_active(True)
    assert (page.selected, page.button.get_sensitive()) == (("aotr",), True)
    page._checks["aio-launcher"].set_active(True)
    assert page.selected == ("aio-launcher", "aotr")   # install order, not tick order


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
    c.model.choose(["aotr"])
    page.enter()
    assert (page.selected, page.button.get_sensitive()) == (("aotr",), True)


def test_the_players_ticks_survive_a_refresh(start):
    c, page = start
    page.enter()
    page._checks["aio-launcher"].set_active(True)
    page.refresh()   # the window renders on every change; only enter() takes the choice from the model
    assert page.selected == ("aio-launcher",)


def test_after_a_stop_the_same_choice_says_resume_and_another_says_install(start):
    c, page = start
    c.model.installed["prefix"] = "missing"
    c.model.begin_plan(["aio-launcher", "aotr"])
    c.model.begin_job("environment")
    feed(c.model, Cancelled())
    c.model.finish_install(130)
    page.enter()
    assert (page.selected, page.button.get_label(), page.view.get_title()) == \
        (("aio-launcher", "aotr"), "Resume", "Setup paused")
    page._checks["aotr"].set_active(False)
    assert page.button.get_label() == "Install"


def test_the_page_says_when_the_game_environment_is_ready(start):
    c, page = start
    page.enter()
    assert page.view.get_title() == "Set up BFME on Linux"
    c.model.installed["prefix"] = "ready"
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
