"""engine.lock: one setup at a time, held with flock on .setup.lock."""

import os
import signal
import subprocess
import time

import pytest

from bfme_wizard.engine.errors import SetupError
from bfme_wizard.engine.lock import SetupLock
from bfme_wizard.engine.paths import Paths


@pytest.fixture
def paths(tmp_path):
    return Paths(tmp_path / "data")


def test_a_second_setup_is_refused_while_the_first_runs(paths):
    with SetupLock(paths, {}):
        with pytest.raises(SetupError, match="^Another setup is already running. Wait for it to finish.$"):
            with SetupLock(paths, {}):
                pass


def test_in_the_flatpak_it_says_how_to_end_a_stuck_one(paths):
    with SetupLock(paths, {}), pytest.raises(SetupError, match="run: flatpak kill com.example.App$"):
        with SetupLock(paths, {"FLATPAK_ID": "com.example.App"}):
            pass


def test_it_is_released_after_the_block_also_when_it_fails(paths):
    with pytest.raises(RuntimeError), SetupLock(paths, {}):
        raise RuntimeError("boom")

    with SetupLock(paths, {}):
        pass


def test_flock_is_kept_out_while_the_engine_holds_it(paths):
    with SetupLock(paths, {}):
        done = subprocess.run(["flock", "-n", str(paths.base / ".setup.lock"), "true"], capture_output=True, timeout=60)

    assert done.returncode == 1


def test_the_engine_is_kept_out_while_flock_holds_it(paths):
    # Another process holding the lock with flock(1) on the same file.
    paths.base.mkdir(parents=True)
    holder = subprocess.Popen(
        ["flock", str(paths.base / ".setup.lock"), "sh", "-c", "echo held; sleep 30"],
        stdout=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )

    try:
        assert holder.stdout.readline() == "held\n"

        with pytest.raises(SetupError), SetupLock(paths, {}):
            pass
    finally:
        # The lock stays held while any process of the group has the file open.
        os.killpg(holder.pid, signal.SIGKILL)
        holder.wait()

    # flock has exited, but its child may still be closing the file for a moment.
    for _attempt in range(50):
        try:
            with SetupLock(paths, {}):
                return
        except SetupError:
            time.sleep(0.05)

    pytest.fail("the lock was never released")
