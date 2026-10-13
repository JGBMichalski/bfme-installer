"""Run scripts/bfme-linux-setup.sh and stream its output. GLib only, no GTK."""
from __future__ import annotations

import os
import shutil
import subprocess
import signal
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402


SETSID = shutil.which("setsid")


def find_script() -> str | None:
    """BFME_SETUP_SCRIPT, then the installed command, then the script in this checkout."""
    override = os.environ.get("BFME_SETUP_SCRIPT")
    if override:
        return override
    installed = shutil.which("bfme-linux-setup")
    if installed:
        return installed
    here = Path(__file__).resolve().parents[2] / "scripts" / "bfme-linux-setup.sh"
    return str(here) if here.is_file() else None


class ScriptRunner:
    """One script process at a time."""

    def __init__(self, script: str) -> None:
        self.script = script
        self._proc: Gio.Subprocess | None = None

    @property
    def busy(self) -> bool:
        return self._proc is not None

    def run(self, args: list[str], on_line: Callable[[str], None], on_exit: Callable[[int], None]) -> None:
        """Start `script --machine <args>`; call on_line per line, then on_exit(code) once."""
        if self._proc is not None:
            raise RuntimeError("a script is already running")
        command = [self.script, "--machine", *args]
        if SETSID:
            # Own process group, so terminate() also stops its downloads and Proton processes.
            command = [SETSID, *command]
        proc = Gio.Subprocess.new(command, Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE)
        self._proc = proc
        stream = Gio.DataInputStream.new(proc.get_stdout_pipe())

        def exited(source: Gio.Subprocess, result: Gio.AsyncResult) -> None:
            source.wait_finish(result)
            code = source.get_exit_status() if source.get_if_exited() else 128 + source.get_term_sig()
            self._proc = None
            on_exit(code)

        def got_line(source: Gio.DataInputStream, result: Gio.AsyncResult) -> None:
            try:
                line, _length = source.read_line_finish_utf8(result)
            except GLib.Error:
                line = None
            if line is None:  # end of output
                proc.wait_async(None, exited)
                return
            on_line(line)
            source.read_line_async(GLib.PRIORITY_DEFAULT, None, got_line)

        stream.read_line_async(GLib.PRIORITY_DEFAULT, None, got_line)

    def request_cancel(self) -> None:
        """Ask the script to stop before its next step (SIGUSR1)."""
        if self._proc is not None:
            self._proc.send_signal(signal.SIGUSR1)

    def terminate(self) -> None:
        """Kill the script and its children (SIGTERM). Partial downloads resume."""
        if self._proc is None:
            return
        pid = int(self._proc.get_identifier())
        try:
            if os.getpgid(pid) == pid:  # setsid made the script a group leader
                os.killpg(pid, signal.SIGTERM)
                return
        except OSError:
            pass
        self._proc.send_signal(signal.SIGTERM)


def _status_lines(script: str, timeout: float) -> list[str]:
    try:
        done = subprocess.run([script, "--machine", "status"], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return []
    return done.stdout.splitlines() if done.returncode == 0 else []


def setup_is_complete(script: str, timeout: float = 20.0) -> bool:
    """Whether the setup is complete. False on any error."""
    return "@bfme STATUS complete yes" in _status_lines(script, timeout)


def app_is_ready(script: str, app: str, timeout: float = 20.0) -> bool:
    """Whether the game environment is ready and this program is installed in it."""
    lines = _status_lines(script, timeout)
    return "@bfme STATUS prefix ready" in lines and f"@bfme STATUS {app} installed" in lines
