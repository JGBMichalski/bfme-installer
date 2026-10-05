import unittest

from bfme_wizard.model import SetupModel


def feed(model, *lines):
    for line in lines:
        model.feed_line(line)


class Status(unittest.TestCase):
    def test_complete_setup_goes_straight_to_done(self):
        m = SetupModel()
        feed(m, "@bfme STATUS prefix ready", "@bfme STATUS launcher installed",
             "@bfme STATUS arena installed", "@bfme STATUS complete yes")
        m.finish_status(0)
        self.assertEqual(m.state, "done")

    def test_partial_setup_is_paused(self):
        m = SetupModel()
        feed(m, "@bfme STATUS prefix ready", "@bfme STATUS launcher missing",
             "@bfme STATUS arena missing", "@bfme STATUS complete no")
        m.finish_status(0)
        self.assertEqual((m.state, m.paused), ("idle", True))

    def test_nothing_installed_is_a_fresh_start(self):
        m = SetupModel()
        feed(m, "@bfme STATUS prefix missing", "@bfme STATUS launcher missing",
             "@bfme STATUS arena missing", "@bfme STATUS complete no")
        m.finish_status(0)
        self.assertEqual((m.state, m.paused), ("idle", False))

    def test_a_failing_status_command_is_not_done(self):
        m = SetupModel()
        m.finish_status(1)
        self.assertEqual(m.state, "idle")


class Install(unittest.TestCase):
    def started(self):
        m = SetupModel()
        m.begin_install()
        return m

    def test_happy_path(self):
        m = self.started()
        feed(m, "@bfme STEP doctor start", "@bfme CHECK cpu ok x86_64 processor", "@bfme STEP doctor done",
             "@bfme STEP runner start", "@bfme PROGRESS 40")
        self.assertEqual((m.current, m.progress, m.step_number), ("runner", 40, 2))
        feed(m, "@bfme STEP runner done")
        self.assertIsNone(m.progress)
        feed(m, "@bfme STEP prefix start", "@bfme STEP prefix done", "@bfme STEP launcher skip",
             "@bfme STEP arena start", "@bfme STEP arena done", "@bfme STEP shortcuts start",
             "@bfme STEP shortcuts done", "@bfme DONE")
        m.finish_install(0)
        self.assertEqual(m.state, "done")
        self.assertEqual(m.done_count, 6)
        self.assertEqual(m.steps["launcher"], "skipped")

    def test_failed_step(self):
        m = self.started()
        feed(m, "@bfme STEP arena start", "@bfme ERROR arena Failed (exit 22). See the logs in /x")
        m.finish_install(22)
        self.assertEqual((m.state, m.failed_step, m.steps["arena"]), ("failed", "arena", "failed"))

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

    def test_cancelled(self):
        m = self.started()
        m.request_cancel()
        self.assertTrue(m.cancel_requested)
        feed(m, "@bfme STEP launcher done", "@bfme CANCELLED")
        m.finish_install(130)
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
        m.finish_install(1)
        self.assertEqual(m.state, "failed")

    def test_a_new_install_forgets_the_old_run(self):
        m = self.started()
        feed(m, "@bfme STEP arena start", "@bfme ERROR arena nope")
        m.finish_install(1)
        m.begin_install()
        self.assertEqual((m.state, m.error, m.steps["arena"], m.problems), ("running", None, "pending", []))

    def test_cancel_only_applies_while_running(self):
        m = SetupModel()
        m.request_cancel()
        self.assertFalse(m.cancel_requested)

    def test_unknown_step_ids_are_ignored(self):
        m = self.started()
        feed(m, "@bfme STEP teleport start")
        self.assertIsNone(m.current)


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
