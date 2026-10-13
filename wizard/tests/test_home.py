import os
import stat
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from gi.repository import GLib

from bfme_wizard.__main__ import parse_args
from bfme_wizard.apps import AppLauncher
from bfme_wizard.controller import Controller
from bfme_wizard.diagnostics import any_log, build_report, data_dir, newest_log, tail
from bfme_wizard.model import SetupModel, games_line
from bfme_wizard.runner import ScriptRunner, app_is_ready, setup_is_complete


def feed(model, *lines):
    for line in lines:
        model.feed_line(line)


class ModelGames(unittest.TestCase):
    def test_installed_games_in_a_fixed_order(self):
        m = SetupModel()
        feed(m, "@bfme STATUS rotwk installed", "@bfme STATUS bfme1 missing", "@bfme STATUS bfme2 installed")
        self.assertEqual(m.games, ["BFME 2", "Rise of the Witch-king"])

    def test_no_games_before_a_status_check(self):
        self.assertEqual(SetupModel().games, [])

    def test_just_finished_only_after_this_session_ran_the_setup(self):
        m = SetupModel()
        feed(m, "@bfme STATUS complete yes")
        m.finish_status(0)
        self.assertEqual((m.state, m.just_finished), ("done", False))
        m.begin_plan(["launcher"])
        m.begin_job("environment")
        feed(m, "@bfme DONE")
        self.assertEqual(m.finish_install(0), "launcher")
        self.assertFalse(m.just_finished)   # the launcher is still to come
        m.begin_job("launcher")
        feed(m, "@bfme DONE")
        m.finish_install(0)
        self.assertTrue(m.just_finished)
        m.begin_plan(["launcher"])
        self.assertFalse(m.just_finished)


class ModelChecks(unittest.TestCase):
    def test_rows_hide_the_firewall_and_list_problems_first(self):
        m = SetupModel()
        feed(m, "@bfme CHECK cpu ok x86_64 processor", "@bfme CHECK firewall warn firewall is active",
              "@bfme CHECK flatpak-32bit fail the 32-bit parts are missing",
              "@bfme FIX flatpak-32bit flatpak install --user flathub X", "@bfme CHECK disk warn low disk",
              "@bfme CHECK curl ok curl found")
        self.assertEqual([r[0] for r in m.check_rows], ["flatpak-32bit", "disk", "cpu", "curl"])
        self.assertEqual(m.check_rows[0][3], "flatpak install --user flathub X")
        self.assertEqual([p.message for p in m.problems], ["the 32-bit parts are missing"])

    def test_a_quiet_check_keeps_the_state_and_forgets_old_results(self):
        m = SetupModel()
        m.state = "done"
        feed(m, "@bfme CHECK cpu fail old")
        m.begin_quiet_check()
        self.assertEqual((m.state, m.checks, m.fixes), ("done", {}, {}))


class Line(unittest.TestCase):
    LAUNCHER = {"launcher": "installed", "arena": "installed"}

    def games(self, installed, finished=False):
        m = SetupModel()
        m.installed = installed
        m.just_finished = finished
        return games_line(m)

    def test_wording(self):
        self.assertEqual(self.games({**self.LAUNCHER, "bfme2": "installed"}), "")
        self.assertEqual(self.games({**self.LAUNCHER, "bfme1": "installed", "bfme2": "installed", "rotwk": "installed"}), "")
        self.assertEqual(self.games(self.LAUNCHER), "No games installed yet. Open the Launcher to install them.")
        self.assertEqual(self.games(self.LAUNCHER, finished=True), "Setup is complete. Open the Launcher to install your games.")
        self.assertEqual(self.games({**self.LAUNCHER, "bfme2": "installed"}, finished=True), "")

    def test_nothing_about_games_for_someone_who_did_not_install_the_launcher(self):
        # Age of the Ring has its own copies of the games, and there is no Launcher to open to install the others.
        self.assertEqual(self.games({"aotr": "installed"}), "")
        self.assertEqual(self.games({"aotr": "installed"}, finished=True), "")


APP = """#!/usr/bin/env bash
# fake setup script; the app commands run for APP_SECONDS
case "$1" in
  launcher|arena) sleep "${APP_SECONDS:-0}" ;;
  bad-exit) exit 3 ;;
esac
"""


def make_script(body):
    d = tempfile.mkdtemp()
    path = os.path.join(d, "fake.sh")
    with open(path, "w") as f:
        f.write(body)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    return path


def wait_for(loop_ms, condition):
    loop = GLib.MainLoop()
    def tick():
        if condition():
            loop.quit()
            return False
        return True
    GLib.timeout_add(50, tick)
    GLib.timeout_add(loop_ms, loop.quit)
    loop.run()


class Apps(unittest.TestCase):
    def test_a_short_run_is_reported_softly_and_a_long_one_is_not(self):
        os.environ["APP_SECONDS"] = "0.3"
        changes = []
        apps = AppLauncher(make_script(APP), lambda: changes.append(dict(apps.state)), quick_seconds=5)
        apps.start("launcher")
        self.assertEqual(apps.state["launcher"], "running")
        wait_for(5000, lambda: apps.state["launcher"] != "running")
        self.assertEqual(apps.state["launcher"], "quick")
        os.environ["APP_SECONDS"] = "0.6"
        apps = AppLauncher(make_script(APP), lambda: None, quick_seconds=0.2)
        apps.start("arena")
        wait_for(5000, lambda: apps.state["arena"] != "running")
        self.assertEqual(apps.state["arena"], "idle")

    def test_both_apps_can_run_at_once_and_each_only_once(self):
        os.environ["APP_SECONDS"] = "1"
        apps = AppLauncher(make_script(APP), lambda: None, quick_seconds=0)
        apps.start("launcher"); apps.start("launcher"); apps.start("arena")
        self.assertEqual(apps.state, {"launcher": "running", "arena": "running", "aotr": "idle"})
        self.assertTrue(apps.any_running)
        wait_for(5000, lambda: not apps.any_running)
        self.assertEqual(apps.state, {"launcher": "idle", "arena": "idle", "aotr": "idle"})

    def test_a_program_that_cannot_start_counts_as_closed_quickly(self):
        apps = AppLauncher("/nonexistent/script", lambda: None)
        apps.start("launcher")
        self.assertEqual(apps.state["launcher"], "quick")

    def test_unknown_names_are_ignored(self):
        apps = AppLauncher(make_script(APP), lambda: None)
        apps.start("bad-exit")
        self.assertEqual(apps.state, {"launcher": "idle", "arena": "idle", "aotr": "idle"})


class Diagnostics(unittest.TestCase):
    def test_data_dir_follows_the_script(self):
        self.assertEqual(data_dir({"BFME_HOME": "/x/y"}), Path("/x/y"))
        self.assertEqual(data_dir({"XDG_DATA_HOME": "/d"}), Path("/d/bfme-installer"))

    def test_report_has_the_version_checks_fixes_and_log_tails(self):
        logs = Path(tempfile.mkdtemp())
        (logs / "launcher-20260101-000000.log").write_text("old\n")
        time.sleep(0.02)
        (logs / "launcher-20260102-000000.log").write_text("\n".join(f"line {i}" for i in range(100)))
        (logs / "arena-20260101-000000.log").write_text("arena says hi\n")
        m = SetupModel()
        m.installed = {"runner": "proton", "prefix": "ready", "launcher": "installed", "arena": "installed", "bfme2": "installed"}
        feed(m, "@bfme CHECK cpu ok x86_64 processor", "@bfme CHECK f fail parts missing", "@bfme FIX f flatpak install X")
        report = build_report("0.2.9", m, logs)
        for expected in ("Version: 0.2.9", "Runner: proton", "BFME 2 installed", "BFME unknown",
                         "[FAILED] parts missing", "fix: flatpak install X", "[ok] x86_64 processor",
                         "launcher-20260102-000000.log", "line 99", "arena says hi", "--- no prefix creation log ---"):
            self.assertIn(expected, report)
        self.assertNotIn("line 59", report)   # only the last 40 lines
        self.assertNotIn("old\n", report)     # only the newest log

    def test_a_report_before_any_check_or_log_still_works(self):
        report = build_report("dev", SetupModel(), Path(tempfile.mkdtemp()))
        self.assertIn("(not run yet)", report)
        self.assertIn("--- no launcher log ---", report)

    def test_log_helpers(self):
        d = Path(tempfile.mkdtemp())
        self.assertIsNone(newest_log(d, "x"))
        self.assertIsNone(any_log(d))
        self.assertIsNone(any_log(d / "missing"))
        (d / "prefix-create.log").write_text("a\nb\nc")
        self.assertEqual(newest_log(d, "prefix-create").name, "prefix-create.log")
        self.assertEqual(any_log(d).name, "prefix-create.log")
        self.assertEqual(tail(d / "prefix-create.log", 2), "b\nc")
        self.assertIn("could not read", tail(d / "nope.log"))


STATUS = """#!/usr/bin/env bash
case "$2" in
  status) echo "@bfme STATUS complete ${COMPLETE:-yes}"; exit "${STATUS_EXIT:-0}" ;;
esac
"""

# What `status` says when only the programs named in $INSTALLED are installed.
INSTALLED = """#!/usr/bin/env bash
case "$2" in
  status)
    echo "@bfme STATUS prefix ${PREFIX_STATE:-ready}"
    for app in launcher arena aotr; do
      case " $INSTALLED " in *" $app "*) echo "@bfme STATUS $app installed" ;; *) echo "@bfme STATUS $app missing" ;; esac
    done
    exit "${STATUS_EXIT:-0}" ;;
esac
"""


class MenuEntries(unittest.TestCase):
    def test_parse_args(self):
        self.assertEqual(parse_args(["--open", "launcher"]), "launcher")
        self.assertEqual(parse_args(["x", "--open", "arena"]), "arena")
        for bad in ([], ["--open"], ["--open", "bfme2"], ["launcher"]):
            self.assertIsNone(parse_args(bad))

    def test_setup_is_complete(self):
        script = make_script(STATUS)
        os.environ["COMPLETE"], os.environ["STATUS_EXIT"] = "yes", "0"
        self.assertTrue(setup_is_complete(script))
        os.environ["COMPLETE"] = "no"
        self.assertFalse(setup_is_complete(script))
        os.environ["COMPLETE"], os.environ["STATUS_EXIT"] = "yes", "1"
        self.assertFalse(setup_is_complete(script))
        self.assertFalse(setup_is_complete("/nonexistent/script"))
        os.environ["STATUS_EXIT"] = "0"

    def ready(self, app, **env):
        with mock.patch.dict(os.environ, env):
            return app_is_ready(make_script(INSTALLED), app)

    def test_an_entry_starts_its_program_at_once_when_that_program_is_installed(self):
        # Someone who chose only Age of the Ring has no Launcher or Arena: only its own entry can start at once.
        self.assertTrue(self.ready("aotr", INSTALLED="aotr"))
        self.assertFalse(self.ready("launcher", INSTALLED="aotr"))
        self.assertFalse(self.ready("arena", INSTALLED="aotr"))
        for app in ("launcher", "arena"):
            self.assertTrue(self.ready(app, INSTALLED="launcher arena"), app)
        self.assertFalse(self.ready("aotr", INSTALLED="launcher arena"))

    def test_an_entry_opens_the_wizard_when_the_game_environment_is_gone_or_the_status_cannot_be_read(self):
        self.assertFalse(self.ready("launcher", INSTALLED="launcher arena", PREFIX_STATE="missing"))
        self.assertFalse(self.ready("launcher", INSTALLED="launcher arena", STATUS_EXIT="1"))
        self.assertFalse(app_is_ready("/nonexistent/script", "launcher"))


FLOW = r"""#!/usr/bin/env bash
shift  # --machine
case "$1" in
  status)
    if [ -f "$FAKE_DIR/reset" ]; then echo "@bfme STATUS complete no"; exit 0; fi
    echo "@bfme STATUS bfme2 installed"; echo "@bfme STATUS complete yes" ;;
  doctor)
    echo "@bfme CHECK cpu ok x86_64 processor"
    if [ -f "$FAKE_DIR/broken" ]; then echo "@bfme CHECK flatpak-32bit fail missing"; echo "@bfme FIX flatpak-32bit flatpak install X"
      echo "@bfme ERROR - Failed (exit 1)"; exit 1; fi ;;
  reset-prefix)
    [ "$2" = "--yes" ] || exit 9
    [ -f "$FAKE_DIR/reset-fails" ] && { echo "@bfme ERROR - nope"; exit 1; }
    touch "$FAKE_DIR/reset"; sleep 0.3 ;;
esac
"""


class Flow(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.environ["FAKE_DIR"] = self.dir
        self.c = Controller(ScriptRunner(make_script(FLOW)), lambda: None)

    def flag(self, name):
        open(os.path.join(self.dir, name), "w").close()

    def settle(self, state, ms=8000):
        wait_for(ms, lambda: self.c.model.state == state and not self.c.runner.busy)
        self.assertEqual(self.c.model.state, state)

    def test_opening_on_a_complete_setup_runs_the_checks_quietly(self):
        self.c.start()
        self.settle("done")
        self.assertEqual(self.c.model.games, ["BFME 2"])
        self.assertEqual(self.c.model.problems, [])
        self.assertEqual([r[0] for r in self.c.model.check_rows], ["cpu"])

    def test_a_failed_check_is_found_without_leaving_the_home_screen(self):
        self.flag("broken")
        states = []
        self.c._on_change = lambda: states.append(self.c.model.state)
        self.c.start()
        self.settle("done")
        self.assertEqual([p.message for p in self.c.model.problems], ["missing"])
        self.assertIsNone(self.c.model.error)          # the script's ERROR line is not a setup error
        self.assertNotIn("blocked", states)
        os.unlink(os.path.join(self.dir, "broken"))
        self.assertTrue(self.c.run_checks())            # "Check again"
        wait_for(8000, lambda: not self.c.runner.busy)
        self.assertEqual(self.c.model.problems, [])
        self.assertEqual(self.c.model.state, "done")

    def test_check_again_does_nothing_while_the_script_is_busy(self):
        self.c.start()
        self.assertFalse(self.c.run_checks())
        self.settle("done")

    def test_reset_deletes_then_shows_the_setup_again(self):
        self.c.start(); self.settle("done")
        results = []
        self.assertTrue(self.c.reset(results.append))
        self.assertEqual(self.c.model.state, "checking")
        wait_for(8000, lambda: results and self.c.model.state == "idle" and not self.c.runner.busy)
        self.assertEqual(results, [True])
        self.assertEqual(self.c.model.state, "idle")

    def test_nothing_from_before_a_reset_is_remembered(self):
        self.c.start(); self.settle("done")
        self.assertEqual(self.c.model.games, ["BFME 2"])
        self.c.reset(lambda ok: None)
        wait_for(8000, lambda: self.c.model.state == "idle" and not self.c.runner.busy)
        self.assertEqual(self.c.model.games, [])

    def test_a_failed_reset_is_reported_and_the_state_is_looked_at_again(self):
        self.flag("reset-fails")
        self.c.start(); self.settle("done")
        results = []
        self.c.reset(results.append)
        wait_for(8000, lambda: results and not self.c.runner.busy)
        self.assertEqual(results, [False])
        self.assertEqual(self.c.model.state, "done")    # nothing was deleted: the home screen comes back

    def test_reset_is_refused_while_things_run(self):
        self.c.start(); self.settle("done")
        self.c.model.state = "running"
        self.assertIn("setup is running", self.c.blocked_reason())
        self.assertFalse(self.c.reset(lambda ok: None))
        self.c.model.state = "done"
        self.c.apps.state["launcher"] = "running"
        self.assertIn("still running", self.c.blocked_reason())
        self.c.apps.state["launcher"] = "idle"
        self.assertIsNone(self.c.blocked_reason())


def gtk_or_skip(test):
    """Import the widgets, or skip: the CI job installs only the GLib bindings and has no display."""
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Gtk
    except (ValueError, ImportError):
        test.skipTest("GTK is not installed")
    if not Gtk.init_check():
        test.skipTest("no display")
    return Gtk


def buttons(widget, Gtk):
    """Every button under the widget, in order."""
    found = []
    def walk(w):
        while w:
            if isinstance(w, Gtk.Button):
                found.append(w)
            walk(w.get_first_child())
            w = w.get_next_sibling()
    walk(widget)
    return found


class HomeCards(unittest.TestCase):
    """Each card opens its program when it is installed and offers to install it when it is not."""

    def labels(self, installed):
        Gtk = gtk_or_skip(self)
        from bfme_wizard.home import HomePage
        c = Controller(ScriptRunner(make_script(FLOW)), lambda: None)
        c.model.installed = installed
        page = HomePage(c, lambda: "1.0.0", lambda: None)
        page.refresh()
        return [(b.get_label(), b.has_css_class("suggested-action"), b.get_sensitive())
                for b in buttons(page.content, Gtk) if b.get_label() in ("Open", "Install")]   # Launcher, Arena, Age of the Ring

    def test_everything_installed_opens_everything(self):
        every = {"launcher": "installed", "arena": "installed", "aotr": "installed"}
        self.assertEqual(self.labels(every), [("Open", True, True)] * 3)

    def test_a_player_who_chose_only_age_of_the_ring_can_install_the_rest_from_here(self):
        self.assertEqual(self.labels({"aotr": "installed"}),
                         [("Install", True, True), ("Install", True, True), ("Open", True, True)])

    def test_a_player_who_chose_only_the_launcher_can_install_age_of_the_ring_from_here(self):
        self.assertEqual(self.labels({"launcher": "installed", "arena": "installed"}),
                         [("Open", True, True), ("Open", True, True), ("Install", True, True)])

    def test_install_waits_while_the_system_checks_run(self):
        # The script is busy then and would ignore the click, so the button says so by being inactive.
        Gtk = gtk_or_skip(self)
        from bfme_wizard.home import HomePage
        c = Controller(ScriptRunner(make_script(FLOW)), lambda: None)
        c.model.installed = {"launcher": "installed", "arena": "installed"}
        page = HomePage(c, lambda: "1.0.0", lambda: None)
        c.run_checks()
        page.refresh()
        install = [b for b in buttons(page.content, Gtk) if b.get_label() == "Install"]
        self.assertEqual([b.get_sensitive() for b in install], [False])
        wait_for(8000, lambda: not c.runner.busy)

    def test_installing_a_missing_card_plans_only_that_program(self):
        Gtk = gtk_or_skip(self)
        from bfme_wizard.home import HomePage
        c = Controller(ScriptRunner(make_script(FLOW)), lambda: None)
        c.model.installed = {"aotr": "installed", "prefix": "ready"}
        asked = []
        c.install = asked.append
        page = HomePage(c, lambda: "1.0.0", lambda: None)
        page.refresh()
        for b in [b for b in buttons(page.content, Gtk) if b.get_label() == "Install"]:
            b.emit("clicked")
        self.assertEqual(asked, [["launcher"], ["launcher"]])   # the Arena card installs it with the Launcher


class StartPageWidget(unittest.TestCase):
    def page(self):
        gtk_or_skip(self)
        from bfme_wizard.start import StartPage
        c = Controller(ScriptRunner(make_script(FLOW)), lambda: None)
        return c, StartPage(c)

    def test_nothing_is_ticked_and_nothing_can_start_until_the_player_chooses(self):
        c, page = self.page()
        page.enter()
        self.assertEqual((page.selected, page.button.get_label(), page.button.get_sensitive()), ((), "Install", False))
        page._checks["aotr"].set_active(True)
        self.assertEqual((page.selected, page.button.get_sensitive()), (("aotr",), True))
        page._checks["launcher"].set_active(True)
        self.assertEqual(page.selected, ("launcher", "aotr"))   # install order, not tick order

    def test_install_waits_while_the_script_is_busy_and_comes_back_after(self):
        # Pressed meanwhile it would do nothing, so the button says so by being inactive.
        c, page = self.page()
        page.enter()
        page._checks["launcher"].set_active(True)
        self.assertTrue(page.button.get_sensitive())
        self.assertTrue(c.run_checks())
        page.refresh()
        self.assertFalse(page.button.get_sensitive())
        wait_for(8000, lambda: not c.runner.busy)
        page.refresh()
        self.assertTrue(page.button.get_sensitive())

    def test_a_shortcut_ticks_its_program(self):
        c, page = self.page()
        c.model.choose(["aotr"])
        page.enter()
        self.assertEqual((page.selected, page.button.get_sensitive()), (("aotr",), True))

    def test_the_players_ticks_survive_a_refresh(self):
        c, page = self.page()
        page.enter()
        page._checks["launcher"].set_active(True)
        page.refresh()   # the window renders on every change; only enter() takes the choice from the model
        self.assertEqual(page.selected, ("launcher",))

    def test_after_a_stop_the_same_choice_says_resume_and_another_says_install(self):
        c, page = self.page()
        c.model.installed["prefix"] = "missing"
        c.model.begin_plan(["launcher", "aotr"])
        c.model.begin_job("environment")
        feed(c.model, "@bfme CANCELLED")
        c.model.finish_install(130)
        page.enter()
        self.assertEqual((page.selected, page.button.get_label(), page.view.get_title()),
                         (("launcher", "aotr"), "Resume", "Setup paused"))
        page._checks["aotr"].set_active(False)
        self.assertEqual(page.button.get_label(), "Install")

    def test_the_page_says_when_the_game_environment_is_ready(self):
        c, page = self.page()
        page.enter()
        self.assertEqual(page.view.get_title(), "Set up BFME on Linux")
        c.model.installed["prefix"] = "ready"
        page.refresh()
        self.assertEqual(page.view.get_title(), "Choose what to install")

    def test_the_button_installs_what_is_ticked(self):
        c, page = self.page()
        asked = []
        c.install = asked.append
        page.enter()
        page._checks["launcher"].set_active(True)
        page._checks["aotr"].set_active(True)
        page.button.emit("clicked")
        self.assertEqual(asked, [("launcher", "aotr")])


if __name__ == "__main__":
    unittest.main()
