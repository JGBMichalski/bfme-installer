"""What the wizard knows about the setup.

The player's choice on the start page becomes a plan: jobs run one after the other, each one command of the setup script.

  environment   prepare            doctor, runner, prefix                       left out when it is already ready
  launcher      launcher-install   launcher, arena, shortcuts
  aotr          aotr-install       aotr-check, aotr-unpack, aotr-install, aotr-settings, once the player has
                                   downloaded the file and chosen it (aotr-download: a step the script never reports)

States:
  checking   asking the script what is already installed (or re-checking the system)
  idle       nothing running; the setup is not complete: the start page
  running    a job of the plan is running
  waiting    the plan needs the player: download Age of the Ring from ModDB and choose the file
  removing   a program is being taken out of the game environment
  cancelled  the plan stopped cleanly between steps
  failed     a step failed; retrying may help
  blocked    the system itself needs a change (a failed system check); the user must act, then recheck
  done       the setup is complete: the home screen
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from . import protocol as p

# Start page choices, in install order. The Arena is not one: it comes with the AIO Launcher.
PROGRAMS = ("launcher", "aotr")
# Everything that can be opened, and removed again.
ALL_PROGRAMS = ("launcher", "arena", "aotr")

JOB_STEPS: dict[str, list[tuple[str, str, str]]] = {
    "environment": [
        ("doctor", "Check your system", "Making sure your computer has what the games need."),
        ("runner", "Get Proton", "Downloading the compatibility layer that runs Windows games."),
        ("prefix", "Create the game environment", "Setting up a private folder for the launchers and games."),
    ],
    "launcher": [
        ("launcher", "Download the AIO Launcher", "Fetching the All-in-One Launcher for managing the games."),
        ("arena", "Download the Arena", "Fetching the Online Arena for playing multiplayer."),
        ("shortcuts", "Add menu shortcuts", "Adding the AIO Launcher and the Arena to your application menu."),
    ],
    "aotr": [
        ("aotr-download", "Download Age of the Ring", "Getting the file from ModDB, then choosing it here."),
        ("aotr-check", "Check the download", "Making sure the file is complete and there is room for it."),
        ("aotr-unpack", "Unpack the download", "Extracting the installer files. This takes a few minutes."),
        ("aotr-install", "Install Age of the Ring", "Copying the game and the mod. This can take an hour."),
        ("aotr-settings", "Finish up", "Removing the temporary files."),
    ],
}
# Steps the player does. The script never reports them.
PLAYER_STEPS = {"aotr-download"}
GAMES = [("bfme1", "BFME"), ("bfme2", "BFME 2"), ("rotwk", "Rise of the Witch-king")]
# The sandbox cannot see the firewall. Troubleshoot has a section for it.
HIDDEN_CHECKS = {"firewall"}
MAX_LOG_LINES = 2000


def title_of(step_id: str) -> str:
    return next((t for steps in JOB_STEPS.values() for i, t, _ in steps if i == step_id), step_id)


def description_of(step_id: str) -> str:
    return next((d for steps in JOB_STEPS.values() for i, _, d in steps if i == step_id), "")


def _in_order(programs: Iterable[str]) -> tuple[str, ...]:
    """Known programs only, in install order."""
    wanted = set(programs)
    return tuple(program for program in PROGRAMS if program in wanted)


def plan_for(programs: Iterable[str], environment_ready: bool) -> list[str]:
    """The jobs these programs need. Empty when none is wanted, since the game environment alone is not a choice."""
    chosen = list(_in_order(programs))
    if not chosen:
        return []
    return chosen if environment_ready else ["environment", *chosen]


@dataclass(frozen=True)
class Problem:
    """A failed system check and its fix command, if there is one."""
    message: str
    command: str | None


class SetupModel:
    def __init__(self) -> None:
        self.state = "checking"
        self.log: list[str] = []
        self.installed: dict[str, str] = {}
        self.selection: tuple[str, ...] = ()   # what the player chose to install (see PROGRAMS)
        self.plan: list[str] = []              # the jobs that choice takes
        self.job: str | None = None            # the job that is running, waiting for the player, or failed
        self.started_from_home = False         # the plan began on the home screen: stopping it goes back there
        self.just_finished = False             # this session ran a plan to the end
        self.removing: str | None = None       # the program being removed, while the state is "removing"
        self.steps: dict[str, str] = {}
        self._reset_run()

    @property
    def step_defs(self) -> list[tuple[str, str, str]]:
        """Every step of the plan. "Step 3 of 8" counts the whole plan."""
        return [step for job in self.plan for step in JOB_STEPS[job]]

    @property
    def step_ids(self) -> list[str]:
        return [s[0] for s in self.step_defs]

    def choose(self, programs: Iterable[str]) -> tuple[str, ...]:
        """Remember the chosen programs, in install order."""
        self.selection = _in_order(programs)
        return self.selection

    def resumes(self, programs: Iterable[str]) -> bool:
        """True when the same choice continues a stopped plan."""
        return self.paused and bool(self.selection) and _in_order(programs) == self.selection

    def begin_plan(self, programs: Iterable[str] | None = None) -> bool:
        """Plan the choice (the last one if `programs` is None). False when nothing is chosen."""
        chosen = self.choose(programs) if programs is not None else self.selection
        plan = plan_for(chosen, self.environment_ready)
        if not plan:
            return False
        self.plan = plan
        self.steps = {sid: "pending" for sid in self.step_ids}
        self.job = None
        self.started_from_home = self.state == "done"
        self.just_finished = False
        self._reset_run(keep_checks=True)
        return True

    def first_unfinished_job(self) -> str | None:
        """Where a resume starts. None when the plan is done."""
        for job in self.plan:
            if any(self.steps[sid] not in ("done", "skipped") for sid, _t, _d in JOB_STEPS[job]):
                return job
        return None

    def begin_job(self, name: str) -> None:
        """A job starts. Its steps start over."""
        self.job = name
        for sid, _t, _d in JOB_STEPS[name]:
            self.steps[sid] = "done" if sid in PLAYER_STEPS else "pending"
        # Only the environment job runs system checks. Troubleshoot keeps showing the last ones.
        self._reset_run(keep_checks=name != "environment")
        self.state = "running"

    def wait_for_file(self) -> None:
        """The plan waits for the player to download and choose the Age of the Ring file."""
        self.job = "aotr"
        self._reset_run(keep_checks=True)
        self.steps["aotr-download"] = "running"
        self.current = "aotr-download"
        self.state = "waiting"

    def _reset_run(self, keep_checks: bool = False) -> None:
        """Forget what the last script run reported. Step results stay."""
        self.current: str | None = None
        self.progress: int | None = None
        if not keep_checks:
            self.checks: dict[str, p.Check] = {}
            self.fixes: dict[str, str] = {}
        self.error: p.Error | None = None
        self.cancel_requested = False
        self._saw_done = False
        self._saw_cancelled = False

    def begin_check(self) -> None:
        """Start a status or recheck question. Drops old check results."""
        self.state = "checking"
        self.removing = None
        self.checks.clear()
        self.fixes.clear()
        self.error = None

    def begin_remove(self, program: str) -> None:
        """A program is being removed. The plan that finished before stays as it was."""
        self.state = "removing"
        self.removing = program
        self.error = None

    def begin_quiet_check(self) -> None:
        """Run the system checks again and keep the current state."""
        self.checks.clear()
        self.fixes.clear()

    def request_cancel(self) -> None:
        if self.state == "running":
            self.cancel_requested = True

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

    def finish_status(self, exit_code: int) -> None:
        if exit_code == 0 and self.installed.get("complete") == "yes":
            self.state = "done"
        else:
            self.state = "idle"

    def finish_check(self, exit_code: int) -> None:
        """A recheck ended. Back to `blocked` if it still fails."""
        if exit_code != 0:
            self.error = p.Error("doctor", "Your system still needs a change.")
            self.state = "blocked"

    def finish_install(self, exit_code: int) -> str | None:
        """A job ended. Returns the next job, or None when the plan is over or stopped (see `state`)."""
        if self.state != "running":
            return None
        if self._saw_cancelled:
            # An install started from the home screen returns there. A setup pauses.
            self.state = "done" if self.started_from_home else "cancelled"
            self.current = None
            return None
        if self._saw_done and exit_code == 0:
            self.current = None
            # DONE means the job finished, so unreported steps are done too.
            for sid, _t, _d in JOB_STEPS[self.job]:
                if self.steps[sid] in ("pending", "running"):
                    self.steps[sid] = "done"
            following = self.first_unfinished_job()
            if following is None:
                self.state = "done"
                self.just_finished = True
            elif self.cancel_requested:
                # The script cannot stop inside its last step. Stop before the next job.
                self.state = "done" if self.started_from_home else "cancelled"
                return None
            return following
        if self.error is None:
            self.error = p.Error(self.current, f"The setup stopped unexpectedly (exit {exit_code}).")
        self.state = "blocked" if self.error.step == "doctor" else "failed"
        return None

    @property
    def paused(self) -> bool:
        """A stopped setup. The start page offers to resume it."""
        return self.state == "cancelled"

    @property
    def environment_ready(self) -> bool:
        """Known only after a status check."""
        return self.installed.get("prefix") == "ready"

    @property
    def has_home_screen(self) -> bool:
        """Something is installed, so leaving the plan lands on the home screen. Known only after a status check."""
        return self.installed.get("complete") == "yes"

    @property
    def done_count(self) -> int:
        return sum(1 for s in self.steps.values() if s in ("done", "skipped"))

    @property
    def step_number(self) -> int:
        """1-based position of the running step in the plan."""
        ids = self.step_ids
        if self.current in ids:
            return ids.index(self.current) + 1
        return max(1, min(self.done_count + 1, len(ids)))   # not past the last step, while the script is finishing up

    @property
    def last_check_message(self) -> str:
        return next(reversed(self.checks.values())).message if self.checks else ""

    @property
    def problems(self) -> list[Problem]:
        """Failed system checks."""
        return [Problem(c.message, self.fixes.get(cid)) for cid, c in self.checks.items() if c.level == "fail"]

    def is_installed(self, program: str) -> bool:
        """Known only after a status check."""
        return self.installed.get(program) == "installed"

    @property
    def aotr_installed(self) -> bool:
        return self.is_installed("aotr")

    @property
    def games(self) -> list[str]:
        """Installed game names. Known only after a status check."""
        return [name for key, name in GAMES if self.installed.get(key) == "installed"]

    @property
    def check_rows(self) -> list[tuple[str, str, str, str | None]]:
        """(id, level, message, fix command) per shown check, problems first."""
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
        """The log for Copy log. Repeated progress lines collapse to the latest."""
        out: list[str] = []
        for line in self.log[-last:]:
            if line.startswith("@bfme PROGRESS") and out and out[-1].startswith("@bfme PROGRESS"):
                out[-1] = line
            else:
                out.append(line)
        return "\n".join(out)


def games_line(model: SetupModel) -> str:
    """The home screen's top sentence. Empty when games are installed or there is no AIO Launcher."""
    if model.games or not model.is_installed("launcher"):
        return ""
    if model.just_finished:
        return "Setup is complete. Open the AIO Launcher to install your games."
    return "No games installed yet. Open the AIO Launcher to install them."
