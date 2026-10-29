import os
import stat

import pytest

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
  if [ -f "$FAKE_DIR/graphics" ]; then echo "@bfme STATUS graphics $(cat "$FAKE_DIR/graphics")"; else echo "@bfme STATUS graphics vulkan"; fi
  if [ -f "$FAKE_DIR/prefix" ]; then echo "@bfme STATUS prefix ready"; else echo "@bfme STATUS prefix missing"; fi
  if [ -f "$FAKE_DIR/launcher" ]; then echo "@bfme STATUS launcher installed"; else echo "@bfme STATUS launcher missing"; fi
  if [ -f "$FAKE_DIR/arena" ]; then echo "@bfme STATUS arena installed"; else echo "@bfme STATUS arena missing"; fi
  if [ -f "$FAKE_DIR/aotr" ]; then echo "@bfme STATUS aotr installed"; else echo "@bfme STATUS aotr missing"; fi
  if [ -f "$FAKE_DIR/prefix" ] && { [ -f "$FAKE_DIR/launcher" ] || [ -f "$FAKE_DIR/arena" ] || [ -f "$FAKE_DIR/aotr" ]; }; then
    echo "@bfme STATUS complete yes"; else echo "@bfme STATUS complete no"; fi
}
case "$cmd" in
  status) report ;;
  graphics)
    case "$2" in
      vulkan|opengl) printf '%s' "$2" > "$FAKE_DIR/graphics"; report; echo "@bfme DONE" ;;
      *) echo "@bfme ERROR - Use: graphics vulkan|opengl"; exit 1 ;;
    esac ;;
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


class Fake:
    """A controller driving the fake script in `dir`, and what it was seen doing."""

    def __init__(self, dir):
        self.dir = str(dir)
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
        assert self.c.model.state == state

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

    def started(self, *flags):
        """Removal: a setup with these installed (everything by default), on its home screen."""
        self.flag(*(flags or EVERYTHING))
        self.run_until("done", self.c.start)

    def remove(self, program, results=None):
        results = [] if results is None else results
        accepted = []
        self.run_until("done", lambda: accepted.append(self.c.remove(program, results.append)))
        assert accepted == [True]
        return results


EVERYTHING = ("prefix", "launcher", "arena", "aotr")


@pytest.fixture
def fake(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_DIR", str(tmp_path))
    return Fake(tmp_path)


# Flow
def test_fresh_start_then_install_the_aio_launcher(fake):
    fake.run_until("idle", fake.c.start)
    assert not fake.c.model.paused
    fake.flag("curl-fixed")
    fake.run_until("done", lambda: fake.c.install(["launcher"]))
    assert fake.c.model.done_count == 6
    assert fake.calls() == ["status", "prepare", "launcher-install"]
    assert fake.c.model.is_installed("launcher")
    assert fake.c.model.just_finished


def test_already_installed_starts_on_done(fake):
    fake.flag("prefix", "launcher")
    fake.run_until("done", fake.c.start)


def test_a_ready_environment_is_not_set_up_again(fake):
    fake.flag("prefix", "curl-fixed")
    fake.run_until("idle", fake.c.start)
    assert fake.c.model.environment_ready
    fake.run_until("done", lambda: fake.c.install(["launcher"]))
    assert fake.calls() == ["status", "launcher-install"]


def test_nothing_chosen_installs_nothing(fake):
    fake.run_until("idle", fake.c.start)
    fake.c.install([])
    assert (fake.c.model.state, fake.c.runner.busy, fake.calls()) == ("idle", False, ["status"])


def test_blocked_then_recheck_continues_the_plan(fake):
    fake.run_until("blocked", lambda: fake.c.install(["launcher"]))
    assert [(p.message, p.command) for p in fake.c.model.problems] == [("curl not found", "sudo apt install curl")]
    fake.run_until("blocked", fake.c.recheck)  # still not fixed
    assert len(fake.c.model.problems) == 1
    fake.flag("curl-fixed")
    fake.run_until("done", fake.c.recheck)  # fixed: the recheck carries on into the plan
    assert fake.c.model.problems == []
    assert fake.calls()[-2:] == ["prepare", "launcher-install"]


def test_failure_then_retry_runs_the_job_that_failed(fake):
    fake.flag("curl-fixed", "flaky")
    fake.run_until("failed", lambda: fake.c.install(["launcher"]))
    assert fake.c.model.failed_step == "runner"
    assert "Failed (exit 22)." in fake.c.model.log_text()
    fake.run_until("done", fake.c.retry)
    assert fake.c.model.error is None
    assert fake.calls() == ["prepare", "prepare", "launcher-install"]


def test_a_retry_does_not_repeat_the_jobs_that_finished(fake):
    fake.flag("curl-fixed", "launcher-flaky")
    fake.run_until("failed", lambda: fake.c.install(["launcher"]))
    assert fake.c.model.failed_step == "launcher"
    fake.run_until("done", fake.c.retry)
    assert fake.calls() == ["prepare", "launcher-install", "launcher-install"]


def test_stopping_pauses_the_setup_and_resume_carries_on_with_the_aio_launcher(fake):
    fake.flag("curl-fixed", "cancel-once")
    fake.run_until("cancelled", lambda: fake.c.install(["launcher"]))
    assert fake.c.model.paused
    fake.run_until("done", fake.c.resume)
    assert fake.calls() == ["prepare", "launcher-install", "launcher-install"]


def test_choosing_the_same_again_after_a_stop_picks_up_where_it_stopped(fake):
    # The start page button is install() for both Install and Resume.
    fake.flag("curl-fixed", "cancel-once")
    fake.run_until("cancelled", lambda: fake.c.install(["launcher"]))
    fake.run_until("done", lambda: fake.c.install(["launcher"]))
    assert fake.calls() == ["prepare", "launcher-install", "launcher-install"]   # no second prepare


def test_a_different_choice_after_a_stop_starts_a_new_plan(fake):
    fake.flag("curl-fixed", "cancel-once")
    fake.run_until("cancelled", lambda: fake.c.install(["launcher"]))
    fake.run_until("waiting", lambda: fake.c.install(["aotr"]))
    # The jobs report the prepared environment, so the new plan skips it.
    assert fake.c.model.plan == ["aotr"]
    assert fake.calls() == ["prepare", "launcher-install"]


def test_a_cancel_pressed_during_the_last_step_of_a_job_does_not_start_the_next_job(fake):
    fake.flag("curl-fixed")
    fake.c.install(["launcher", "aotr"])
    fake.c.model.request_cancel()   # as the Cancel button does; the script has no step left to stop before
    fake.run_until("cancelled", lambda: None)
    assert fake.calls() == ["prepare"]
    # The same choice resumes at the next job, then waits for the Age of the Ring file.
    fake.run_until("waiting", lambda: fake.c.install(["launcher", "aotr"]))
    assert fake.calls() == ["prepare", "launcher-install"]


def test_a_second_install_while_running_is_ignored(fake):
    fake.flag("curl-fixed")
    fake.c.install(["launcher"])
    fake.c.install(["launcher"])  # ignored: the first is still running
    fake.c.start()                # also ignored
    GLib.timeout_add(5000, fake.loop.quit)
    GLib.timeout_add(50, lambda: (fake.loop.quit(), False)[1] if fake.c.model.state == "done" else True)
    fake.loop.run()
    assert fake.c.model.state == "done"
    assert fake.calls().count("prepare") == 1


# Age of the Ring
def test_alone_it_installs_neither_the_aio_launcher_nor_the_arena(fake):
    fake.flag("curl-fixed")
    fake.run_until("idle", fake.c.start)
    fake.run_until("waiting", lambda: fake.c.install(["aotr"]))
    assert fake.calls() == ["status", "prepare"]     # the environment, then it waits for the file
    assert (fake.c.model.job, fake.c.model.current) == ("aotr", "aotr-download")
    fake.run_until("done", lambda: fake.c.choose_aotr_file(ZIP))
    assert fake.calls() == ["status", "prepare", f"aotr-install {ZIP}"]
    m = fake.c.model
    assert m.aotr_installed
    assert not m.is_installed("launcher")
    assert not m.is_installed("arena")
    assert m.just_finished


def test_with_the_aio_launcher_it_comes_last(fake):
    fake.flag("curl-fixed")
    fake.run_until("waiting", lambda: fake.c.install(["aotr", "launcher"]))
    assert fake.calls() == ["prepare", "launcher-install"]
    fake.run_until("done", lambda: fake.c.choose_aotr_file(ZIP))
    assert fake.calls() == ["prepare", "launcher-install", f"aotr-install {ZIP}"]
    assert fake.c.model.aotr_installed and fake.c.model.is_installed("launcher")


def test_the_download_page_knows_what_the_jobs_before_it_installed(fake):
    # Regression: its exit said "Back to start" with the AIO Launcher already installed, because it went by the
    # status taken when the app opened. Each job reports where things stand, so leaving lands where it says.
    fake.flag("curl-fixed")
    fake.run_until("idle", fake.c.start)
    assert not fake.c.model.has_home_screen
    fake.run_until("waiting", lambda: fake.c.install(["launcher", "aotr"]))
    assert fake.c.model.has_home_screen
    assert fake.calls() == ["status", "prepare", "launcher-install"]   # learned without asking again
    fake.run_until("done", fake.c.back_home)    # and it really is the home screen


def test_leaving_when_only_the_environment_was_prepared_lands_on_the_start_page(fake):
    fake.flag("curl-fixed")
    fake.run_until("waiting", lambda: fake.c.install(["aotr"]))
    assert not fake.c.model.has_home_screen
    assert fake.c.model.environment_ready


def test_from_the_home_screen_it_goes_straight_to_the_download_page(fake):
    fake.flag("prefix", "launcher")
    fake.run_until("done", fake.c.start)
    before = fake.calls()
    fake.run_until("waiting", lambda: fake.c.install(["aotr"]))
    assert fake.calls() == before   # nothing ran: the environment and the AIO Launcher are already there
    assert fake.c.model.started_from_home


def test_a_failed_check_can_be_retried_with_the_same_file(fake):
    fake.flag("prefix", "launcher", "aotr-bad")
    fake.run_until("done", fake.c.start)
    fake.c.install(["aotr"])
    fake.run_until("failed", lambda: fake.c.choose_aotr_file(ZIP))
    assert fake.c.model.failed_step == "aotr-check"
    assert "incomplete" in fake.c.model.error.message
    fake.run_until("done", fake.c.retry)   # runs aotr-install again with the same file, not the setup
    assert fake.c.model.aotr_installed
    assert [c for c in fake.calls() if c.startswith("aotr")] == [f"aotr-install {ZIP}"] * 2


def test_a_failed_check_can_be_followed_by_another_file(fake):
    fake.flag("prefix", "launcher", "aotr-bad")
    fake.run_until("done", fake.c.start)
    fake.c.install(["aotr"])
    fake.run_until("failed", lambda: fake.c.choose_aotr_file("/tmp/old.zip"))
    fake.run_until("waiting", fake.c.choose_another_aotr_file)
    fake.run_until("done", lambda: fake.c.choose_aotr_file("/tmp/new.zip"))
    assert [c for c in fake.calls() if c.startswith("aotr")] == ["aotr-install /tmp/old.zip", "aotr-install /tmp/new.zip"]


def test_back_home_looks_at_the_setup_again(fake):
    fake.flag("prefix", "launcher", "aotr-bad")
    fake.run_until("done", fake.c.start)
    fake.c.install(["aotr"])
    fake.run_until("failed", lambda: fake.c.choose_aotr_file(ZIP))
    fake.run_until("done", fake.c.back_home)
    assert not fake.c.model.aotr_installed


def test_leaving_the_download_page_of_a_first_setup_goes_back_to_the_start_page(fake):
    fake.flag("curl-fixed")
    fake.run_until("waiting", lambda: fake.c.install(["aotr"]))
    fake.run_until("idle", fake.c.back_home)           # nothing is installed yet, so there is no home screen
    assert fake.c.model.environment_ready    # but the environment is ready, and says so
    assert fake.c.model.selection == ("aotr",)


# Shortcuts: a shortcut lives exactly as long as its program, so the wizard asks the script to bring them in line with
# what is installed every time it starts, whichever page comes next. (The script does the writing and the removing.)
def test_a_start_with_something_installed_does_it_before_the_quiet_checks(fake):
    fake.flag("prefix", "launcher")
    fake.run_until("done", fake.c.start)
    assert fake.calls(raw=True) == ["status", "shortcuts", "doctor"]


def test_a_start_with_nothing_installed_does_it_too(fake):
    # The last program to go takes the home screen with it, and its shortcut must not be missed for that.
    fake.run_until("idle", fake.c.start)
    assert fake.calls(raw=True) == ["status", "shortcuts"]


def test_a_program_removed_by_hand_is_noticed_at_the_next_start(fake):
    fake.flag("prefix", "launcher", "aotr")
    fake.run_until("done", fake.c.start)
    os.unlink(os.path.join(fake.dir, "aotr"))          # the player deleted Age of the Ring
    fake.run_until("done", fake.c.start)               # and opens the wizard again
    assert fake.calls(raw=True).count("shortcuts") == 2
    assert not fake.c.model.aotr_installed


def test_the_only_program_removed_by_hand_is_noticed_too(fake):
    fake.flag("prefix", "launcher")
    fake.run_until("done", fake.c.start)
    os.unlink(os.path.join(fake.dir, "launcher"))
    fake.run_until("idle", fake.c.start)               # no home screen any more: the start page
    assert fake.calls(raw=True) == ["status", "shortcuts", "doctor", "status", "shortcuts"]


def test_reset_removes_the_programs_and_then_looks_again_so_the_shortcuts_follow(fake):
    fake.flag("prefix", "launcher", "aotr")
    fake.run_until("done", fake.c.start)
    results = []
    fake.run_until("idle", lambda: fake.c.reset(results.append))
    assert results == [True]
    assert fake.calls(raw=True)[-3:] == ["reset-prefix --yes", "status", "shortcuts"]


def test_a_shortcut_of_a_program_that_is_gone_is_removed_before_the_install_page_comes_up(fake):
    # Clicking the Age of the Ring shortcut after the mod was deleted: the shortcut goes, and the wizard offers it again.
    fake.flag("prefix", "launcher")
    fake.c = fake.controller(offer="aotr")
    fake.run_until("waiting", fake.c.start)
    assert fake.calls(raw=True) == ["status", "shortcuts"]


def test_installing_does_not_add_a_run_of_its_own(fake):
    # The jobs write the shortcuts of what they install themselves, so the wizard asks once per start.
    fake.flag("curl-fixed")
    fake.run_until("idle", fake.c.start)
    fake.run_until("done", lambda: fake.c.install(["launcher"]))
    assert fake.calls(raw=True) == ["status", "shortcuts", "prepare", "launcher-install"]


def test_what_the_script_says_about_it_stays_out_of_the_log(fake):
    fake.flag("prefix", "launcher")
    fake.run_until("done", fake.c.start)
    assert "Shortcuts are up to date" not in fake.c.model.log_text()


def test_a_failing_run_changes_nothing_for_the_player(fake):
    # Shortcuts are optional, so the wizard still starts.
    fake.flag("prefix", "launcher", "shortcuts-fails")
    fake.run_until("done", fake.c.start)
    assert fake.c.model.error is None
    assert not fake.c.checking
    assert fake.calls(raw=True) == ["status", "shortcuts", "doctor"]   # and the checks still run


def test_the_page_waits_for_the_shortcuts_so_its_buttons_never_meet_a_busy_script(fake):
    # Shown first, its buttons would do nothing while the script ran. So the first time the home screen is rendered,
    # the shortcuts have been brought in line and the script is free again.
    fake.flag("prefix", "launcher")
    first = []
    def changed():
        if fake.c.model.state == "done" and not first:
            first.append(("shortcuts" in fake.calls(raw=True), fake.c.runner.busy))
    fake.c._on_change = changed
    fake.run_until("done", fake.c.start)
    assert first == [(True, False)]


def test_the_start_page_waits_too(fake):
    first = []
    def changed():
        if fake.c.model.state == "idle" and not first:
            first.append(("shortcuts" in fake.calls(raw=True), fake.c.runner.busy))
    fake.c._on_change = changed
    fake.run_until("idle", fake.c.start)
    assert first == [(True, False)]


# Graphics
def test_switching_backends_saves_the_choice_and_reports_it(fake):
    fake.run_until("idle", fake.c.start)
    results = []
    fake.run_until("idle", lambda: fake.c.set_graphics("opengl", results.append))
    assert results == [True]
    assert (fake.c.model.graphics, fake.c.model.graphics_label) == ("opengl", "OpenGL (WineD3D)")
    assert "graphics opengl" in fake.calls()


def test_it_is_refused_while_the_setup_or_a_program_runs(fake):
    fake.run_until("idle", fake.c.start)
    calls = list(fake.calls())
    fake.c.model.state = "running"
    assert not fake.c.set_graphics("opengl", lambda ok: None)
    fake.c.model.state = "done"
    fake.c.apps.state["launcher"] = "running"
    assert not fake.c.set_graphics("opengl", lambda ok: None)
    assert fake.calls() == calls


def test_an_unknown_backend_is_not_run(fake):
    fake.run_until("idle", fake.c.start)
    assert not fake.c.set_graphics("direct3d", lambda ok: None)


# Removal: taking one program out of the game environment, from the Programs page.
def test_a_program_goes_and_the_others_stay(fake):
    fake.started()
    assert fake.remove("arena") == [True]
    m = fake.c.model
    assert [m.is_installed(p) for p in ("launcher", "arena", "aotr")] == [True, False, True]
    assert fake.calls() == ["status", "doctor", "remove arena", "status", "doctor"]


@pytest.mark.parametrize("program", ["launcher", "arena", "aotr"])


def test_each_program_can_go_by_itself(fake, program):
    fake.started()
    assert fake.remove(program) == [True]
    gone = [p for p in ("launcher", "arena", "aotr") if not fake.c.model.is_installed(p)]
    assert gone == [program]


def test_the_window_sees_it_as_a_state_of_its_own_and_then_looks_at_the_setup_again(fake):
    fake.started()
    fake.states.clear()
    fake.remove("launcher")
    assert fake.states == ["removing", "checking", "done"]


def test_the_last_program_to_go_leaves_the_start_page_with_a_ready_environment(fake):
    fake.started("prefix", "aotr")
    fake.states.clear()
    fake.run_until("idle", lambda: fake.c.remove("aotr", lambda ok: None))
    assert (fake.c.model.environment_ready, fake.c.model.has_home_screen) == (True, False)
    assert fake.states[-1] == "idle"


def test_a_failed_removal_says_what_went_wrong_and_looks_again(fake):
    fake.started()
    fake.flag("remove-fails")
    seen = []
    fake.run_until("done", lambda: fake.c.remove("launcher", lambda ok: seen.append((ok, fake.c.model.error.message))))
    assert seen == [(False, "Could not remove it")]
    assert fake.c.model.is_installed("launcher")      # nothing was deleted
    assert fake.c.model.error is None                        # and the home screen is not an error page


def test_it_is_refused_while_the_setup_runs_or_a_program_is_open_or_the_script_is_busy(fake):
    fake.started()
    before = fake.calls()
    fake.c.model.state = "running"
    assert not fake.c.remove("arena", lambda ok: None)
    fake.c.model.state = "done"
    fake.c.apps.state["launcher"] = "running"
    assert not fake.c.remove("arena", lambda ok: None)
    fake.c.apps.state["launcher"] = "idle"
    fake.c.run_checks()
    assert not fake.c.remove("arena", lambda ok: None)
    fake.run_until("done", lambda: None)
    assert fake.calls()[len(before):] == ["doctor"]     # only the checks ran


def test_only_a_program_can_be_removed(fake):
    fake.started()
    for name in ("everything", "prefix", "", "BFME2", "launcher-install"):
        assert not fake.c.remove(name, lambda ok: None), name
    assert [c for c in fake.calls() if c.startswith("remove")] == []


def test_the_reason_it_waits_is_told(fake):
    fake.started()
    fake.c.model.state = "removing"
    assert "being removed" in fake.c.blocked_reason()
    fake.c.model.state = "running"
    assert "setup is running" in fake.c.blocked_reason()


def test_a_program_that_was_removed_can_be_installed_again(fake):
    fake.started()
    fake.remove("launcher")
    fake.flag("curl-fixed")
    fake.run_until("done", lambda: fake.c.install(["launcher"]))
    assert fake.c.model.is_installed("launcher")


# Offer: what a shortcut wanted, when the setup could not just start it.
@pytest.mark.parametrize("entry, program", [("launcher", "launcher"), ("arena", "launcher"), ("aotr", "aotr")])


def test_an_entry_for_a_program_that_is_not_installed_prechooses_it_on_the_start_page(fake, entry, program):
    fake.c = fake.controller(offer=entry)
    fake.run_until("idle", fake.c.start)
    assert fake.c.model.selection == (program,)


def test_no_entry_chooses_nothing(fake):
    fake.run_until("idle", fake.c.start)
    assert fake.c.model.selection == ()


def test_the_age_of_the_ring_entry_goes_to_its_download_page_on_a_complete_setup(fake):
    fake.flag("prefix", "launcher")
    fake.c = fake.controller(offer="aotr")
    fake.run_until("waiting", fake.c.start)
    assert fake.calls() == ["status"]   # no system checks first: the download page is already waiting


def test_but_only_once(fake):
    fake.flag("prefix", "launcher")
    fake.c = fake.controller(offer="aotr")
    fake.run_until("waiting", fake.c.start)
    fake.run_until("done", fake.c.back_home)


def test_the_age_of_the_ring_entry_does_nothing_when_it_is_installed(fake):
    fake.flag("prefix", "launcher", "aotr")
    fake.c = fake.controller(offer="aotr")
    fake.run_until("done", fake.c.start)


def test_an_aio_launcher_entry_on_a_complete_setup_just_shows_the_home_screen(fake):
    fake.flag("prefix", "aotr")
    fake.c = fake.controller(offer="launcher")
    fake.run_until("done", fake.c.start)
    assert not fake.c.model.is_installed("launcher")
