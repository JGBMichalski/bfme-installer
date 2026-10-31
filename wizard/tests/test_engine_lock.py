"""engine.lock: one setup at a time, held with flock on .setup.lock."""
import os
import signal
import subprocess

import pytest

from bfme_wizard.engine.errors import SetupError
from bfme_wizard.engine.lock import setup_lock
from bfme_wizard.engine.paths import Paths


@pytest.fixture
def paths(tmp_path):
    return Paths(tmp_path / "data")


def test_a_second_setup_is_refused_while_the_first_runs(paths):
    with setup_lock(paths, {}):
        with pytest.raises(SetupError, match="^Another setup is already running. Wait for it to finish.$"):
            with setup_lock(paths, {}):
                pass


def test_in_the_flatpak_it_says_how_to_end_a_stuck_one(paths):
    with setup_lock(paths, {}):
        with pytest.raises(SetupError, match="run: flatpak kill com.example.App$"):
            with setup_lock(paths, {"FLATPAK_ID": "com.example.App"}):
                pass


def test_it_is_released_after_the_block_also_when_it_fails(paths):
    with pytest.raises(RuntimeError):
        with setup_lock(paths, {}):
            raise RuntimeError("boom")

    with setup_lock(paths, {}):
        pass


def test_flock_is_kept_out_while_the_engine_holds_it(paths):
    with setup_lock(paths, {}):
        done = subprocess.run(["flock", "-n", str(paths.base / ".setup.lock"), "true"], capture_output=True, timeout=60)

    assert done.returncode == 1


def test_the_engine_is_kept_out_while_flock_holds_it(paths):
    # Another process holding the lock with flock(1) on the same file.
    paths.base.mkdir(parents=True)
    holder = subprocess.Popen(["flock", str(paths.base / ".setup.lock"), "sh", "-c", "echo held; sleep 30"],
                              stdout=subprocess.PIPE, text=True, start_new_session=True)

    try:
        assert holder.stdout.readline() == "held\n"

        with pytest.raises(SetupError):
            with setup_lock(paths, {}):
                pass
    finally:
        # The lock stays held while any process of the group has the file open.
        os.killpg(holder.pid, signal.SIGKILL)
        holder.wait()

    with setup_lock(paths, {}):
        pass
