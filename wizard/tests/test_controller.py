import os
import stat
import tempfile
import unittest

from gi.repository import GLib

from bfme_wizard.controller import Controller
from bfme_wizard.runner import ScriptRunner

# A fake setup script. State lives in flag files in $FAKE_DIR; every call is appended to $FAKE_DIR/calls.
#   prefix, launcher, arena, aotr   what is installed
#   curl-fixed               the system check passes (without it `prepare` fails its check)
#   flaky                    `prepare` fails once, in the runner step
#   launcher-flaky           `launcher-install` fails once, in the `launcher` step
#   cancel-once              `launcher-install` is stopped once, before the arena step
#   aotr-bad                 `aotr-install` fails once, in the check
#   shortcuts-fails          `shortcuts` fails (the permission is gone, say)
#   remove-fails             `remove` fails and deletes nothing
FAKE = r"""#!/usr/bin/env bash
shift  # --machine
cmd="$1"
echo "$*" >> "$FAKE_DIR/calls"
once() { [ -f "$FAKE_DIR/$1" ] && [ ! -f "$FAKE_DIR/$1-used" ] && touch "$FAKE_DIR/$1-used"; }
# What the real script prints for `status`, and at the end of every job just before DONE.
report() {
  if [ -f "$FAKE_DIR/prefix" ]; then echo "@bfme STATUS prefix ready"; else echo "@bfme STATUS prefix missing"; fi
  if [ -f "$FAKE_DIR/launcher" ]; then echo "@bfme STATUS launcher installed"; else echo "@bfme STATUS launcher missing"; fi
  if [ -f "$FAKE_DIR/arena" ]; then echo "@bfme STATUS arena installed"; else echo "@bfme STATUS arena missing"; fi
  if [ -f "$FAKE_DIR/aotr" ]; then echo "@bfme STATUS aotr installed"; else echo "@bfme STATUS aotr missing"; fi
  if [ -f "$FAKE_DIR/prefix" ] && { [ -f "$FAKE_DIR/launcher" ] || [ -f "$FAKE_DIR/arena" ] || [ -f "$FAKE_DIR/aotr" ]; }; then
    echo "@bfme STATUS complete yes"; else echo "@bfme STATUS complete no"; fi
}
case "$cmd" in
  status) report ;;
  shortcuts)
    echo "Shortcuts are up to date in /fake"
    if [ -f "$FAKE_DIR/shortcuts-fails" ]; then echo "@bfme ERROR - Could not update the shortcuts"; exit 1; fi ;;
  reset-prefix) rm -f "$FAKE_DIR/prefix" "$FAKE_DIR/launcher" "$FAKE_DIR/arena" "$FAKE_DIR/aotr"; echo "Prefix deleted." ;;
  remove)
    if [ -f "$FAKE_DIR/remove-fails" ]; then echo "@bfme ERROR - Could not remove it"; exit 1; fi
    rm -f "$FAKE_DIR/$2"; report; echo "@bfme DONE" ;;
  doctor)
    if [ -f "$FAKE_DIR/curl-fixed" ]; then echo "@bfme CHECK cmd-curl ok curl found"; exit 0; fi
    echo "@bfme CHECK cmd-curl fail curl not found"; echo "@bfme FIX cmd-curl sudo apt install curl"; exit 1 ;;
  prepare)
    echo "@bfme STEP doctor start"
    if [ ! -f "$FAKE_DIR/curl-fixed" ]; then
      echo "@bfme CHECK cmd-curl fail curl not found"; echo "@bfme FIX cmd-curl sudo apt install curl"
      echo "@bfme ERROR doctor Fix the problems above, then run prepare again."; exit 1
    fi
    echo "@bfme CHECK cmd-curl ok curl found"; echo "@bfme STEP doctor done"
    echo "@bfme STEP runner start"
    if once flaky; then echo "@bfme ERROR runner Failed (exit 22)."; exit 22; fi
    echo "@bfme PROGRESS 50"; echo "@bfme STEP runner done"
    echo "@bfme STEP prefix start"; echo "@bfme STEP prefix done"
    touch "$FAKE_DIR/prefix"; report; echo "@bfme DONE" ;;
  launcher-install)
    echo "@bfme STEP launcher start"
    if once launcher-flaky; then echo "@bfme ERROR launcher Failed (exit 22)."; exit 22; fi
    echo "@bfme STEP launcher done"; echo "@bfme STEP arena start"
    if once cancel-once; then echo "@bfme CANCELLED"; exit 130; fi
    echo "@bfme STEP arena done"; echo "@bfme STEP shortcuts skip"
    touch "$FAKE_DIR/launcher" "$FAKE_DIR/arena"; report; echo "@bfme DONE" ;;
  aotr-install)
    echo "@bfme STEP aotr-check start"
    if once aotr-bad; then echo "@bfme ERROR aotr-check This file is incomplete."; exit 1; fi
    echo "@bfme STEP aotr-check done"; echo "@bfme PROGRESS 40"
    echo "@bfme STEP aotr-install start"; echo "@bfme STEP aotr-install done"
    touch "$FAKE_DIR/aotr"; report; echo "@bfme DONE" ;;
esac
"""

ZIP = "/tmp/AotR_Standalone_9.3.0_Installer.zip"


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.environ["FAKE_DIR"] = self.dir
        self.script = os.path.join(self.dir, "fake.sh")
        with open(self.script, "w") as f:
            f.write(FAKE)
        os.chmod(self.script, os.stat(self.script).st_mode | stat.S_IXUSR)
        self.loop = GLib.MainLoop()
        self.states = []
        self.c = self.controller()

    def controller(self, offer=None):
        return Controller(ScriptRunner(self.script), self.changed, offer=offer)

    def changed(self):
        if not self.states or self.states[-1] != self.c.model.state:
            self.states.append(self.c.model.state)

    def run_until(self, state, action):
        action()
        def check():
            if self.c.model.state == state and not self.c.runner.busy:
                self.loop.quit()
                return False
            return True
        GLib.timeout_add(50, check)
        GLib.timeout_add(10000, self.loop.quit)
        self.loop.run()
        self.assertEqual(self.c.model.state, state)

    def flag(self, *names):
        for name in names:
            open(os.path.join(self.dir, name), "w").close()

    def calls(self, raw=False):
        """What the script was asked to do. The quiet `shortcuts` run after every status is left out unless `raw`: it has
        tests of its own (Shortcuts), and the tests that read this are about which jobs ran."""
        try:
            with open(os.path.join(self.dir, "calls")) as f:
                calls = f.read().splitlines()
        except FileNotFoundError:
            return []
        return calls if raw else [c for c in calls if c != "shortcuts"]


class Flow(Base):
    def test_fresh_start_then_install_the_aio_launcher(self):
        self.run_until("idle", self.c.start)
        self.assertFalse(self.c.model.paused)
        self.flag("curl-fixed")
        self.run_until("done", lambda: self.c.install(["launcher"]))
        self.assertEqual(self.c.model.done_count, 6)
        self.assertEqual(self.calls(), ["status", "prepare", "launcher-install"])
        self.assertTrue(self.c.model.is_installed("launcher"))
        self.assertTrue(self.c.model.just_finished)

    def test_already_installed_starts_on_done(self):
        self.flag("prefix", "launcher")
        self.run_until("done", self.c.start)

    def test_a_ready_environment_is_not_set_up_again(self):
        self.flag("prefix", "curl-fixed")
        self.run_until("idle", self.c.start)
        self.assertTrue(self.c.model.environment_ready)
        self.run_until("done", lambda: self.c.install(["launcher"]))
        self.assertEqual(self.calls(), ["status", "launcher-install"])

    def test_nothing_chosen_installs_nothing(self):
        self.run_until("idle", self.c.start)
        self.c.install([])
        self.assertEqual((self.c.model.state, self.c.runner.busy, self.calls()), ("idle", False, ["status"]))

    def test_blocked_then_recheck_continues_the_plan(self):
        self.run_until("blocked", lambda: self.c.install(["launcher"]))
        self.assertEqual([(p.message, p.command) for p in self.c.model.problems],
                         [("curl not found", "sudo apt install curl")])
        self.run_until("blocked", self.c.recheck)  # still not fixed
        self.assertEqual(len(self.c.model.problems), 1)
        self.flag("curl-fixed")
        self.run_until("done", self.c.recheck)  # fixed: the recheck carries on into the plan
        self.assertEqual(self.c.model.problems, [])
        self.assertEqual(self.calls()[-2:], ["prepare", "launcher-install"])

    def test_failure_then_retry_runs_the_job_that_failed(self):
        self.flag("curl-fixed", "flaky")
        self.run_until("failed", lambda: self.c.install(["launcher"]))
        self.assertEqual(self.c.model.failed_step, "runner")
        self.assertIn("Failed (exit 22).", self.c.model.log_text())
        self.run_until("done", self.c.retry)
        self.assertIsNone(self.c.model.error)
        self.assertEqual(self.calls(), ["prepare", "prepare", "launcher-install"])

    def test_a_retry_does_not_repeat_the_jobs_that_finished(self):
        self.flag("curl-fixed", "launcher-flaky")
        self.run_until("failed", lambda: self.c.install(["launcher"]))
        self.assertEqual(self.c.model.failed_step, "launcher")
        self.run_until("done", self.c.retry)
        self.assertEqual(self.calls(), ["prepare", "launcher-install", "launcher-install"])

    def test_stopping_pauses_the_setup_and_resume_carries_on_with_the_aio_launcher(self):
        self.flag("curl-fixed", "cancel-once")
        self.run_until("cancelled", lambda: self.c.install(["launcher"]))
        self.assertTrue(self.c.model.paused)
        self.run_until("done", self.c.resume)
        self.assertEqual(self.calls(), ["prepare", "launcher-install", "launcher-install"])

    def test_choosing_the_same_again_after_a_stop_picks_up_where_it_stopped(self):
        # The start page button is install() for both Install and Resume.
        self.flag("curl-fixed", "cancel-once")
        self.run_until("cancelled", lambda: self.c.install(["launcher"]))
        self.run_until("done", lambda: self.c.install(["launcher"]))
        self.assertEqual(self.calls(), ["prepare", "launcher-install", "launcher-install"])   # no second prepare

    def test_a_different_choice_after_a_stop_starts_a_new_plan(self):
        self.flag("curl-fixed", "cancel-once")
        self.run_until("cancelled", lambda: self.c.install(["launcher"]))
        self.run_until("waiting", lambda: self.c.install(["aotr"]))
        # The jobs report the prepared environment, so the new plan skips it.
        self.assertEqual(self.c.model.plan, ["aotr"])
        self.assertEqual(self.calls(), ["prepare", "launcher-install"])

    def test_a_cancel_pressed_during_the_last_step_of_a_job_does_not_start_the_next_job(self):
        self.flag("curl-fixed")
        self.c.install(["launcher", "aotr"])
        self.c.model.request_cancel()   # as the Cancel button does; the script has no step left to stop before
        self.run_until("cancelled", lambda: None)
        self.assertEqual(self.calls(), ["prepare"])
        # The same choice resumes at the next job, then waits for the Age of the Ring file.
        self.run_until("waiting", lambda: self.c.install(["launcher", "aotr"]))
        self.assertEqual(self.calls(), ["prepare", "launcher-install"])

    def test_a_second_install_while_running_is_ignored(self):
        self.flag("curl-fixed")
        self.c.install(["launcher"])
        self.c.install(["launcher"])  # ignored: the first is still running
        self.c.start()                # also ignored
        GLib.timeout_add(5000, self.loop.quit)
        GLib.timeout_add(50, lambda: (self.loop.quit(), False)[1] if self.c.model.state == "done" else True)
        self.loop.run()
        self.assertEqual(self.c.model.state, "done")
        self.assertEqual(self.calls().count("prepare"), 1)


class AgeOfTheRing(Base):
    def test_alone_it_installs_neither_the_aio_launcher_nor_the_arena(self):
        self.flag("curl-fixed")
        self.run_until("idle", self.c.start)
        self.run_until("waiting", lambda: self.c.install(["aotr"]))
        self.assertEqual(self.calls(), ["status", "prepare"])     # the environment, then it waits for the file
        self.assertEqual((self.c.model.job, self.c.model.current), ("aotr", "aotr-download"))
        self.run_until("done", lambda: self.c.choose_aotr_file(ZIP))
        self.assertEqual(self.calls(), ["status", "prepare", f"aotr-install {ZIP}"])
        m = self.c.model
        self.assertTrue(m.aotr_installed)
        self.assertFalse(m.is_installed("launcher"))
        self.assertFalse(m.is_installed("arena"))
        self.assertTrue(m.just_finished)

    def test_with_the_aio_launcher_it_comes_last(self):
        self.flag("curl-fixed")
        self.run_until("waiting", lambda: self.c.install(["aotr", "launcher"]))
        self.assertEqual(self.calls(), ["prepare", "launcher-install"])
        self.run_until("done", lambda: self.c.choose_aotr_file(ZIP))
        self.assertEqual(self.calls(), ["prepare", "launcher-install", f"aotr-install {ZIP}"])
        self.assertTrue(self.c.model.aotr_installed and self.c.model.is_installed("launcher"))

    def test_the_download_page_knows_what_the_jobs_before_it_installed(self):
        # Regression: its exit said "Back to start" with the AIO Launcher already installed, because it went by the
        # status taken when the app opened. Each job reports where things stand, so leaving lands where it says.
        self.flag("curl-fixed")
        self.run_until("idle", self.c.start)
        self.assertFalse(self.c.model.has_home_screen)
        self.run_until("waiting", lambda: self.c.install(["launcher", "aotr"]))
        self.assertTrue(self.c.model.has_home_screen)
        self.assertEqual(self.calls(), ["status", "prepare", "launcher-install"])   # learned without asking again
        self.run_until("done", self.c.back_home)    # and it really is the home screen

    def test_leaving_when_only_the_environment_was_prepared_lands_on_the_start_page(self):
        self.flag("curl-fixed")
        self.run_until("waiting", lambda: self.c.install(["aotr"]))
        self.assertFalse(self.c.model.has_home_screen)
        self.assertTrue(self.c.model.environment_ready)

    def test_from_the_home_screen_it_goes_straight_to_the_download_page(self):
        self.flag("prefix", "launcher")
        self.run_until("done", self.c.start)
        before = self.calls()
        self.run_until("waiting", lambda: self.c.install(["aotr"]))
        self.assertEqual(self.calls(), before)   # nothing ran: the environment and the AIO Launcher are already there
        self.assertTrue(self.c.model.started_from_home)

    def test_a_failed_check_can_be_retried_with_the_same_file(self):
        self.flag("prefix", "launcher", "aotr-bad")
        self.run_until("done", self.c.start)
        self.c.install(["aotr"])
        self.run_until("failed", lambda: self.c.choose_aotr_file(ZIP))
        self.assertEqual(self.c.model.failed_step, "aotr-check")
        self.assertIn("incomplete", self.c.model.error.message)
        self.run_until("done", self.c.retry)   # runs aotr-install again with the same file, not the setup
        self.assertTrue(self.c.model.aotr_installed)
        self.assertEqual([c for c in self.calls() if c.startswith("aotr")], [f"aotr-install {ZIP}"] * 2)

    def test_a_failed_check_can_be_followed_by_another_file(self):
        self.flag("prefix", "launcher", "aotr-bad")
        self.run_until("done", self.c.start)
        self.c.install(["aotr"])
        self.run_until("failed", lambda: self.c.choose_aotr_file("/tmp/old.zip"))
        self.run_until("waiting", self.c.choose_another_aotr_file)
        self.run_until("done", lambda: self.c.choose_aotr_file("/tmp/new.zip"))
        self.assertEqual([c for c in self.calls() if c.startswith("aotr")],
                         ["aotr-install /tmp/old.zip", "aotr-install /tmp/new.zip"])

    def test_back_home_looks_at_the_setup_again(self):
        self.flag("prefix", "launcher", "aotr-bad")
        self.run_until("done", self.c.start)
        self.c.install(["aotr"])
        self.run_until("failed", lambda: self.c.choose_aotr_file(ZIP))
        self.run_until("done", self.c.back_home)
        self.assertFalse(self.c.model.aotr_installed)

    def test_leaving_the_download_page_of_a_first_setup_goes_back_to_the_start_page(self):
        self.flag("curl-fixed")
        self.run_until("waiting", lambda: self.c.install(["aotr"]))
        self.run_until("idle", self.c.back_home)           # nothing is installed yet, so there is no home screen
        self.assertTrue(self.c.model.environment_ready)    # but the environment is ready, and says so
        self.assertEqual(self.c.model.selection, ("aotr",))


class Shortcuts(Base):
    """A shortcut lives exactly as long as its program, so the wizard asks the script to bring them in line with what is
    installed every time it starts, whichever page comes next. (The script does the writing and the removing.)"""

    def test_a_start_with_something_installed_does_it_before_the_quiet_checks(self):
        self.flag("prefix", "launcher")
        self.run_until("done", self.c.start)
        self.assertEqual(self.calls(raw=True), ["status", "shortcuts", "doctor"])

    def test_a_start_with_nothing_installed_does_it_too(self):
        # The last program to go takes the home screen with it, and its shortcut must not be missed for that.
        self.run_until("idle", self.c.start)
        self.assertEqual(self.calls(raw=True), ["status", "shortcuts"])

    def test_a_program_removed_by_hand_is_noticed_at_the_next_start(self):
        self.flag("prefix", "launcher", "aotr")
        self.run_until("done", self.c.start)
        os.unlink(os.path.join(self.dir, "aotr"))          # the player deleted Age of the Ring
        self.run_until("done", self.c.start)               # and opens the wizard again
        self.assertEqual(self.calls(raw=True).count("shortcuts"), 2)
        self.assertFalse(self.c.model.aotr_installed)

    def test_the_only_program_removed_by_hand_is_noticed_too(self):
        self.flag("prefix", "launcher")
        self.run_until("done", self.c.start)
        os.unlink(os.path.join(self.dir, "launcher"))
        self.run_until("idle", self.c.start)               # no home screen any more: the start page
        self.assertEqual(self.calls(raw=True), ["status", "shortcuts", "doctor", "status", "shortcuts"])

    def test_reset_removes_the_programs_and_then_looks_again_so_the_shortcuts_follow(self):
        self.flag("prefix", "launcher", "aotr")
        self.run_until("done", self.c.start)
        results = []
        self.run_until("idle", lambda: self.c.reset(results.append))
        self.assertEqual(results, [True])
        self.assertEqual(self.calls(raw=True)[-3:], ["reset-prefix --yes", "status", "shortcuts"])

    def test_a_shortcut_of_a_program_that_is_gone_is_removed_before_the_install_page_comes_up(self):
        # Clicking the Age of the Ring shortcut after the mod was deleted: the shortcut goes, and the wizard offers it again.
        self.flag("prefix", "launcher")
        self.c = self.controller(offer="aotr")
        self.run_until("waiting", self.c.start)
        self.assertEqual(self.calls(raw=True), ["status", "shortcuts"])

    def test_installing_does_not_add_a_run_of_its_own(self):
        # The jobs write the shortcuts of what they install themselves, so the wizard asks once per start.
        self.flag("curl-fixed")
        self.run_until("idle", self.c.start)
        self.run_until("done", lambda: self.c.install(["launcher"]))
        self.assertEqual(self.calls(raw=True), ["status", "shortcuts", "prepare", "launcher-install"])

    def test_what_the_script_says_about_it_stays_out_of_the_log(self):
        self.flag("prefix", "launcher")
        self.run_until("done", self.c.start)
        self.assertNotIn("Shortcuts are up to date", self.c.model.log_text())

    def test_a_failing_run_changes_nothing_for_the_player(self):
        # Shortcuts are optional, so the wizard still starts.
        self.flag("prefix", "launcher", "shortcuts-fails")
        self.run_until("done", self.c.start)
        self.assertIsNone(self.c.model.error)
        self.assertFalse(self.c.checking)
        self.assertEqual(self.calls(raw=True), ["status", "shortcuts", "doctor"])   # and the checks still run

    def test_the_page_waits_for_the_shortcuts_so_its_buttons_never_meet_a_busy_script(self):
        # Shown first, its buttons would do nothing while the script ran. So the first time the home screen is rendered,
        # the shortcuts have been brought in line and the script is free again.
        self.flag("prefix", "launcher")
        first = []
        def changed():
            if self.c.model.state == "done" and not first:
                first.append(("shortcuts" in self.calls(raw=True), self.c.runner.busy))
        self.c._on_change = changed
        self.run_until("done", self.c.start)
        self.assertEqual(first, [(True, False)])

    def test_the_start_page_waits_too(self):
        first = []
        def changed():
            if self.c.model.state == "idle" and not first:
                first.append(("shortcuts" in self.calls(raw=True), self.c.runner.busy))
        self.c._on_change = changed
        self.run_until("idle", self.c.start)
        self.assertEqual(first, [(True, False)])


class Removal(Base):
    """Taking one program out of the game environment, from the Programs page."""

    EVERYTHING = ("prefix", "launcher", "arena", "aotr")

    def started(self, *flags):
        self.flag(*(flags or self.EVERYTHING))
        self.run_until("done", self.c.start)

    def remove(self, program, results=None):
        results = [] if results is None else results
        self.run_until("done", lambda: self.assertTrue(self.c.remove(program, results.append)))
        return results

    def test_a_program_goes_and_the_others_stay(self):
        self.started()
        self.assertEqual(self.remove("arena"), [True])
        m = self.c.model
        self.assertEqual([m.is_installed(p) for p in ("launcher", "arena", "aotr")], [True, False, True])
        self.assertEqual(self.calls(), ["status", "doctor", "remove arena", "status", "doctor"])

    def test_each_program_can_go_by_itself(self):
        for program in ("launcher", "arena", "aotr"):
            with self.subTest(program):
                self.setUp()
                self.started()
                self.assertEqual(self.remove(program), [True])
                gone = [p for p in ("launcher", "arena", "aotr") if not self.c.model.is_installed(p)]
                self.assertEqual(gone, [program])

    def test_the_window_sees_it_as_a_state_of_its_own_and_then_looks_at_the_setup_again(self):
        self.started()
        self.states.clear()
        self.remove("launcher")
        self.assertEqual(self.states, ["removing", "checking", "done"])

    def test_the_last_program_to_go_leaves_the_start_page_with_a_ready_environment(self):
        self.started("prefix", "aotr")
        self.states.clear()
        self.run_until("idle", lambda: self.c.remove("aotr", lambda ok: None))
        self.assertEqual((self.c.model.environment_ready, self.c.model.has_home_screen), (True, False))
        self.assertEqual(self.states[-1], "idle")

    def test_a_failed_removal_says_what_went_wrong_and_looks_again(self):
        self.started()
        self.flag("remove-fails")
        seen = []
        self.run_until("done", lambda: self.c.remove("launcher", lambda ok: seen.append((ok, self.c.model.error.message))))
        self.assertEqual(seen, [(False, "Could not remove it")])
        self.assertTrue(self.c.model.is_installed("launcher"))      # nothing was deleted
        self.assertIsNone(self.c.model.error)                        # and the home screen is not an error page

    def test_it_is_refused_while_the_setup_runs_or_a_program_is_open_or_the_script_is_busy(self):
        self.started()
        before = self.calls()
        self.c.model.state = "running"
        self.assertFalse(self.c.remove("arena", lambda ok: None))
        self.c.model.state = "done"
        self.c.apps.state["launcher"] = "running"
        self.assertFalse(self.c.remove("arena", lambda ok: None))
        self.c.apps.state["launcher"] = "idle"
        self.c.run_checks()
        self.assertFalse(self.c.remove("arena", lambda ok: None))
        self.run_until("done", lambda: None)
        self.assertEqual(self.calls()[len(before):], ["doctor"])     # only the checks ran

    def test_only_a_program_can_be_removed(self):
        self.started()
        for name in ("everything", "prefix", "", "BFME2", "launcher-install"):
            self.assertFalse(self.c.remove(name, lambda ok: None), name)
        self.assertEqual([c for c in self.calls() if c.startswith("remove")], [])

    def test_the_reason_it_waits_is_told(self):
        self.started()
        self.c.model.state = "removing"
        self.assertIn("being removed", self.c.blocked_reason())
        self.c.model.state = "running"
        self.assertIn("setup is running", self.c.blocked_reason())

    def test_a_program_that_was_removed_can_be_installed_again(self):
        self.started()
        self.remove("launcher")
        self.flag("curl-fixed")
        self.run_until("done", lambda: self.c.install(["launcher"]))
        self.assertTrue(self.c.model.is_installed("launcher"))


class Offer(Base):
    """What a shortcut wanted, when the setup could not just start it."""

    def test_an_entry_for_a_program_that_is_not_installed_prechooses_it_on_the_start_page(self):
        for entry, program in (("launcher", "launcher"), ("arena", "launcher"), ("aotr", "aotr")):
            self.c = self.controller(offer=entry)
            self.run_until("idle", self.c.start)
            self.assertEqual(self.c.model.selection, (program,), entry)

    def test_no_entry_chooses_nothing(self):
        self.run_until("idle", self.c.start)
        self.assertEqual(self.c.model.selection, ())

    def test_the_age_of_the_ring_entry_goes_to_its_download_page_on_a_complete_setup(self):
        self.flag("prefix", "launcher")
        self.c = self.controller(offer="aotr")
        self.run_until("waiting", self.c.start)
        self.assertEqual(self.calls(), ["status"])   # no system checks first: the download page is already waiting

    def test_but_only_once(self):
        self.flag("prefix", "launcher")
        self.c = self.controller(offer="aotr")
        self.run_until("waiting", self.c.start)
        self.run_until("done", self.c.back_home)

    def test_the_age_of_the_ring_entry_does_nothing_when_it_is_installed(self):
        self.flag("prefix", "launcher", "aotr")
        self.c = self.controller(offer="aotr")
        self.run_until("done", self.c.start)

    def test_an_aio_launcher_entry_on_a_complete_setup_just_shows_the_home_screen(self):
        self.flag("prefix", "aotr")
        self.c = self.controller(offer="launcher")
        self.run_until("done", self.c.start)
        self.assertFalse(self.c.model.is_installed("launcher"))


if __name__ == "__main__":
    unittest.main()
