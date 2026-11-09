"""What the wizard knows about the setup.

The player's choice on the start page becomes a plan: jobs run one after the other, each one job of engine/jobs.py.

  environment   prepare                doctor, runner, prefix                   left out when it is already ready
  aio-launcher  install aio-launcher   aio-launcher, arena, shortcuts
  aotr          install aotr           aotr-download, aotr-unpack, aotr-install, aotr-settings. The job
                                       downloads the file from ModDB itself

States:
  checking   asking the setup what is already installed (or re-checking the system)
  idle       nothing running; the setup is not complete: the start page
  running    a job of the plan is running
  removing   a program is being taken out of the game environment
  cancelled  the plan stopped cleanly between steps
  failed     a step failed; retrying may help
  blocked    the system itself needs a change (a failed system check); the user must act, then recheck
  done       the setup is complete: the home screen
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .engine import events
from .engine import programs as engine_programs
from .engine.games import GAMES
from .engine.jobs import PrepareJob


def _job_steps() -> dict[str, list[tuple[str, str, str]]]:
    """The steps of each job: the game environment's, then each program's that has a job of its own."""
    steps = {PrepareJob.KEY: list(PrepareJob.STEPS)}

    for program in engine_programs.EVERY_PROGRAM:
        if program.steps:
            steps[program.key] = list(program.steps)

    return steps


JOB_STEPS = _job_steps()


def _keys(only_choices: bool = False, tools: bool = False) -> tuple[str, ...]:
    keys = []

    for program in engine_programs.EVERY_PROGRAM:
        if program.is_tool != tools:
            continue

        if only_choices and program.choice is None:
            continue

        keys.append(program.key)

    return tuple(keys)


PROGRAMS = _keys(only_choices=True)  # Start page choices, in install order.
ALL_PROGRAMS = _keys()  # Everything that can be opened, and removed again.
TOOLS = _keys(tools=True)  # Extra programs of the Tools page. Each installs as a job of its own, from the home screen.


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
    return tuple(program for program in (*PROGRAMS, *TOOLS) if program in wanted)


def plan_for(programs: Iterable[str], environment_ready: bool) -> list[str]:
    """The jobs these programs need. Empty when none is wanted, since the game environment alone is not a choice."""
    chosen = list(_in_order(programs))
    if not chosen:
        return []
    return chosen if environment_ready else [PrepareJob.KEY, *chosen]


@dataclass(frozen=True)
class Problem:
    """A failed system check and its fix command, if there is one."""

    message: str
    command: str | None


class SetupModel:
    def __init__(self) -> None:
        self.state = "checking"
        self.log: list[str] = []
        self.status: events.SetupStatus | None = None  # known after a status check
        self.selection: tuple[str, ...] = ()  # what the player chose to install (see PROGRAMS)
        self.plan: list[str] = []  # the jobs that choice takes
        self.job: str | None = None  # the job that is running, or failed
        self.started_from_home = False  # the plan began on the home screen: stopping it goes back there
        self.just_finished = False  # this session ran a plan to the end
        self.removing: str | None = None  # the program being removed, while the state is "removing"
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
            self.steps[sid] = "pending"
        # Only the environment job runs system checks. Troubleshoot keeps showing the last ones.
        self._reset_run(keep_checks=name != PrepareJob.KEY)
        self.state = "running"

    def _reset_run(self, keep_checks: bool = False) -> None:
        """Forget what the last script run reported. Step results stay."""
        self.current: str | None = None
        self.progress: int | None = None
        self.speed: int | None = None  # bytes per second of the download that is running
        if not keep_checks:
            self.checks: dict[str, events.Check] = {}
            self.fixes: dict[str, str] = {}
        self.error: events.Error | None = None
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
        """Request cancellation of the current job, if it is running."""
        if self.state == "running":
            self.cancel_requested = True

    def feed_event(self, event: events.Event) -> None:
        """What a job reported. Its log lines and warnings go into the log the player can copy."""
        if isinstance(event, events.Log):
            self._add_to_log(event.text)
        elif isinstance(event, events.Warn):
            self._add_to_log(f"WARNING: {event.message}")
        self._apply(event)

    def _add_to_log(self, text: str) -> None:
        """Add a line to the job log, keeping it within the maximum number of lines."""
        self.log.append(text)
        if len(self.log) > MAX_LOG_LINES:
            del self.log[: len(self.log) - MAX_LOG_LINES]

    def _apply(self, e: events.Event) -> None:
        """Apply an event to the model, updating its state accordingly."""
        if isinstance(e, events.Step):
            if e.id not in self.steps:
                return
            self.progress = None
            self.speed = None
            if e.status == "start":
                self.steps[e.id] = "running"
                self.current = e.id
            else:
                self.steps[e.id] = "done" if e.status == "done" else "skipped"
                if self.current == e.id:
                    self.current = None
        elif isinstance(e, events.Progress):
            self.progress = e.percent
        elif isinstance(e, events.Speed):
            self.speed = e.bytes_per_second
        elif isinstance(e, events.Check):
            self.checks[e.id] = e
        elif isinstance(e, events.Fix):
            self.fixes[e.check_id] = e.command
        elif isinstance(e, events.Error):
            self.error = e
            if e.step in self.steps:
                self.steps[e.step] = "failed"
        elif isinstance(e, events.Cancelled):
            self._saw_cancelled = True
        elif isinstance(e, events.Done):
            self._saw_done = True
        elif isinstance(e, events.SetupStatus):
            self.status = e

    def finish_status(self, exit_code: int) -> None:
        """Handle the completion of the status job."""
        if exit_code == 0 and self.known.complete:
            self.state = "done"
        else:
            self.state = "idle"

    def finish_check(self, exit_code: int) -> None:
        """Handle the completion of a recheck job. Back to `blocked` if it still fails."""
        if exit_code != 0:
            self.error = events.Error("doctor", "Your system still needs a change.")
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
                # A job cannot stop inside its last step. Stop before the next job.
                self.state = "done" if self.started_from_home else "cancelled"
                return None
            return following
        if self.error is None:
            self.error = events.Error(self.current, f"The setup stopped unexpectedly (exit {exit_code}).")
        self.state = "blocked" if self.error.step == "doctor" else "failed"
        return None

    @property
    def paused(self) -> bool:
        """A stopped setup. The start page offers to resume it."""
        return self.state == "cancelled"

    @property
    def known(self) -> events.SetupStatus:
        """The last status reported, or an empty one before the first status check."""
        if self.status is None:
            return events.SetupStatus()

        return self.status

    @property
    def environment_ready(self) -> bool:
        return self.known.prefix_ready

    @property
    def graphics(self) -> str:
        """The graphics backend: `vulkan` (DXVK) or `opengl` (WineD3D)."""
        return self.known.graphics

    @property
    def graphics_label(self) -> str:
        """Human-readable label for the graphics backend."""
        return "OpenGL (WineD3D)" if self.graphics == "opengl" else "Vulkan (DXVK)"

    @property
    def has_home_screen(self) -> bool:
        """Something is installed, so leaving the plan lands on the home screen. Known only after a status check."""
        return self.known.complete

    @property
    def done_count(self) -> int:
        """Number of steps that are done or skipped."""
        return sum(1 for s in self.steps.values() if s in ("done", "skipped"))

    @property
    def step_number(self) -> int:
        """1-based position of the running step in the plan. Returns the next step if the current one is not found."""
        ids = self.step_ids
        if self.current in ids:
            return ids.index(self.current) + 1
        return max(1, min(self.done_count + 1, len(ids)))  # not past the last step, while the script is finishing up

    @property
    def last_check_message(self) -> str:
        """Message of the last system check, if any."""
        return next(reversed(self.checks.values())).message if self.checks else ""

    @property
    def problems(self) -> list[Problem]:
        """List of failed system checks as Problem instances."""
        return [Problem(c.message, self.fixes.get(cid)) for cid, c in self.checks.items() if c.level == "fail"]

    def is_installed(self, program: str) -> bool:
        """Known only after a status check."""
        return program in self.known.programs

    @property
    def games(self) -> list[str]:
        """Return a list of installed game names. Known only after a status check."""
        names = []

        for game in GAMES:
            if game.key in self.known.games:
                names.append(game.name)

        return names

    @property
    def check_rows(self) -> list[tuple[str, str, str, str | None]]:
        """Return a list of shown checks as (id, level, message, fix command) tuples, problems first."""
        rows = [
            (cid, c.level, c.message, self.fixes.get(cid)) for cid, c in self.checks.items() if cid not in HIDDEN_CHECKS
        ]
        order = {"fail": 0, "warn": 1, "ok": 2}
        return sorted(rows, key=lambda r: order[r[1]])

    @property
    def failed_step(self) -> str | None:
        """Return the step that failed, if any."""
        return self.error.step if self.error else None

    @property
    def games_line(self) -> str:
        """The home screen's top sentence. Empty when games are installed or there is no AIO Launcher."""
        has_installer = False

        for program in engine_programs.EVERY_PROGRAM:
            if program.installs_games and self.is_installed(program.key):
                has_installer = True

        if not has_installer:
            return ""

        for game in GAMES:
            if game.key in self.known.games and engine_programs.program(game.installed_by).installs_games:
                return ""

        if self.just_finished:
            return "Setup is complete. Open the AIO Launcher to install your games."

        return "No games installed yet. Open the AIO Launcher to install them."

    def log_text(self, last: int = 400) -> str:
        """Return the last `last` lines of the job log for the Copy log feature."""
        return "\n".join(self.log[-last:])


def speed_text(bytes_per_second: int) -> str:
    """ "3.2 MB/s" or "640 KB/s"."""
    if bytes_per_second >= 1_000_000:
        return f"{bytes_per_second / 1_000_000:.1f} MB/s"

    return f"{bytes_per_second // 1000} KB/s"
