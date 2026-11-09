import time

import pytest

from bfme_wizard.control.apps import AppLauncher
from bfme_wizard.control.model import SetupModel, speed_text
from bfme_wizard.control.plan import Plan
from bfme_wizard.control.steps import STEPS
from bfme_wizard.engine.events import Cancelled, Check, Done, Error, Fix, Log, Progress, Speed, Step, Warn
from tests.helpers import status, wait_for


def feed(model, *events):
    for event in events:
        model.feed_event(event)


def planned(*programs, environment_ready=False):
    """A model with a plan for these programs, as the start page leaves it: nothing is running yet."""
    m = SetupModel()
    m.status = status(prefix_ready=environment_ready)
    m.begin_plan(programs)
    return m


def run_next(m):
    """Start the next job of the plan, as the controller does. Returns its name."""
    job = m.plan.first_unfinished_job()
    m.begin_job(job)
    return job


ENVIRONMENT_DONE = (Step("doctor", "done"), Step("runner", "done"), Step("prefix", "done"), Done())


def test_complete_setup_goes_straight_to_done():
    m = SetupModel()
    feed(m, status("aio-launcher", "arena", prefix_ready=True))
    m.finish_status(0)
    assert m.state == "done"


def test_a_ready_environment_with_nothing_installed_is_not_complete():
    m = SetupModel()
    feed(m, status(prefix_ready=True))
    m.finish_status(0)
    assert (m.state, m.paused, m.environment_ready) == ("idle", False, True)


def test_nothing_installed_is_a_fresh_start():
    m = SetupModel()
    feed(m, status())
    m.finish_status(0)
    assert (m.state, m.paused, m.environment_ready) == ("idle", False, False)


def test_a_failing_status_command_is_not_done():
    m = SetupModel()
    m.finish_status(1)
    assert m.state == "idle"


def test_each_program_is_known_from_the_status():
    m = SetupModel()
    assert not any(m.is_installed(p) for p in ("aio-launcher", "arena", "aotr"))
    feed(m, status("aio-launcher", "aotr"))
    assert [m.is_installed(p) for p in ("aio-launcher", "arena", "aotr")] == [True, False, True]
    assert m.is_installed("aotr")


def test_leaving_a_plan_lands_on_the_home_screen_only_when_something_is_installed():
    m = SetupModel()
    assert not m.has_home_screen
    feed(m, status(prefix_ready=True))
    assert not m.has_home_screen  # the environment alone is not a home screen
    feed(m, status("aotr", prefix_ready=True))
    assert m.has_home_screen


def test_a_choice_is_kept_in_install_order_and_unknown_programs_are_ignored():
    m = SetupModel()
    assert m.plan.choose(["aotr", "aio-launcher", "teleport"]) == ("aio-launcher", "aotr")
    assert m.plan.selection == ("aio-launcher", "aotr")


def test_choosing_nothing_gives_no_plan():
    m = SetupModel()
    assert not m.begin_plan([])
    assert not m.begin_plan(["teleport"])
    assert m.plan.jobs == []


def test_the_same_choice_after_a_stop_resumes_and_a_different_one_does_not():
    m = planned("aio-launcher", "aotr")
    assert not m.resumes(["aio-launcher", "aotr"])  # nothing was stopped
    run_next(m)
    feed(m, Cancelled())
    m.finish_install(130)
    assert m.paused
    assert m.resumes(["aotr", "aio-launcher"])  # the order does not matter
    assert m.resumes(["aio-launcher", "aotr", "teleport"])  # neither does a name that is not a program
    assert not m.resumes(["aio-launcher"])
    assert not m.resumes([])


def test_the_environment_comes_first_and_the_programs_follow_in_a_fixed_order():
    assert Plan().jobs_for(["aio-launcher"], environment_ready=False) == ["environment", "aio-launcher"]
    assert Plan().jobs_for(["aotr"], environment_ready=False) == ["environment", "aotr"]
    assert Plan().jobs_for(["aotr", "aio-launcher"], environment_ready=False) == ["environment", "aio-launcher", "aotr"]


def test_a_ready_environment_is_not_set_up_again():
    assert Plan().jobs_for(["aotr"], environment_ready=True) == ["aotr"]
    assert Plan().jobs_for(["aio-launcher", "aotr"], environment_ready=True) == ["aio-launcher", "aotr"]


def test_the_aio_launcher_alone_has_the_six_steps_it_always_had():
    m = planned("aio-launcher")
    assert m.plan.step_ids == ["doctor", "runner", "prefix", "aio-launcher", "arena", "shortcuts"]
    assert len(m.plan.step_defs) == 6


def test_the_steps_name_the_aio_launcher_in_full_because_age_of_the_ring_has_a_aio_launcher_too():
    assert STEPS.title_of("aio-launcher") == "Download the AIO Launcher"
    assert STEPS.description_of("shortcuts") == "Adding the AIO Launcher and the Arena to your application menu."


def test_age_of_the_ring_alone_does_not_download_the_aio_launcher_or_the_arena():
    m = planned("aotr")
    assert m.plan.step_ids == [
        "doctor",
        "runner",
        "prefix",
        "aotr-download",
        "aotr-unpack",
        "aotr-install",
        "aotr-settings",
    ]
    assert "aio-launcher" not in m.plan.step_ids
    assert "arena" not in m.plan.step_ids


def test_both_programs_make_one_long_list_of_steps():
    m = planned("aio-launcher", "aotr")
    assert len(m.plan.step_defs) == 10
    assert m.plan.step_ids.index("aotr-unpack") + 1 == 8


def test_with_the_environment_ready_only_the_programs_are_listed():
    assert planned("aotr", environment_ready=True).plan.step_ids[0] == "aotr-download"


def test_a_new_plan_forgets_the_old_one():
    m = planned("aio-launcher")
    run_next(m)
    feed(m, Step("doctor", "start"), Error("doctor", "nope"))
    m.finish_install(1)
    m.begin_plan(["aotr"])
    assert (m.error, m.problems, m.plan.steps["doctor"], m.job, m.plan.just_finished) == (
        None,
        [],
        "pending",
        None,
        False,
    )
    assert m.plan.jobs == ["environment", "aotr"]


def started(*programs):
    m = planned(*(programs or ("aio-launcher",)))
    run_next(m)
    return m


def test_happy_path():
    m = started()
    feed(
        m,
        Step("doctor", "start"),
        Check("cpu", "ok", "x86_64 processor"),
        Step("doctor", "done"),
        Step("runner", "start"),
        Progress(40),
    )
    assert (m.current, m.progress, m.step_number) == ("runner", 40, 2)
    feed(m, Step("runner", "done"))
    assert m.progress is None
    feed(m, Step("prefix", "start"), Step("prefix", "done"), Done())
    assert m.finish_install(0) == "aio-launcher"  # the environment is ready: the `aio-launcher` job is next
    assert m.state == "running"
    m.begin_job("aio-launcher")
    feed(
        m,
        Step("aio-launcher", "skip"),
        Step("arena", "start"),
        Step("arena", "done"),
        Step("shortcuts", "start"),
        Step("shortcuts", "done"),
        Done(),
    )
    assert m.finish_install(0) is None
    assert m.state == "done"
    assert m.plan.done_count == 6
    assert m.plan.steps["aio-launcher"] == "skipped"
    assert m.plan.just_finished


def test_failed_step():
    m = started()
    feed(m, Step("runner", "start"), Error("runner", "Failed (exit 22). See the logs in /x"))
    assert m.finish_install(22) is None
    assert (m.state, m.failed_step, m.plan.steps["runner"], m.job) == ("failed", "runner", "failed", "environment")


def test_doctor_failure_is_blocked_and_lists_problems():
    m = started()
    feed(
        m,
        Step("doctor", "start"),
        Check("cpu", "ok", "x86_64 processor"),
        Check("cmd-curl", "fail", "curl not found"),
        Fix("cmd-curl", "sudo apt install curl"),
        Check("bwrap", "fail", "bubblewrap cannot start a sandbox"),
        Error("doctor", "Fix the problems above, then run install again."),
    )
    m.finish_install(1)
    assert m.state == "blocked"
    assert [(x.message, x.command) for x in m.problems] == [
        ("curl not found", "sudo apt install curl"),
        ("bubblewrap cannot start a sandbox", None),
    ]


def test_stopping_pauses_the_setup():
    m = started()
    m.request_cancel()
    assert m.cancel_requested
    feed(m, Step("runner", "done"), Cancelled())
    assert m.finish_install(130) is None
    assert (m.state, m.paused) == ("cancelled", True)


def test_unexpected_exit_without_an_error_line():
    m = started()
    feed(m, Step("runner", "start"))
    m.finish_install(137)
    assert (m.state, m.failed_step) == ("failed", "runner")
    assert "137" in m.error.message


def test_done_line_with_bad_exit_code_is_not_done():
    m = started()
    feed(m, Done())
    assert m.finish_install(1) is None
    assert m.state == "failed"


def test_a_step_the_script_forgot_is_not_left_pending_once_the_job_says_it_is_done():
    m = started()
    feed(m, Step("doctor", "done"), Done())  # runner and prefix were never reported
    assert m.finish_install(0) == "aio-launcher"  # no endless loop on the same job
    assert [m.plan.steps[s] for s in ("doctor", "runner", "prefix")] == ["done"] * 3


def test_cancel_only_applies_while_running():
    m = SetupModel()
    m.request_cancel()
    assert not m.cancel_requested


def test_unknown_step_ids_are_ignored():
    m = started()
    feed(m, Step("teleport", "start"))
    assert m.current is None


def test_a_step_of_a_job_that_is_not_in_the_plan_is_ignored():
    m = started("aio-launcher")
    feed(m, Step("aotr-unpack", "start"))
    assert m.current is None


def test_the_next_job_waits_for_nobody():
    m = planned("aio-launcher", "aotr")
    assert run_next(m) == "environment"
    feed(m, *ENVIRONMENT_DONE)
    assert m.finish_install(0) == "aio-launcher"
    m.begin_job("aio-launcher")
    feed(m, Step("aio-launcher", "done"), Step("arena", "done"), Step("shortcuts", "skip"), Done())
    assert m.finish_install(0) == "aotr"
    assert (m.state, m.plan.just_finished) == ("running", False)  # not finished: Age of the Ring is left


def test_the_counter_never_runs_past_the_last_step():
    # Between the last step finishing and the script exiting, every step is done: "Step 4 of 3" would show for a moment.
    m = planned("aio-launcher", environment_ready=True)
    run_next(m)
    feed(m, Step("aio-launcher", "done"), Step("arena", "done"), Step("shortcuts", "done"))
    assert (m.state, m.plan.done_count, len(m.plan.step_defs), m.step_number) == ("running", 3, 3, 3)


def test_the_download_step_is_counted_in_the_numbering():
    m = planned("aio-launcher", "aotr")
    m.begin_job("aotr")
    feed(m, Step("aotr-unpack", "start"))
    assert (m.current, m.step_number) == ("aotr-unpack", 8)


def test_finishing_the_last_job_finishes_the_setup():
    m = planned("aotr", environment_ready=True)
    m.begin_job("aotr")
    feed(m, Done())
    assert m.finish_install(0) is None
    assert (m.state, m.plan.just_finished) == ("done", True)


def test_a_stopped_age_of_the_ring_install_from_the_setup_pauses_it():
    m = planned("aotr", environment_ready=True)
    m.begin_job("aotr")
    feed(m, Cancelled())
    m.finish_install(130)
    assert (m.state, m.paused) == ("cancelled", True)


def test_stopping_an_install_started_from_the_home_screen_goes_back_to_the_home_screen():
    m = SetupModel()
    feed(m, status("aio-launcher", prefix_ready=True))
    m.finish_status(0)
    assert m.state == "done"
    m.begin_plan(["aotr"])
    assert m.plan.jobs == ["aotr"]
    m.begin_job("aotr")
    feed(m, Cancelled())
    m.finish_install(130)
    assert (m.state, m.paused) == ("done", False)


def test_resume_starts_at_the_first_job_that_is_not_finished():
    m = planned("aio-launcher", "aotr")
    run_next(m)
    feed(m, *ENVIRONMENT_DONE)
    m.finish_install(0)
    m.begin_job("aio-launcher")
    feed(m, Step("aio-launcher", "done"), Cancelled())
    m.finish_install(130)
    assert (m.state, m.plan.first_unfinished_job()) == ("cancelled", "aio-launcher")
    run_next(m)  # the `aio-launcher` job runs again from its own start; the environment keeps its results
    assert (m.plan.steps["doctor"], m.plan.steps["aio-launcher"], m.plan.steps["arena"]) == (
        "done",
        "pending",
        "pending",
    )


def test_a_cancel_pressed_during_the_last_step_of_a_job_stops_before_the_next_job():
    # The script cannot stop inside its last step, so it ends with DONE. The player asked to stop: the plan does.
    m = planned("aio-launcher", "aotr")
    run_next(m)
    m.request_cancel()
    feed(m, *ENVIRONMENT_DONE)
    assert m.finish_install(0) is None
    assert (m.state, m.paused, m.plan.first_unfinished_job()) == ("cancelled", True, "aio-launcher")


def test_a_cancel_during_the_last_job_changes_nothing_because_there_is_nothing_left_to_stop():
    m = planned("aio-launcher", environment_ready=True)
    run_next(m)
    m.request_cancel()
    feed(m, Step("shortcuts", "done"), Done())
    assert m.finish_install(0) is None
    assert (m.state, m.plan.just_finished) == ("done", True)


def test_a_plan_started_on_the_home_screen_goes_back_there_when_stopped_between_jobs():
    m = SetupModel()
    feed(m, status("aotr", prefix_ready=True))
    m.finish_status(0)
    m.begin_plan(["aio-launcher", "aotr"])
    run_next(m)
    m.request_cancel()
    feed(m, Done())
    m.finish_install(0)
    assert m.state == "done"


def test_retry_runs_the_job_that_failed():
    m = planned("aio-launcher", "aotr")
    run_next(m)
    feed(m, *ENVIRONMENT_DONE)
    m.finish_install(0)
    m.begin_job("aio-launcher")
    feed(m, Step("aio-launcher", "start"), Error("aio-launcher", "Failed (exit 22)."))
    m.finish_install(22)
    assert (m.state, m.job, m.failed_step, m.plan.first_unfinished_job()) == (
        "failed",
        "aio-launcher",
        "aio-launcher",
        "aio-launcher",
    )
    m.begin_job(m.job)
    assert (m.state, m.error, m.plan.steps["aio-launcher"]) == ("running", None, "pending")


def test_the_system_checks_survive_the_jobs_after_the_environment():
    m = planned("aio-launcher")
    run_next(m)
    feed(m, Step("doctor", "start"), Check("cpu", "ok", "x86_64 processor"), *ENVIRONMENT_DONE)
    m.finish_install(0)
    m.begin_job("aio-launcher")
    assert [r[0] for r in m.check_rows] == ["cpu"]  # Troubleshoot still has them


def done_setup():
    m = SetupModel()
    feed(m, status("aio-launcher", "arena", prefix_ready=True))
    m.finish_status(0)
    return m


def test_removing_is_a_state_of_its_own_and_remembers_the_program():
    m = done_setup()
    assert m.removing is None
    m.begin_remove("arena")
    assert (m.state, m.removing) == ("removing", "arena")


def test_looking_at_the_setup_again_ends_it():
    m = done_setup()
    m.begin_remove("arena")
    m.begin_check()
    assert (m.state, m.removing) == ("checking", None)


def test_a_removal_starts_without_the_last_error():
    m = done_setup()
    feed(m, Error(None, "an old problem"))
    assert m.error is not None
    m.begin_remove("arena")
    assert m.error is None


def test_it_does_not_disturb_the_plan_that_finished_before_it():
    m = done_setup()
    m.begin_plan(["aotr"])
    m.begin_job("aotr")
    feed(m, Done())
    m.finish_install(0)
    assert m.plan.just_finished
    m.begin_remove("arena")
    assert m.plan.just_finished  # the home screen's "Setup is complete" line is the plan's, not the removal's


def test_still_failing_returns_to_blocked():
    m = SetupModel()
    m.begin_check()
    feed(m, Check("cmd-curl", "fail", "curl not found"))
    m.finish_check(1)
    assert m.state == "blocked"
    assert len(m.problems) == 1


def test_passing_leaves_the_state_for_the_caller():
    m = SetupModel()
    m.begin_check()
    m.finish_check(0)
    assert m.state == "checking"


def test_the_log_holds_the_log_lines_and_the_warnings_and_nothing_else():
    m = SetupModel()
    feed(m, Log("hello"), Progress(1), Step("doctor", "start"), Warn("careful"), status(prefix_ready=True), Log("bye"))
    assert m.log_text() == "hello\nWARNING: careful\nbye"


def test_log_is_bounded():
    m = SetupModel()
    for i in range(5000):
        m.feed_event(Log(f"line {i}"))
    assert len(m.log) == 2000
    assert m.log[-1] == "line 4999"


def test_a_download_speed_is_shown_until_the_step_changes():
    m = planned("aio-launcher", environment_ready=True)
    run_next(m)
    feed(m, Step("aio-launcher", "start"), Progress(40), Speed(3_200_000))
    assert (m.progress, m.speed) == (40, 3_200_000)

    feed(m, Step("aio-launcher", "done"))
    assert (m.progress, m.speed) == (None, None)


@pytest.mark.parametrize(
    "bytes_per_second, text",
    [
        (3_200_000, "3.2 MB/s"),
        (1_000_000, "1.0 MB/s"),
        (640_000, "640 KB/s"),
        (999, "0 KB/s"),
    ],
)
def test_speed_text(bytes_per_second, text):
    assert speed_text(bytes_per_second) == text


# The model: games, graphics and checks


def test_installed_games_in_a_fixed_order():
    m = SetupModel()
    feed(m, status("rotwk", "bfme2"))
    assert m.games == ["BFME 2", "Rise of the Witch-king"]


def test_no_games_before_a_status_check():
    assert SetupModel().games == []


def test_just_finished_only_after_this_session_ran_the_setup():
    m = SetupModel()
    feed(m, status(complete=True))
    m.finish_status(0)
    assert (m.state, m.plan.just_finished) == ("done", False)
    m.begin_plan(["aio-launcher"])
    m.begin_job("environment")
    feed(m, Done())
    assert m.finish_install(0) == "aio-launcher"
    assert not m.plan.just_finished  # the AIO Launcher is still to come
    m.begin_job("aio-launcher")
    feed(m, Done())
    m.finish_install(0)
    assert m.plan.just_finished
    m.begin_plan(["aio-launcher"])
    assert not m.plan.just_finished


def test_the_backend_comes_from_the_status_and_defaults_to_vulkan():
    m = SetupModel()
    assert (m.graphics, m.graphics_label) == ("vulkan", "Vulkan (DXVK)")
    feed(m, status(graphics="opengl"))
    assert (m.graphics, m.graphics_label) == ("opengl", "OpenGL (WineD3D)")


def test_rows_hide_the_firewall_and_list_problems_first():
    m = SetupModel()
    feed(
        m,
        Check("cpu", "ok", "x86_64 processor"),
        Check("firewall", "warn", "firewall is active"),
        Check("flatpak-32bit", "fail", "the 32-bit parts are missing"),
        Fix("flatpak-32bit", "flatpak install --user flathub X"),
        Check("disk", "warn", "low disk"),
        Check("curl", "ok", "curl found"),
    )
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

LAUNCHER = ("aio-launcher", "arena")


def games(installed, finished=False):
    m = SetupModel()
    m.status = installed
    m.plan.just_finished = finished
    return m.games_line


def test_wording():
    assert games(status(*LAUNCHER, "bfme2")) == ""
    assert games(status(*LAUNCHER, "bfme1", "bfme2", "rotwk")) == ""
    assert games(status(*LAUNCHER)) == "No games installed yet. Open the AIO Launcher to install them."
    assert games(status(*LAUNCHER), finished=True) == "Setup is complete. Open the AIO Launcher to install your games."
    assert games(status(*LAUNCHER, "bfme2"), finished=True) == ""


def test_nothing_about_games_for_someone_who_did_not_install_the_aio_launcher():
    # Age of the Ring has its own copies of the games, and there is no AIO Launcher to open to install the others.
    assert games(status("aotr")) == ""
    assert games(status("aotr"), finished=True) == ""


def test_age_of_the_rings_own_copies_are_not_the_games_the_aio_launcher_installs():
    assert (
        games(status(*LAUNCHER, "aotr", "aotr-games"))
        == "No games installed yet. Open the AIO Launcher to install them."
    )


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
    apps.start("aio-launcher")
    apps.start("aio-launcher")
    apps.start("arena")
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
