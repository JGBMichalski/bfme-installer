import unittest

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


class Status(unittest.TestCase):
    def test_complete_setup_goes_straight_to_done(self):
        m = SetupModel()
        feed(m, "@bfme STATUS prefix ready", "@bfme STATUS launcher installed",
             "@bfme STATUS arena installed", "@bfme STATUS complete yes")
        m.finish_status(0)
        self.assertEqual(m.state, "done")

    def test_a_ready_environment_with_nothing_installed_is_not_complete(self):
        m = SetupModel()
        feed(m, "@bfme STATUS prefix ready", "@bfme STATUS launcher missing",
             "@bfme STATUS arena missing", "@bfme STATUS aotr missing", "@bfme STATUS complete no")
        m.finish_status(0)
        self.assertEqual((m.state, m.paused, m.environment_ready), ("idle", False, True))

    def test_nothing_installed_is_a_fresh_start(self):
        m = SetupModel()
        feed(m, "@bfme STATUS prefix missing", "@bfme STATUS launcher missing",
             "@bfme STATUS arena missing", "@bfme STATUS complete no")
        m.finish_status(0)
        self.assertEqual((m.state, m.paused, m.environment_ready), ("idle", False, False))

    def test_a_failing_status_command_is_not_done(self):
        m = SetupModel()
        m.finish_status(1)
        self.assertEqual(m.state, "idle")

    def test_each_program_is_known_from_its_status_line(self):
        m = SetupModel()
        self.assertFalse(any(m.is_installed(p) for p in ("launcher", "arena", "aotr")))
        feed(m, "@bfme STATUS launcher installed", "@bfme STATUS arena missing", "@bfme STATUS aotr installed")
        self.assertEqual([m.is_installed(p) for p in ("launcher", "arena", "aotr")], [True, False, True])
        self.assertTrue(m.aotr_installed)

    def test_leaving_a_plan_lands_on_the_home_screen_only_when_something_is_installed(self):
        m = SetupModel()
        self.assertFalse(m.has_home_screen)
        feed(m, "@bfme STATUS prefix ready", "@bfme STATUS complete no")
        self.assertFalse(m.has_home_screen)   # the environment alone is not a home screen
        feed(m, "@bfme STATUS aotr installed", "@bfme STATUS complete yes")
        self.assertTrue(m.has_home_screen)


class Choice(unittest.TestCase):
    def test_a_choice_is_kept_in_install_order_and_unknown_programs_are_ignored(self):
        m = SetupModel()
        self.assertEqual(m.choose(["aotr", "launcher", "teleport"]), ("launcher", "aotr"))
        self.assertEqual(m.selection, ("launcher", "aotr"))

    def test_choosing_nothing_gives_no_plan(self):
        m = SetupModel()
        self.assertFalse(m.begin_plan([]))
        self.assertFalse(m.begin_plan(["teleport"]))
        self.assertEqual(m.plan, [])

    def test_the_same_choice_after_a_stop_resumes_and_a_different_one_does_not(self):
        m = planned("launcher", "aotr")
        self.assertFalse(m.resumes(["launcher", "aotr"]))   # nothing was stopped
        run_next(m)
        feed(m, "@bfme CANCELLED")
        m.finish_install(130)
        self.assertTrue(m.paused)
        self.assertTrue(m.resumes(["aotr", "launcher"]))    # the order does not matter
        self.assertTrue(m.resumes(["launcher", "aotr", "teleport"]))   # neither does a name that is not a program
        self.assertFalse(m.resumes(["launcher"]))
        self.assertFalse(m.resumes([]))


class Plan(unittest.TestCase):
    def test_the_environment_comes_first_and_the_programs_follow_in_a_fixed_order(self):
        self.assertEqual(plan_for(["launcher"], environment_ready=False), ["environment", "launcher"])
        self.assertEqual(plan_for(["aotr"], environment_ready=False), ["environment", "aotr"])
        self.assertEqual(plan_for(["aotr", "launcher"], environment_ready=False), ["environment", "launcher", "aotr"])

    def test_a_ready_environment_is_not_set_up_again(self):
        self.assertEqual(plan_for(["aotr"], environment_ready=True), ["aotr"])
        self.assertEqual(plan_for(["launcher", "aotr"], environment_ready=True), ["launcher", "aotr"])

    def test_the_launcher_alone_has_the_six_steps_it_always_had(self):
        m = planned("launcher")
        self.assertEqual(m.step_ids, ["doctor", "runner", "prefix", "launcher", "arena", "shortcuts"])
        self.assertEqual(len(m.step_defs), 6)

    def test_age_of_the_ring_alone_does_not_download_the_launcher_or_the_arena(self):
        m = planned("aotr")
        self.assertEqual(m.step_ids, ["doctor", "runner", "prefix", "aotr-download", "aotr-check", "aotr-unpack",
                                      "aotr-install", "aotr-settings"])
        self.assertNotIn("launcher", m.step_ids)
        self.assertNotIn("arena", m.step_ids)

    def test_both_programs_make_one_long_list_of_steps(self):
        m = planned("launcher", "aotr")
        self.assertEqual(len(m.step_defs), 11)
        self.assertEqual(m.step_ids.index("aotr-check") + 1, 8)

    def test_with_the_environment_ready_only_the_programs_are_listed(self):
        self.assertEqual(planned("aotr", environment_ready=True).step_ids[0], "aotr-download")

    def test_a_new_plan_forgets_the_old_one(self):
        m = planned("launcher")
        run_next(m)
        feed(m, "@bfme STEP doctor start", "@bfme ERROR doctor nope")
        m.finish_install(1)
        m.begin_plan(["aotr"])
        self.assertEqual((m.error, m.problems, m.steps["doctor"], m.job, m.just_finished),
                         (None, [], "pending", None, False))
        self.assertEqual(m.plan, ["environment", "aotr"])


class Install(unittest.TestCase):
    def started(self, *programs):
        m = planned(*(programs or ("launcher",)))
        run_next(m)
        return m

    def test_happy_path(self):
        m = self.started()
        feed(m, "@bfme STEP doctor start", "@bfme CHECK cpu ok x86_64 processor", "@bfme STEP doctor done",
             "@bfme STEP runner start", "@bfme PROGRESS 40")
        self.assertEqual((m.current, m.progress, m.step_number), ("runner", 40, 2))
        feed(m, "@bfme STEP runner done")
        self.assertIsNone(m.progress)
        feed(m, "@bfme STEP prefix start", "@bfme STEP prefix done", "@bfme DONE")
        self.assertEqual(m.finish_install(0), "launcher")   # the environment is ready: the launcher job is next
        self.assertEqual(m.state, "running")
        m.begin_job("launcher")
        feed(m, "@bfme STEP launcher skip", "@bfme STEP arena start", "@bfme STEP arena done",
             "@bfme STEP shortcuts start", "@bfme STEP shortcuts done", "@bfme DONE")
        self.assertIsNone(m.finish_install(0))
        self.assertEqual(m.state, "done")
        self.assertEqual(m.done_count, 6)
        self.assertEqual(m.steps["launcher"], "skipped")
        self.assertTrue(m.just_finished)

    def test_failed_step(self):
        m = self.started()
        feed(m, "@bfme STEP runner start", "@bfme ERROR runner Failed (exit 22). See the logs in /x")
        self.assertIsNone(m.finish_install(22))
        self.assertEqual((m.state, m.failed_step, m.steps["runner"], m.job), ("failed", "runner", "failed", "environment"))

    def test_doctor_failure_is_blocked_and_lists_problems(self):
        m = self.started()
        feed(m, "@bfme STEP doctor start", "@bfme CHECK cpu ok x86_64 processor",
             "@bfme CHECK cmd-curl fail curl not found", "@bfme FIX cmd-curl sudo apt install curl",
             "@bfme CHECK bwrap fail bubblewrap cannot start a sandbox",
             "@bfme ERROR doctor Fix the problems above, then run install again.")
        m.finish_install(1)
        self.assertEqual(m.state, "blocked")
        self.assertEqual([(x.message, x.command) for x in m.problems],
                         [("curl not found", "sudo apt install curl"), ("bubblewrap cannot start a sandbox", None)])

    def test_stopping_pauses_the_setup(self):
        m = self.started()
        m.request_cancel()
        self.assertTrue(m.cancel_requested)
        feed(m, "@bfme STEP runner done", "@bfme CANCELLED")
        self.assertIsNone(m.finish_install(130))
        self.assertEqual((m.state, m.paused), ("cancelled", True))

    def test_unexpected_exit_without_an_error_line(self):
        m = self.started()
        feed(m, "@bfme STEP runner start")
        m.finish_install(137)
        self.assertEqual((m.state, m.failed_step), ("failed", "runner"))
        self.assertIn("137", m.error.message)

    def test_done_line_with_bad_exit_code_is_not_done(self):
        m = self.started()
        feed(m, "@bfme DONE")
        self.assertIsNone(m.finish_install(1))
        self.assertEqual(m.state, "failed")

    def test_a_step_the_script_forgot_is_not_left_pending_once_the_job_says_it_is_done(self):
        m = self.started()
        feed(m, "@bfme STEP doctor done", "@bfme DONE")     # runner and prefix were never reported
        self.assertEqual(m.finish_install(0), "launcher")   # no endless loop on the same job
        self.assertEqual([m.steps[s] for s in ("doctor", "runner", "prefix")], ["done"] * 3)

    def test_cancel_only_applies_while_running(self):
        m = SetupModel()
        m.request_cancel()
        self.assertFalse(m.cancel_requested)

    def test_unknown_step_ids_are_ignored(self):
        m = self.started()
        feed(m, "@bfme STEP teleport start")
        self.assertIsNone(m.current)

    def test_a_step_of_a_job_that_is_not_in_the_plan_is_ignored(self):
        m = self.started("launcher")
        feed(m, "@bfme STEP aotr-check start")
        self.assertIsNone(m.current)


class Jobs(unittest.TestCase):
    def test_the_next_job_waits_for_nobody_unless_it_needs_a_file(self):
        m = planned("launcher", "aotr")
        self.assertEqual(run_next(m), "environment")
        feed(m, *ENVIRONMENT_DONE)
        self.assertEqual(m.finish_install(0), "launcher")
        m.begin_job("launcher")
        feed(m, "@bfme STEP launcher done", "@bfme STEP arena done", "@bfme STEP shortcuts skip", "@bfme DONE")
        self.assertEqual(m.finish_install(0), "aotr")
        self.assertEqual((m.state, m.just_finished), ("running", False))   # not finished: Age of the Ring is left

    def test_age_of_the_ring_waits_for_the_player_to_choose_the_file(self):
        m = planned("aotr", environment_ready=True)
        m.wait_for_file()
        self.assertEqual((m.state, m.job, m.current, m.step_number), ("waiting", "aotr", "aotr-download", 1))
        self.assertEqual(m.steps["aotr-download"], "running")
        m.begin_job("aotr")   # the file was chosen
        self.assertEqual((m.state, m.steps["aotr-download"], m.steps["aotr-check"]), ("running", "done", "pending"))

    def test_the_download_step_is_counted_in_the_numbering(self):
        m = planned("launcher", "aotr")
        m.begin_job("aotr")
        feed(m, "@bfme STEP aotr-check start")
        self.assertEqual((m.current, m.step_number), ("aotr-check", 8))

    def test_finishing_the_last_job_finishes_the_setup(self):
        m = planned("aotr", environment_ready=True)
        m.begin_job("aotr")
        feed(m, "@bfme DONE")
        self.assertIsNone(m.finish_install(0))
        self.assertEqual((m.state, m.just_finished), ("done", True))

    def test_a_stopped_age_of_the_ring_install_from_the_setup_pauses_it(self):
        m = planned("aotr", environment_ready=True)
        m.begin_job("aotr")
        feed(m, "@bfme CANCELLED")
        m.finish_install(130)
        self.assertEqual((m.state, m.paused), ("cancelled", True))

    def test_stopping_an_install_started_from_the_home_screen_goes_back_to_the_home_screen(self):
        m = SetupModel()
        feed(m, "@bfme STATUS prefix ready", "@bfme STATUS launcher installed", "@bfme STATUS complete yes")
        m.finish_status(0)
        self.assertEqual(m.state, "done")
        m.begin_plan(["aotr"])
        self.assertEqual(m.plan, ["aotr"])
        m.begin_job("aotr")
        feed(m, "@bfme CANCELLED")
        m.finish_install(130)
        self.assertEqual((m.state, m.paused), ("done", False))

    def test_resume_starts_at_the_first_job_that_is_not_finished(self):
        m = planned("launcher", "aotr")
        run_next(m)
        feed(m, *ENVIRONMENT_DONE)
        m.finish_install(0)
        m.begin_job("launcher")
        feed(m, "@bfme STEP launcher done", "@bfme CANCELLED")
        m.finish_install(130)
        self.assertEqual((m.state, m.first_unfinished_job()), ("cancelled", "launcher"))
        run_next(m)   # the launcher job runs again from its own start; the environment keeps its results
        self.assertEqual((m.steps["doctor"], m.steps["launcher"], m.steps["arena"]), ("done", "pending", "pending"))

    def test_a_cancel_pressed_during_the_last_step_of_a_job_stops_before_the_next_job(self):
        # The script cannot stop inside its last step, so it ends with DONE. The player asked to stop: the plan does.
        m = planned("launcher", "aotr")
        run_next(m)
        m.request_cancel()
        feed(m, *ENVIRONMENT_DONE)
        self.assertIsNone(m.finish_install(0))
        self.assertEqual((m.state, m.paused, m.first_unfinished_job()), ("cancelled", True, "launcher"))

    def test_a_cancel_during_the_last_job_changes_nothing_because_there_is_nothing_left_to_stop(self):
        m = planned("launcher", environment_ready=True)
        run_next(m)
        m.request_cancel()
        feed(m, "@bfme STEP shortcuts done", "@bfme DONE")
        self.assertIsNone(m.finish_install(0))
        self.assertEqual((m.state, m.just_finished), ("done", True))

    def test_a_plan_started_on_the_home_screen_goes_back_there_when_stopped_between_jobs(self):
        m = SetupModel()
        feed(m, "@bfme STATUS prefix ready", "@bfme STATUS aotr installed", "@bfme STATUS complete yes")
        m.finish_status(0)
        m.begin_plan(["launcher", "aotr"])
        run_next(m)
        m.request_cancel()
        feed(m, "@bfme DONE")
        m.finish_install(0)
        self.assertEqual(m.state, "done")

    def test_retry_runs_the_job_that_failed(self):
        m = planned("launcher", "aotr")
        run_next(m)
        feed(m, *ENVIRONMENT_DONE)
        m.finish_install(0)
        m.begin_job("launcher")
        feed(m, "@bfme STEP launcher start", "@bfme ERROR launcher Failed (exit 22).")
        m.finish_install(22)
        self.assertEqual((m.state, m.job, m.failed_step, m.first_unfinished_job()), ("failed", "launcher", "launcher", "launcher"))
        m.begin_job(m.job)
        self.assertEqual((m.state, m.error, m.steps["launcher"]), ("running", None, "pending"))

    def test_the_system_checks_survive_the_jobs_after_the_environment(self):
        m = planned("launcher")
        run_next(m)
        feed(m, "@bfme STEP doctor start", "@bfme CHECK cpu ok x86_64 processor", *ENVIRONMENT_DONE)
        m.finish_install(0)
        m.begin_job("launcher")
        self.assertEqual([r[0] for r in m.check_rows], ["cpu"])   # Troubleshoot still has them


class Recheck(unittest.TestCase):
    def test_still_failing_returns_to_blocked(self):
        m = SetupModel()
        m.begin_check()
        feed(m, "@bfme CHECK cmd-curl fail curl not found")
        m.finish_check(1)
        self.assertEqual(m.state, "blocked")
        self.assertEqual(len(m.problems), 1)

    def test_passing_leaves_the_state_for_the_caller(self):
        m = SetupModel()
        m.begin_check()
        m.finish_check(0)
        self.assertEqual(m.state, "checking")


class Log(unittest.TestCase):
    def test_progress_lines_collapse(self):
        m = SetupModel()
        feed(m, "hello", "@bfme PROGRESS 1", "@bfme PROGRESS 2", "@bfme PROGRESS 3", "bye")
        self.assertEqual(m.log_text(), "hello\n@bfme PROGRESS 3\nbye")

    def test_log_is_bounded(self):
        m = SetupModel()
        for i in range(5000):
            m.feed_line(f"line {i}")
        self.assertEqual(len(m.log), 2000)
        self.assertEqual(m.log[-1], "line 4999")


if __name__ == "__main__":
    unittest.main()
