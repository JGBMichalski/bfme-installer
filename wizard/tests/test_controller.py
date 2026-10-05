import os
import stat
import tempfile
import unittest

from gi.repository import GLib

from bfme_wizard.controller import Controller
from bfme_wizard.runner import ScriptRunner

# A fake setup script. FAKE_MODE selects what it does; state lives in $FAKE_DIR.
FAKE = r"""#!/usr/bin/env bash
shift  # --machine
cmd="$1"
case "$cmd" in
  status)
    if [ -f "$FAKE_DIR/installed" ]; then
      echo "@bfme STATUS prefix ready"; echo "@bfme STATUS launcher installed"
      echo "@bfme STATUS arena installed"; echo "@bfme STATUS complete yes"
    else
      echo "@bfme STATUS prefix missing"; echo "@bfme STATUS complete no"
    fi ;;
  doctor)
    if [ -f "$FAKE_DIR/curl-fixed" ]; then echo "@bfme CHECK cmd-curl ok curl found"; exit 0; fi
    echo "@bfme CHECK cmd-curl fail curl not found"; echo "@bfme FIX cmd-curl sudo apt install curl"; exit 1 ;;
  install)
    echo "@bfme STEP doctor start"
    if [ ! -f "$FAKE_DIR/curl-fixed" ]; then
      echo "@bfme CHECK cmd-curl fail curl not found"; echo "@bfme FIX cmd-curl sudo apt install curl"
      echo "@bfme ERROR doctor Fix the problems above, then run install again."; exit 1
    fi
    echo "@bfme STEP doctor done"
    echo "@bfme STEP runner start"
    if [ -f "$FAKE_DIR/flaky" ] && [ ! -f "$FAKE_DIR/flaky-used" ]; then
      touch "$FAKE_DIR/flaky-used"; echo "@bfme ERROR runner Failed (exit 22)."; exit 22; fi
    echo "@bfme PROGRESS 50"; echo "@bfme STEP runner done"; echo "@bfme DONE"; touch "$FAKE_DIR/installed" ;;
esac
"""


class Flow(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.environ["FAKE_DIR"] = self.dir
        script = os.path.join(self.dir, "fake.sh")
        with open(script, "w") as f:
            f.write(FAKE)
        os.chmod(script, os.stat(script).st_mode | stat.S_IXUSR)
        self.loop = GLib.MainLoop()
        self.states = []
        self.c = Controller(ScriptRunner(script), self.changed)

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

    def flag(self, name):
        open(os.path.join(self.dir, name), "w").close()

    def test_fresh_start_then_install(self):
        self.run_until("idle", self.c.start)
        self.assertFalse(self.c.model.paused)
        self.flag("curl-fixed")
        self.run_until("done", self.c.install)
        self.assertEqual(self.c.model.done_count, 2)

    def test_already_installed_starts_on_done(self):
        self.flag("installed")
        self.run_until("done", self.c.start)

    def test_blocked_then_recheck_continues_the_install(self):
        self.run_until("blocked", self.c.install)
        self.assertEqual([(p.message, p.command) for p in self.c.model.problems],
                         [("curl not found", "sudo apt install curl")])
        self.run_until("blocked", self.c.recheck)  # still not fixed
        self.assertEqual(len(self.c.model.problems), 1)
        self.flag("curl-fixed")
        self.run_until("done", self.c.recheck)  # fixed: the recheck carries on into the install
        self.assertEqual(self.c.model.problems, [])

    def test_failure_then_retry(self):
        self.flag("curl-fixed")
        self.flag("flaky")
        self.run_until("failed", self.c.install)
        self.assertEqual(self.c.model.failed_step, "runner")
        self.assertIn("Failed (exit 22).", self.c.model.log_text())
        self.run_until("done", self.c.retry)
        self.assertIsNone(self.c.model.error)

    def test_a_second_install_while_running_is_ignored(self):
        self.flag("curl-fixed")
        self.c.install()
        self.c.install()  # ignored: the first is still running
        self.c.start()    # also ignored
        GLib.timeout_add(5000, self.loop.quit)
        GLib.timeout_add(50, lambda: (self.loop.quit(), False)[1] if self.c.model.state == "done" else True)
        self.loop.run()
        self.assertEqual(self.c.model.state, "done")


if __name__ == "__main__":
    unittest.main()
