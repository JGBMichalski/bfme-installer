import os
import stat
import tempfile
import time
import unittest
from pathlib import Path

from gi.repository import GLib

from bfme_wizard.__main__ import parse_args
from bfme_wizard.apps import AppLauncher
from bfme_wizard.controller import Controller
from bfme_wizard.diagnostics import any_log, build_report, data_dir, newest_log, tail
from bfme_wizard.model import SetupModel, games_line
from bfme_wizard.runner import ScriptRunner, setup_is_complete


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
        m.begin_install()
        feed(m, "@bfme DONE")
        m.finish_install(0)
        self.assertTrue(m.just_finished)
        m.begin_install()
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
    def games(self, installed, finished=False):
        m = SetupModel()
        m.installed = installed
        m.just_finished = finished
        return games_line(m)

    def test_wording(self):
        self.assertEqual(self.games({"bfme2": "installed"}), "")
        self.assertEqual(self.games({"bfme1": "installed", "bfme2": "installed", "rotwk": "installed"}), "")
        self.assertEqual(self.games({}), "No games installed yet. Open the Launcher to install them.")
        self.assertEqual(self.games({}, finished=True), "Setup is complete. Open the Launcher to install your games.")
        self.assertEqual(self.games({"bfme2": "installed"}, finished=True), "")


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
        self.assertEqual(apps.state, {"launcher": "running", "arena": "running"})
        self.assertTrue(apps.any_running)
        wait_for(5000, lambda: not apps.any_running)
        self.assertEqual(apps.state, {"launcher": "idle", "arena": "idle"})

    def test_a_program_that_cannot_start_counts_as_closed_quickly(self):
        apps = AppLauncher("/nonexistent/script", lambda: None)
        apps.start("launcher")
        self.assertEqual(apps.state["launcher"], "quick")

    def test_unknown_names_are_ignored(self):
        apps = AppLauncher(make_script(APP), lambda: None)
        apps.start("bad-exit")
        self.assertEqual(apps.state, {"launcher": "idle", "arena": "idle"})


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


class OfferedApp(unittest.TestCase):
    """The app a menu entry wanted is the highlighted one on the home screen."""

    def highlighted(self, offer):
        try:
            import gi
            gi.require_version("Gtk", "4.0")
            gi.require_version("Adw", "1")
            from gi.repository import Gtk
            from bfme_wizard.home import HomePage
        except (ValueError, ImportError):
            self.skipTest("GTK is not installed")   # the CI job installs only the GLib bindings
        if not Gtk.init_check():
            self.skipTest("no display")
        c = Controller(ScriptRunner(make_script(FLOW)), lambda: None)
        page = HomePage(c, lambda: "1.0.0", offer, lambda: None)
        page.refresh()
        found = {}
        def walk(w):
            while w:
                if isinstance(w, Gtk.Button) and w.get_label() == "Open":
                    found[len(found)] = w.has_css_class("suggested-action")
                walk(w.get_first_child())
                w = w.get_next_sibling()
        walk(page.content)
        return [found[0], found[1]]   # Launcher card first, then Arena

    def test_launcher_by_default_and_the_offered_app_otherwise(self):
        self.assertEqual(self.highlighted(None), [True, False])
        self.assertEqual(self.highlighted("launcher"), [True, False])
        self.assertEqual(self.highlighted("arena"), [False, True])


if __name__ == "__main__":
    unittest.main()
