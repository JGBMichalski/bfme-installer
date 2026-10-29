from bfme_wizard.model import SetupModel, plan_for


def feed(model, *lines):
    for line in lines:
        model.feed_line(line)


def planned(*programs, environment_ready=False):
    """A model with a plan for these programs, as the start page leaves it: nothing is running yet."""
    m = SetupModel()
    m.installed["prefix"] = "ready" if environment_ready else "missing"
    m.begin_plan(programs)
    return m


def run_next(m):
    """Start the next job of the plan, as the controller does. Returns its name."""
    job = m.first_unfinished_job()
    m.begin_job(job)
    return job


ENVIRONMENT_DONE = ("@bfme STEP doctor done", "@bfme STEP runner done", "@bfme STEP prefix done", "@bfme DONE")


def test_complete_setup_goes_straight_to_done():
    m = SetupModel()
    feed(m, "@bfme STATUS prefix ready", "@bfme STATUS launcher installed",
         "@bfme STATUS arena installed", "@bfme STATUS complete yes")
    m.finish_status(0)
    assert m.state == "done"

def test_a_ready_environment_with_nothing_installed_is_not_complete():
    m = SetupModel()
    feed(m, "@bfme STATUS prefix ready", "@bfme STATUS launcher missing",
         "@bfme STATUS arena missing", "@bfme STATUS aotr missing", "@bfme STATUS complete no")
    m.finish_status(0)
    assert (m.state, m.paused, m.environment_ready) == ("idle", False, True)

def test_nothing_installed_is_a_fresh_start():
    m = SetupModel()
    feed(m, "@bfme STATUS prefix missing", "@bfme STATUS launcher missing",
         "@bfme STATUS arena missing", "@bfme STATUS complete no")
    m.finish_status(0)
    assert (m.state, m.paused, m.environment_ready) == ("idle", False, False)

def test_a_failing_status_command_is_not_done():
    m = SetupModel()
    m.finish_status(1)
    assert m.state == "idle"

def test_each_program_is_known_from_its_status_line():
    m = SetupModel()
    assert not any(m.is_installed(p) for p in ("launcher", "arena", "aotr"))
    feed(m, "@bfme STATUS launcher installed", "@bfme STATUS arena missing", "@bfme STATUS aotr installed")
    assert [m.is_installed(p) for p in ("launcher", "arena", "aotr")] == [True, False, True]
    assert m.aotr_installed

def test_leaving_a_plan_lands_on_the_home_screen_only_when_something_is_installed():
    m = SetupModel()
    assert not m.has_home_screen
    feed(m, "@bfme STATUS prefix ready", "@bfme STATUS complete no")
    assert not m.has_home_screen   # the environment alone is not a home screen
    feed(m, "@bfme STATUS aotr installed", "@bfme STATUS complete yes")
    assert m.has_home_screen


def test_a_choice_is_kept_in_install_order_and_unknown_programs_are_ignored():
    m = SetupModel()
    assert m.choose(["aotr", "launcher", "teleport"]) == ("launcher", "aotr")
    assert m.selection == ("launcher", "aotr")

def test_choosing_nothing_gives_no_plan():
    m = SetupModel()
    assert not m.begin_plan([])
    assert not m.begin_plan(["teleport"])
    assert m.plan == []

def test_the_same_choice_after_a_stop_resumes_and_a_different_one_does_not():
    m = planned("launcher", "aotr")
    assert not m.resumes(["launcher", "aotr"])   # nothing was stopped
    run_next(m)
    feed(m, "@bfme CANCELLED")
    m.finish_install(130)
    assert m.paused
    assert m.resumes(["aotr", "launcher"])    # the order does not matter
    assert m.resumes(["launcher", "aotr", "teleport"])   # neither does a name that is not a program
    assert not m.resumes(["launcher"])
    assert not m.resumes([])


def test_the_environment_comes_first_and_the_programs_follow_in_a_fixed_order():
    assert plan_for(["launcher"], environment_ready=False) == ["environment", "launcher"]
    assert plan_for(["aotr"], environment_ready=False) == ["environment", "aotr"]
    assert plan_for(["aotr", "launcher"], environment_ready=False) == ["environment", "launcher", "aotr"]

def test_a_ready_environment_is_not_set_up_again():
    assert plan_for(["aotr"], environment_ready=True) == ["aotr"]
    assert plan_for(["launcher", "aotr"], environment_ready=True) == ["launcher", "aotr"]

def test_the_aio_launcher_alone_has_the_six_steps_it_always_had():
    m = planned("launcher")
    assert m.step_ids == ["doctor", "runner", "prefix", "launcher", "arena", "shortcuts"]
    assert len(m.step_defs) == 6

def test_the_steps_name_the_aio_launcher_in_full_because_age_of_the_ring_has_a_launcher_too():
    from bfme_wizard.model import description_of, title_of
    assert title_of("launcher") == "Download the AIO Launcher"
    assert description_of("shortcuts") == "Adding the AIO Launcher and the Arena to your application menu."

def test_age_of_the_ring_alone_does_not_download_the_aio_launcher_or_the_arena():
    m = planned("aotr")
    assert m.step_ids == ["doctor", "runner", "prefix", "aotr-download", "aotr-check", "aotr-unpack",
                                  "aotr-install", "aotr-settings"]
    assert "launcher" not in m.step_ids
    assert "arena" not in m.step_ids

def test_both_programs_make_one_long_list_of_steps():
    m = planned("launcher", "aotr")
    assert len(m.step_defs) == 11
    assert m.step_ids.index("aotr-check") + 1 == 8

def test_with_the_environment_ready_only_the_programs_are_listed():
    assert planned("aotr", environment_ready=True).step_ids[0] == "aotr-download"

def test_a_new_plan_forgets_the_old_one():
    m = planned("launcher")
    run_next(m)
    feed(m, "@bfme STEP doctor start", "@bfme ERROR doctor nope")
    m.finish_install(1)
    m.begin_plan(["aotr"])
    assert (m.error, m.problems, m.steps["doctor"], m.job, m.just_finished) == (None, [], "pending", None, False)
    assert m.plan == ["environment", "aotr"]


def started(*programs):
    m = planned(*(programs or ("launcher",)))
    run_next(m)
    return m

def test_happy_path():
    m = started()
    feed(m, "@bfme STEP doctor start", "@bfme CHECK cpu ok x86_64 processor", "@bfme STEP doctor done",
         "@bfme STEP runner start", "@bfme PROGRESS 40")
    assert (m.current, m.progress, m.step_number) == ("runner", 40, 2)
    feed(m, "@bfme STEP runner done")
    assert m.progress is None
    feed(m, "@bfme STEP prefix start", "@bfme STEP prefix done", "@bfme DONE")
    assert m.finish_install(0) == "launcher"   # the environment is ready: the `launcher` job is next
    assert m.state == "running"
    m.begin_job("launcher")
    feed(m, "@bfme STEP launcher skip", "@bfme STEP arena start", "@bfme STEP arena done",
         "@bfme STEP shortcuts start", "@bfme STEP shortcuts done", "@bfme DONE")
    assert m.finish_install(0) is None
    assert m.state == "done"
    assert m.done_count == 6
    assert m.steps["launcher"] == "skipped"
    assert m.just_finished

def test_failed_step():
    m = started()
    feed(m, "@bfme STEP runner start", "@bfme ERROR runner Failed (exit 22). See the logs in /x")
    assert m.finish_install(22) is None
    assert (m.state, m.failed_step, m.steps["runner"], m.job) == ("failed", "runner", "failed", "environment")

def test_doctor_failure_is_blocked_and_lists_problems():
    m = started()
    feed(m, "@bfme STEP doctor start", "@bfme CHECK cpu ok x86_64 processor",
         "@bfme CHECK cmd-curl fail curl not found", "@bfme FIX cmd-curl sudo apt install curl",
         "@bfme CHECK bwrap fail bubblewrap cannot start a sandbox",
         "@bfme ERROR doctor Fix the problems above, then run install again.")
    m.finish_install(1)
    assert m.state == "blocked"
    assert [(x.message, x.command) for x in m.problems] == [("curl not found", "sudo apt install curl"), ("bubblewrap cannot start a sandbox", None)]

def test_stopping_pauses_the_setup():
    m = started()
    m.request_cancel()
    assert m.cancel_requested
    feed(m, "@bfme STEP runner done", "@bfme CANCELLED")
    assert m.finish_install(130) is None
    assert (m.state, m.paused) == ("cancelled", True)

def test_unexpected_exit_without_an_error_line():
    m = started()
    feed(m, "@bfme STEP runner start")
    m.finish_install(137)
    assert (m.state, m.failed_step) == ("failed", "runner")
    assert "137" in m.error.message

def test_done_line_with_bad_exit_code_is_not_done():
    m = started()
    feed(m, "@bfme DONE")
    assert m.finish_install(1) is None
    assert m.state == "failed"

def test_a_step_the_script_forgot_is_not_left_pending_once_the_job_says_it_is_done():
    m = started()
    feed(m, "@bfme STEP doctor done", "@bfme DONE")     # runner and prefix were never reported
    assert m.finish_install(0) == "launcher"   # no endless loop on the same job
    assert [m.steps[s] for s in ("doctor", "runner", "prefix")] == ["done"] * 3

def test_cancel_only_applies_while_running():
    m = SetupModel()
    m.request_cancel()
    assert not m.cancel_requested

def test_unknown_step_ids_are_ignored():
    m = started()
    feed(m, "@bfme STEP teleport start")
    assert m.current is None

def test_a_step_of_a_job_that_is_not_in_the_plan_is_ignored():
    m = started("launcher")
    feed(m, "@bfme STEP aotr-check start")
    assert m.current is None


def test_the_next_job_waits_for_nobody_unless_it_needs_a_file():
    m = planned("launcher", "aotr")
    assert run_next(m) == "environment"
    feed(m, *ENVIRONMENT_DONE)
    assert m.finish_install(0) == "launcher"
    m.begin_job("launcher")
    feed(m, "@bfme STEP launcher done", "@bfme STEP arena done", "@bfme STEP shortcuts skip", "@bfme DONE")
    assert m.finish_install(0) == "aotr"
    assert (m.state, m.just_finished) == ("running", False)   # not finished: Age of the Ring is left

def test_age_of_the_ring_waits_for_the_player_to_choose_the_file():
    m = planned("aotr", environment_ready=True)
    m.wait_for_file()
    assert (m.state, m.job, m.current, m.step_number) == ("waiting", "aotr", "aotr-download", 1)
    assert m.steps["aotr-download"] == "running"
    m.begin_job("aotr")   # the file was chosen
    assert (m.state, m.steps["aotr-download"], m.steps["aotr-check"]) == ("running", "done", "pending")

def test_the_counter_never_runs_past_the_last_step():
    # Between the last step finishing and the script exiting, every step is done: "Step 4 of 3" would show for a moment.
    m = planned("launcher", environment_ready=True)
    run_next(m)
    feed(m, "@bfme STEP launcher done", "@bfme STEP arena done", "@bfme STEP shortcuts done")
    assert (m.state, m.done_count, len(m.step_defs), m.step_number) == ("running", 3, 3, 3)

def test_the_download_step_is_counted_in_the_numbering():
    m = planned("launcher", "aotr")
    m.begin_job("aotr")
    feed(m, "@bfme STEP aotr-check start")
    assert (m.current, m.step_number) == ("aotr-check", 8)

def test_finishing_the_last_job_finishes_the_setup():
    m = planned("aotr", environment_ready=True)
    m.begin_job("aotr")
    feed(m, "@bfme DONE")
    assert m.finish_install(0) is None
    assert (m.state, m.just_finished) == ("done", True)

def test_a_stopped_age_of_the_ring_install_from_the_setup_pauses_it():
    m = planned("aotr", environment_ready=True)
    m.begin_job("aotr")
    feed(m, "@bfme CANCELLED")
    m.finish_install(130)
    assert (m.state, m.paused) == ("cancelled", True)

def test_stopping_an_install_started_from_the_home_screen_goes_back_to_the_home_screen():
    m = SetupModel()
    feed(m, "@bfme STATUS prefix ready", "@bfme STATUS launcher installed", "@bfme STATUS complete yes")
    m.finish_status(0)
    assert m.state == "done"
    m.begin_plan(["aotr"])
    assert m.plan == ["aotr"]
    m.begin_job("aotr")
    feed(m, "@bfme CANCELLED")
    m.finish_install(130)
    assert (m.state, m.paused) == ("done", False)

def test_resume_starts_at_the_first_job_that_is_not_finished():
    m = planned("launcher", "aotr")
    run_next(m)
    feed(m, *ENVIRONMENT_DONE)
    m.finish_install(0)
    m.begin_job("launcher")
    feed(m, "@bfme STEP launcher done", "@bfme CANCELLED")
    m.finish_install(130)
    assert (m.state, m.first_unfinished_job()) == ("cancelled", "launcher")
    run_next(m)   # the `launcher` job runs again from its own start; the environment keeps its results
    assert (m.steps["doctor"], m.steps["launcher"], m.steps["arena"]) == ("done", "pending", "pending")

def test_a_cancel_pressed_during_the_last_step_of_a_job_stops_before_the_next_job():
    # The script cannot stop inside its last step, so it ends with DONE. The player asked to stop: the plan does.
    m = planned("launcher", "aotr")
    run_next(m)
    m.request_cancel()
    feed(m, *ENVIRONMENT_DONE)
    assert m.finish_install(0) is None
    assert (m.state, m.paused, m.first_unfinished_job()) == ("cancelled", True, "launcher")

def test_a_cancel_during_the_last_job_changes_nothing_because_there_is_nothing_left_to_stop():
    m = planned("launcher", environment_ready=True)
    run_next(m)
    m.request_cancel()
    feed(m, "@bfme STEP shortcuts done", "@bfme DONE")
    assert m.finish_install(0) is None
    assert (m.state, m.just_finished) == ("done", True)

def test_a_plan_started_on_the_home_screen_goes_back_there_when_stopped_between_jobs():
    m = SetupModel()
    feed(m, "@bfme STATUS prefix ready", "@bfme STATUS aotr installed", "@bfme STATUS complete yes")
    m.finish_status(0)
    m.begin_plan(["launcher", "aotr"])
    run_next(m)
    m.request_cancel()
    feed(m, "@bfme DONE")
    m.finish_install(0)
    assert m.state == "done"

def test_retry_runs_the_job_that_failed():
    m = planned("launcher", "aotr")
    run_next(m)
    feed(m, *ENVIRONMENT_DONE)
    m.finish_install(0)
    m.begin_job("launcher")
    feed(m, "@bfme STEP launcher start", "@bfme ERROR launcher Failed (exit 22).")
    m.finish_install(22)
    assert (m.state, m.job, m.failed_step, m.first_unfinished_job()) == ("failed", "launcher", "launcher", "launcher")
    m.begin_job(m.job)
    assert (m.state, m.error, m.steps["launcher"]) == ("running", None, "pending")

def test_the_system_checks_survive_the_jobs_after_the_environment():
    m = planned("launcher")
    run_next(m)
    feed(m, "@bfme STEP doctor start", "@bfme CHECK cpu ok x86_64 processor", *ENVIRONMENT_DONE)
    m.finish_install(0)
    m.begin_job("launcher")
    assert [r[0] for r in m.check_rows] == ["cpu"]   # Troubleshoot still has them


def done_setup():
    m = SetupModel()
    feed(m, "@bfme STATUS prefix ready", "@bfme STATUS launcher installed", "@bfme STATUS arena installed",
         "@bfme STATUS complete yes")
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
    feed(m, "@bfme ERROR - an old problem")
    assert m.error is not None
    m.begin_remove("arena")
    assert m.error is None

def test_it_does_not_disturb_the_plan_that_finished_before_it():
    m = done_setup()
    m.begin_plan(["aotr"])
    m.begin_job("aotr")
    feed(m, "@bfme DONE")
    m.finish_install(0)
    assert m.just_finished
    m.begin_remove("arena")
    assert m.just_finished   # the home screen's "Setup is complete" line is the plan's, not the removal's


def test_still_failing_returns_to_blocked():
    m = SetupModel()
    m.begin_check()
    feed(m, "@bfme CHECK cmd-curl fail curl not found")
    m.finish_check(1)
    assert m.state == "blocked"
    assert len(m.problems) == 1

def test_passing_leaves_the_state_for_the_caller():
    m = SetupModel()
    m.begin_check()
    m.finish_check(0)
    assert m.state == "checking"


def test_progress_lines_collapse():
    m = SetupModel()
    feed(m, "hello", "@bfme PROGRESS 1", "@bfme PROGRESS 2", "@bfme PROGRESS 3", "bye")
    assert m.log_text() == "hello\n@bfme PROGRESS 3\nbye"

def test_log_is_bounded():
    m = SetupModel()
    for i in range(5000):
        m.feed_line(f"line {i}")
    assert len(m.log) == 2000
    assert m.log[-1] == "line 4999"

