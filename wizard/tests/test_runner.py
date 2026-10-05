import os
import stat
import tempfile
import unittest

from gi.repository import GLib

from bfme_wizard.runner import ScriptRunner

FAKE = r"""#!/usr/bin/env bash
# fake setup script: first argument is --machine, second the command
trap 'echo "@bfme CANCELLED"; exit 130' USR1
case "$2" in
  ok)     echo "plain text"; echo "@bfme STEP doctor start"; echo "@bfme STEP doctor done"; echo "@bfme DONE" ;;
  bad)    echo "@bfme ERROR runner nope"; exit 7 ;;
  slow)   echo "@bfme STEP runner start"; for i in $(seq 1 100); do sleep 0.1; done ;;
  noeol)  printf 'no newline at the end' ;;
esac
"""


def run_and_collect(runner, args, timeout_ms=10000, before_exit=None):
    loop = GLib.MainLoop()
    lines, codes = [], []
    runner.run(args, lines.append, lambda c: (codes.append(c), loop.quit()))
    if before_exit:
        GLib.timeout_add(before_exit[0], lambda: (before_exit[1](), False)[1])
    GLib.timeout_add(timeout_ms, loop.quit)
    loop.run()
    return lines, codes


class Runner(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.script = os.path.join(d, "fake.sh")
        with open(self.script, "w") as f:
            f.write(FAKE)
        os.chmod(self.script, os.stat(self.script).st_mode | stat.S_IXUSR)
        self.runner = ScriptRunner(self.script)

    def test_streams_lines_then_reports_the_exit_code(self):
        lines, codes = run_and_collect(self.runner, ["ok"])
        self.assertEqual(lines, ["plain text", "@bfme STEP doctor start", "@bfme STEP doctor done", "@bfme DONE"])
        self.assertEqual(codes, [0])
        self.assertFalse(self.runner.busy)

    def test_nonzero_exit_code(self):
        lines, codes = run_and_collect(self.runner, ["bad"])
        self.assertEqual((lines, codes), (["@bfme ERROR runner nope"], [7]))

    def test_last_line_without_a_newline_is_still_delivered(self):
        lines, _ = run_and_collect(self.runner, ["noeol"])
        self.assertEqual(lines, ["no newline at the end"])

    def test_cancel_sends_sigusr1(self):
        lines, codes = run_and_collect(self.runner, ["slow"], before_exit=(500, self.runner.request_cancel))
        self.assertIn("@bfme CANCELLED", lines)
        self.assertEqual(codes, [130])

    def test_only_one_script_at_a_time(self):
        loop = GLib.MainLoop()
        self.runner.run(["slow"], lambda _l: None, lambda _c: loop.quit())
        with self.assertRaises(RuntimeError):
            self.runner.run(["ok"], lambda _l: None, lambda _c: None)
        self.runner.request_cancel()
        GLib.timeout_add(5000, loop.quit)
        loop.run()


if __name__ == "__main__":
    unittest.main()
