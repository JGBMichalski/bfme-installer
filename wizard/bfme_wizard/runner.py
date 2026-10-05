"""Run scripts/bfme-linux-setup.sh and stream its output. Uses GLib/Gio only (no GTK), so it can be tested headless."""
from __future__ import annotations

import os
import shutil
import signal
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402


def find_script() -> str | None:
    """BFME_SETUP_SCRIPT, then the installed command (the Flatpak), then the script next to this checkout."""
    override = os.environ.get("BFME_SETUP_SCRIPT")
    if override:
        return override
    installed = shutil.which("bfme-linux-setup")
    if installed:
        return installed
    here = Path(__file__).resolve().parents[2] / "scripts" / "bfme-linux-setup.sh"
    return str(here) if here.is_file() else None


class ScriptRunner:
    """One script process at a time. Output arrives line by line on the GLib main loop."""

    def __init__(self, script: str) -> None:
        self.script = script
        self._proc: Gio.Subprocess | None = None

    @property
    def busy(self) -> bool:
        return self._proc is not None

    def run(self, args: list[str], on_line: Callable[[str], None], on_exit: Callable[[int], None]) -> None:
        """Start `script --machine <args>`. Calls on_line per output line, then on_exit(code) once."""
        if self._proc is not None:
            raise RuntimeError("a script is already running")
        proc = Gio.Subprocess.new(
            [self.script, "--machine", *args],
            Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE,
        )
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
            if line is None:  # end of output: the process is finishing
                proc.wait_async(None, exited)
                return
            on_line(line)
            source.read_line_async(GLib.PRIORITY_DEFAULT, None, got_line)

        stream.read_line_async(GLib.PRIORITY_DEFAULT, None, got_line)

    def request_cancel(self) -> None:
        """Ask the running install to stop cleanly before its next step (SIGUSR1)."""
        if self._proc is not None:
            self._proc.send_signal(signal.SIGUSR1)

    def terminate(self) -> None:
        """Stop the running script at once (SIGTERM). Partial downloads resume next time."""
        if self._proc is not None:
            self._proc.send_signal(signal.SIGTERM)

    def spawn_detached(self, args: list[str]) -> None:
        """Start the launcher or the Arena and let it run on its own."""
        Gio.Subprocess.new([self.script, *args], Gio.SubprocessFlags.NONE)
