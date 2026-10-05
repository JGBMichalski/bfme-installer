import unittest

from bfme_wizard.protocol import (
    Cancelled, Check, Done, Error, Fix, Progress, Status, Step, Warn, parse_line,
)


class ParseLine(unittest.TestCase):
    def test_ordinary_text_is_not_an_event(self):
        self.assertIsNone(parse_line("Downloading Proton"))
        self.assertIsNone(parse_line("  [ok]   curl found"))
        self.assertIsNone(parse_line(""))

    def test_steps(self):
        self.assertEqual(parse_line("@bfme STEP runner start"), Step("runner", "start"))
        self.assertEqual(parse_line("@bfme STEP launcher skip\n"), Step("launcher", "skip"))
        self.assertIsNone(parse_line("@bfme STEP runner paused"))

    def test_progress_is_clamped(self):
        self.assertEqual(parse_line("@bfme PROGRESS 42"), Progress(42))
        self.assertEqual(parse_line("@bfme PROGRESS 140"), Progress(100))
        self.assertIsNone(parse_line("@bfme PROGRESS lots"))

    def test_check_keeps_the_whole_message(self):
        self.assertEqual(
            parse_line("@bfme CHECK disk warn less than 30 GB free where the data goes (/x)"),
            Check("disk", "warn", "less than 30 GB free where the data goes (/x)"),
        )
        self.assertIsNone(parse_line("@bfme CHECK disk maybe nope"))

    def test_fix_keeps_the_whole_command(self):
        self.assertEqual(
            parse_line("@bfme FIX cmd-curl sudo apt install curl"),
            Fix("cmd-curl", "sudo apt install curl"),
        )

    def test_error_with_and_without_a_step(self):
        self.assertEqual(parse_line("@bfme ERROR arena Failed (exit 22)."), Error("arena", "Failed (exit 22)."))
        self.assertEqual(parse_line("@bfme ERROR - Unknown command"), Error(None, "Unknown command"))

    def test_bare_events_and_status(self):
        self.assertEqual(parse_line("@bfme DONE"), Done())
        self.assertEqual(parse_line("@bfme CANCELLED"), Cancelled())
        self.assertEqual(parse_line("@bfme WARN be careful"), Warn("be careful"))
        self.assertEqual(parse_line("@bfme STATUS complete yes"), Status("complete", "yes"))

    def test_unknown_and_malformed_lines_are_ignored(self):
        self.assertIsNone(parse_line("@bfme FUTURE thing"))
        self.assertIsNone(parse_line("@bfme STEP only-one-word"))
        self.assertIsNone(parse_line("@bfme"))


if __name__ == "__main__":
    unittest.main()
