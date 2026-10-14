import contextlib
import io
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from bfme_wizard.__main__ import main, parse_args
from bfme_wizard.apps import AppLauncher
from bfme_wizard.controller import Controller
from bfme_wizard.diagnostics import any_log, build_report, data_dir, newest_log, tail
from bfme_wizard.model import SetupModel, games_line
from bfme_wizard.runner import ScriptRunner, app_is_ready, setup_is_complete
from tests.helpers import buttons, descendants, gtk_or_skip, labels, make_script, wait_for


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
        self.assertFalse(m.just_finished)   # the AIO Launcher is still to come
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
        self.assertEqual(self.games(self.LAUNCHER), "No games installed yet. Open the AIO Launcher to install them.")
        self.assertEqual(self.games(self.LAUNCHER, finished=True), "Setup is complete. Open the AIO Launcher to install your games.")
        self.assertEqual(self.games({**self.LAUNCHER, "bfme2": "installed"}, finished=True), "")

    def test_nothing_about_games_for_someone_who_did_not_install_the_aio_launcher(self):
        # Age of the Ring has its own copies of the games, and there is no AIO Launcher to open to install the others.
        self.assertEqual(self.games({"aotr": "installed"}), "")
        self.assertEqual(self.games({"aotr": "installed"}, finished=True), "")


APP = """#!/usr/bin/env bash
# fake setup script; the app commands run for APP_SECONDS
case "$1" in
  launcher|arena) sleep "${APP_SECONDS:-0}" ;;
  bad-exit) exit 3 ;;
esac
"""


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
                         "--- latest AIO Launcher log (launcher-20260102-000000.log", "line 99", "arena says hi", "--- no prefix creation log ---"):
            self.assertIn(expected, report)
        self.assertNotIn("line 59", report)   # only the last 40 lines
        self.assertNotIn("old\n", report)     # only the newest log

    def test_a_report_before_any_check_or_log_still_works(self):
        report = build_report("dev", SetupModel(), Path(tempfile.mkdtemp()))
        self.assertIn("(not run yet)", report)
        self.assertIn("--- no AIO Launcher log ---", report)

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

    def test_without_a_display_the_terminal_message_names_the_aio_launcher(self):
        out = io.StringIO()
        # os.execv never returns, so its stand-in must not either: past it, main() would start the real application.
        with mock.patch("bfme_wizard.__main__.find_script", return_value="/x/setup.sh"), \
                mock.patch("bfme_wizard.__main__.has_display", return_value=False), \
                mock.patch("bfme_wizard.__main__.os.execv", side_effect=SystemExit) as execv, \
                mock.patch("sys.argv", ["bfme-installer"]), contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            main()
        self.assertIn("Installing the AIO Launcher and the Arena in this terminal instead.", out.getvalue())
        execv.assert_called_once_with("/x/setup.sh", ["/x/setup.sh", "install"])

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
        # Someone who chose only Age of the Ring has no AIO Launcher or Arena: only its own entry can start at once.
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
        self.assertEqual(self.c.blocked_reason(), "The AIO Launcher, the Arena or Age of the Ring is still running.")
        self.c.apps.state["launcher"] = "idle"
        self.assertIsNone(self.c.blocked_reason())


class Advice(unittest.TestCase):
    def test_the_advice_about_graphics_drivers_names_the_aio_launcher(self):
        gtk_or_skip(self)
        from bfme_wizard.home import CANT_CHECK
        advice = {title: text for title, text, _command in CANT_CHECK}
        self.assertEqual(advice["Graphics drivers"], "The launchers/applications need working Vulkan drivers on your computer.")


class HomeCards(unittest.TestCase):
    """The home screen shows the programs that are installed, each with a button to open it. Installing and removing
    programs is the Programs page's job, and the buttons for the other pages float in the corner of the window's page."""

    ALL = {"launcher": "installed", "arena": "installed", "aotr": "installed"}

    def page(self, installed):
        Gtk = gtk_or_skip(self)
        from bfme_wizard.home import HomePage
        c = Controller(ScriptRunner(make_script(FLOW)), lambda: None)
        c.model.installed = installed
        page = HomePage(c, lambda: "1.0.0")
        page.refresh()
        return Gtk, c, page

    def titles(self, installed):
        Gtk, _c, page = self.page(installed)
        return labels(page.content, Gtk, "title-2")

    def test_only_the_installed_programs_have_a_card(self):
        self.assertEqual(self.titles(self.ALL), ["AIO Launcher", "Arena", "Age of the Ring"])
        self.assertEqual(self.titles({"launcher": "installed", "arena": "installed"}), ["AIO Launcher", "Arena"])
        self.assertEqual(self.titles({"aotr": "installed"}), ["Age of the Ring"])
        self.assertEqual(self.titles({"arena": "installed"}), ["Arena"])
        self.assertEqual(self.titles({"launcher": "installed", "aotr": "installed"}), ["AIO Launcher", "Age of the Ring"])

    def test_a_program_that_is_not_there_leaves_no_trace_of_itself(self):
        Gtk, _c, page = self.page({"launcher": "installed"})
        text = " ".join(labels(page.content, Gtk))
        for word in ("Arena", "Age of the Ring", "Not installed", "Comes with"):
            self.assertNotIn(word, text)

    def test_every_card_has_one_open_button_and_it_starts_its_own_program(self):
        Gtk, c, page = self.page(self.ALL)
        opened = []
        c.open_app = opened.append
        found = buttons(page.content, Gtk)
        self.assertEqual([b.get_label() for b in found], ["Open"] * 3)
        for button in found:
            button.emit("clicked")
        self.assertEqual(opened, ["launcher", "arena", "aotr"])

    def test_nothing_to_install_or_to_navigate_is_left_on_the_page(self):
        # Install belongs to the Programs page; Game folders and Troubleshoot are buttons in the corner of the window's page.
        Gtk, _c, page = self.page(self.ALL)
        self.assertEqual({b.get_label() for b in buttons(page.box, Gtk)}, {"Open"})

    def test_a_running_program_shows_that_and_a_quick_exit_says_so_softly(self):
        Gtk, c, page = self.page(self.ALL)
        c.apps.state.update(launcher="running", arena="quick")
        page.refresh()
        self.assertEqual([b.get_label() for b in buttons(page.content, Gtk)], ["Open", "Open"])   # not the running one
        text = labels(page.content, Gtk)
        self.assertIn("Running", text)
        self.assertTrue(any("Closed after a few seconds" in line for line in text))

    def test_with_nothing_installed_it_points_at_the_button_that_installs(self):
        # Not reachable through a real status (the setup is not complete then), but the page must not be a blank.
        Gtk, _c, page = self.page({})
        self.assertEqual(labels(page.content, Gtk, "title-2"), [])
        self.assertTrue(any("download button" in line for line in labels(page.content, Gtk)))

    def test_the_version_is_at_the_bottom(self):
        Gtk, _c, page = self.page(self.ALL)
        self.assertIn("Version 1.0.0", labels(page.box, Gtk, "caption"))


class GameFoldersWidget(unittest.TestCase):
    def page(self, home, opened):
        Gtk = gtk_or_skip(self)
        from bfme_wizard.home import GameFoldersPage
        with mock.patch.dict(os.environ, {"BFME_HOME": home, "BFME_RUNNER": "proton"}):
            return Gtk, GameFoldersPage(opened.append)

    def groups(self, Gtk, page):
        from gi.repository import Adw
        return [w for w in descendants(page.view) if isinstance(w, Adw.PreferencesGroup)]

    def test_only_the_installed_games_have_a_group_in_their_order_with_age_of_the_ring_last(self):
        with tempfile.TemporaryDirectory() as home:
            drive = Path(home) / "prefix/drive_c"
            for folder in ("RotWK", "BFME1", "AgeoftheRing"):
                (drive / folder).mkdir(parents=True)
            Gtk, page = self.page(home, [])
            self.assertEqual([g.get_title() for g in self.groups(Gtk, page)], ["BFME", "Rise of the Witch-king", "Age of the Ring"])

    def test_a_game_that_is_not_installed_leaves_no_trace_of_itself(self):
        with tempfile.TemporaryDirectory() as home:
            (Path(home) / "prefix/drive_c/BFME2").mkdir(parents=True)
            Gtk, page = self.page(home, [])
            text = " ".join(labels(page.view, Gtk))
            for word in ("Not installed", "Rise of the Witch-king", "Age of the Ring"):
                self.assertNotIn(word, text)
            self.assertEqual([g.get_title() for g in self.groups(Gtk, page)], ["BFME 2"])

    def test_with_no_game_installed_the_page_says_so_instead_of_being_empty(self):
        with tempfile.TemporaryDirectory() as home:
            Gtk, page = self.page(home, [])
            self.assertEqual(self.groups(Gtk, page), [])
            from gi.repository import Adw
            status = [w for w in descendants(page.view) if isinstance(w, Adw.StatusPage)]
            self.assertEqual(len(status), 1)
            self.assertEqual(status[0].get_title(), "No games installed")

    def test_its_rows_open_its_program_folder_and_its_lowercase_maps_folder(self):
        with tempfile.TemporaryDirectory() as home:
            drive = Path(home) / "prefix/drive_c"
            (drive / "AgeoftheRing").mkdir(parents=True)
            user = drive / "users/steamuser/AppData/Roaming/Age of the Ring"
            (user / "maps").mkdir(parents=True)
            opened = []
            Gtk, page = self.page(home, opened)
            from gi.repository import Adw
            rows = [w for w in descendants(self.groups(Gtk, page)[0]) if isinstance(w, Adw.ActionRow)]
            self.assertEqual([r.get_title() for r in rows], ["Game folder", "Maps and user data"])
            for row in rows:
                row.emit("activated")
            self.assertEqual(opened, [drive / "AgeoftheRing", user / "maps"])
            self.assertEqual([g.get_title() for g in self.groups(Gtk, page)], ["Age of the Ring"])   # the games are separate


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
