"""What the wizard knows about the setup. Fed one line at a time; no GTK, no processes.

States:
  checking   asking the script what is already installed (or re-checking the system)
  idle       nothing running; setup is incomplete (see `paused` for "some of it is done")
  running    install is running
  cancelled  the install stopped cleanly between steps
  failed     a step failed; retrying may help
  blocked    the system itself needs a change (a failed doctor check); the user must act, then recheck
  done       everything is installed
"""
from __future__ import annotations

from dataclasses import dataclass

from . import protocol as p

# (id, title, description). The order is the order `install` runs them in.
STEPS = [
    ("doctor", "Check your system", "Making sure your computer has what the games need."),
    ("runner", "Get Proton", "Downloading the compatibility layer that runs Windows games."),
    ("prefix", "Create the game environment", "Setting up a folder for the launcher and games."),
    ("launcher", "Download the launcher", "Fetching the All-in-One Launcher for managing the games."),
    ("arena", "Download the Arena", "Fetching the Online Arena for playing multiplayer."),
    ("shortcuts", "Add menu shortcuts", "Adding the Launcher, Arena and Workshop Studio to your application menu."),
]
STEP_IDS = [s[0] for s in STEPS]
# The games the script reports (STATUS bfme1 / bfme2 / rotwk), in the order they are shown.
GAMES = [("bfme1", "BFME"), ("bfme2", "BFME 2"), ("rotwk", "Rise of the Witch-king")]
# Checks the home screen does not list: the firewall cannot be seen from the sandbox, and the Troubleshoot page
# has its own "Can't be checked from here" section for it.
HIDDEN_CHECKS = {"firewall"}
MAX_LOG_LINES = 2000


def title_of(step_id: str) -> str:
    return next((t for i, t, _ in STEPS if i == step_id), step_id)


def description_of(step_id: str) -> str:
    return next((d for i, _, d in STEPS if i == step_id), "")


@dataclass(frozen=True)
class Problem:
    """One thing the user has to fix on their system, with the command that fixes it if we know one."""
    message: str
    command: str | None


class SetupModel:
    def __init__(self) -> None:
        self.state = "checking"
        self.log: list[str] = []
        self.installed: dict[str, str] = {}
        self.just_finished = False   # this session ran the setup to the end
        self._reset_run()

    # ------------------------------------------------------------ run bookkeeping
    def _reset_run(self) -> None:
        self.steps = {sid: "pending" for sid in STEP_IDS}
        self.current: str | None = None
        self.progress: int | None = None
        self.checks: dict[str, p.Check] = {}
        self.fixes: dict[str, str] = {}
        self.error: p.Error | None = None
        self.cancel_requested = False
        self._saw_done = False
        self._saw_cancelled = False

    def begin_check(self) -> None:
        """Start asking the script something (status, or a doctor recheck). Forgets old check results."""
        self.state = "checking"
        self.checks.clear()
        self.fixes.clear()
        self.error = None

    def begin_quiet_check(self) -> None:
        """Run the system checks again without leaving the current state (the home screen stays on screen)."""
        self.checks.clear()
        self.fixes.clear()

    def begin_install(self) -> None:
        self._reset_run()
        self.just_finished = False
        self.state = "running"

    def request_cancel(self) -> None:
        if self.state == "running":
            self.cancel_requested = True

    # ---------------------------------------------------------------- lines in
    def feed_line(self, line: str) -> None:
        line = line.rstrip("\r\n")
        self.log.append(line)
        if len(self.log) > MAX_LOG_LINES:
            del self.log[: len(self.log) - MAX_LOG_LINES]
        event = p.parse_line(line)
        if event is not None:
            self._apply(event)

    def _apply(self, e: p.Event) -> None:
        if isinstance(e, p.Step):
            if e.id not in self.steps:
                return
            self.progress = None
            if e.status == "start":
                self.steps[e.id] = "running"
                self.current = e.id
            else:
                self.steps[e.id] = "done" if e.status == "done" else "skipped"
                if self.current == e.id:
                    self.current = None
        elif isinstance(e, p.Progress):
            self.progress = e.percent
        elif isinstance(e, p.Check):
            self.checks[e.id] = e
        elif isinstance(e, p.Fix):
            self.fixes[e.check_id] = e.command
        elif isinstance(e, p.Error):
            self.error = e
            if e.step in self.steps:
                self.steps[e.step] = "failed"
        elif isinstance(e, p.Cancelled):
            self._saw_cancelled = True
        elif isinstance(e, p.Done):
            self._saw_done = True
        elif isinstance(e, p.Status):
            self.installed[e.key] = e.value

    # -------------------------------------------------------------- process out
    def finish_status(self, exit_code: int) -> None:
        """The `status` command ended."""
        if exit_code == 0 and self.installed.get("complete") == "yes":
            self.state = "done"
        else:
            self.state = "idle"

    def finish_check(self, exit_code: int) -> None:
        """A doctor recheck ended. Returns to `blocked` when it still fails; the caller continues the install when it passed."""
        if exit_code != 0:
            self.error = p.Error("doctor", "Your system still needs a change.")
            self.state = "blocked"

    def finish_install(self, exit_code: int) -> None:
        if self.state != "running":
            return
        if self._saw_cancelled:
            self.state = "cancelled"
            self.current = None
        elif self._saw_done and exit_code == 0:
            self.state = "done"
            self.current = None
            self.just_finished = True
        else:
            if self.error is None:
                self.error = p.Error(self.current, f"The setup stopped unexpectedly (exit {exit_code}).")
            self.state = "blocked" if self.error.step == "doctor" else "failed"

    # ------------------------------------------------------------------ queries
    @property
    def paused(self) -> bool:
        """Some, but not all, of the setup is already in place (or an install was stopped)."""
        if self.state == "cancelled":
            return True
        return any(self.installed.get(k) in ("ready", "installed") for k in ("prefix", "launcher", "arena"))

    @property
    def done_count(self) -> int:
        return sum(1 for s in self.steps.values() if s in ("done", "skipped"))

    @property
    def step_number(self) -> int:
        """1-based position of the running step, for "Step 3 of 6"."""
        return STEP_IDS.index(self.current) + 1 if self.current in STEP_IDS else max(1, self.done_count + 1)

    @property
    def last_check_message(self) -> str:
        return next(reversed(self.checks.values())).message if self.checks else ""

    @property
    def problems(self) -> list[Problem]:
        """Failed system checks, each with its fix command when there is one."""
        return [Problem(c.message, self.fixes.get(cid)) for cid, c in self.checks.items() if c.level == "fail"]

    @property
    def games(self) -> list[str]:
        """Names of the installed games. Only known after a status check."""
        return [name for key, name in GAMES if self.installed.get(key) == "installed"]

    @property
    def check_rows(self) -> list[tuple[str, str, str, str | None]]:
        """(id, level, message, fix command) for every check to show, problems first."""
        rows = [
            (cid, c.level, c.message, self.fixes.get(cid))
            for cid, c in self.checks.items() if cid not in HIDDEN_CHECKS
        ]
        order = {"fail": 0, "warn": 1, "ok": 2}
        return sorted(rows, key=lambda r: order[r[1]])

    @property
    def failed_step(self) -> str | None:
        return self.error.step if self.error else None

    def log_text(self, last: int = 400) -> str:
        """The log as text for Copy log. Repeated progress lines collapse to the latest."""
        out: list[str] = []
        for line in self.log[-last:]:
            if line.startswith("@bfme PROGRESS") and out and out[-1].startswith("@bfme PROGRESS"):
                out[-1] = line
            else:
                out.append(line)
        return "\n".join(out)


def games_line(model: SetupModel) -> str:
    """The sentence at the top of the home screen; empty when games are installed."""
    if model.games:
        return ""
    if model.just_finished:
        return "Setup is complete. Open the Launcher to install your games."
    return "No games installed yet. Open the Launcher to install them."
