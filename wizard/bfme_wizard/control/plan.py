"""The plan: what the player chose to install, the jobs it takes, and how far each of their steps got. No GTK.

A job of the plan is one job of engine/jobs.py, named by the program it installs, or "environment" for the game
environment, which comes first when it is not ready yet.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..engine.jobs import PrepareJob
from .steps import STEPS, Step, StepCatalog


class Plan:
    def __init__(self, catalog: StepCatalog = STEPS) -> None:
        self.catalog = catalog
        self.selection: tuple[str, ...] = ()  # what the player chose, in install order
        self.jobs: list[str] = []  # the jobs that choice takes
        self.steps: dict[str, str] = {}  # step id: pending | running | done | skipped | failed
        self.started_from_home = False  # it began on the home screen: stopping it goes back there
        self.just_finished = False  # this session ran it to the end

    def choose(self, programs: Iterable[str]) -> tuple[str, ...]:
        """Remember the chosen programs, in install order."""
        self.selection = self.catalog.in_order(programs)
        return self.selection

    def same_choice(self, programs: Iterable[str]) -> bool:
        return bool(self.selection) and self.catalog.in_order(programs) == self.selection

    def jobs_for(self, programs: Iterable[str], environment_ready: bool) -> list[str]:
        """The jobs these programs need. Empty when none is wanted, since the game environment alone is not a choice."""
        chosen = list(self.catalog.in_order(programs))

        if not chosen:
            return []

        if environment_ready:
            return chosen

        return [PrepareJob.KEY, *chosen]

    def begin(self, programs: Iterable[str] | None, environment_ready: bool, from_home: bool) -> bool:
        """Plan the choice (the last one if `programs` is None). False when nothing is chosen."""
        if programs is not None:
            self.choose(programs)

        jobs = self.jobs_for(self.selection, environment_ready)

        if not jobs:
            return False

        self.jobs = jobs
        self.steps = {}

        for step_id in self.step_ids:
            self.steps[step_id] = "pending"

        self.started_from_home = from_home
        self.just_finished = False
        return True

    @property
    def step_defs(self) -> list[Step]:
        """Every step of the plan. "Step 3 of 8" counts the whole plan."""
        steps = []

        for job in self.jobs:
            steps.extend(self.catalog.of(job))

        return steps

    @property
    def step_ids(self) -> list[str]:
        ids = []

        for step_id, _title, _description in self.step_defs:
            ids.append(step_id)

        return ids

    @property
    def done_count(self) -> int:
        """How many steps are done or skipped."""
        count = 0

        for state in self.steps.values():
            if state in ("done", "skipped"):
                count += 1

        return count

    def step_number(self, current: str | None) -> int:
        """1-based position of the running step in the plan, or of the next one when none runs."""
        ids = self.step_ids

        if current in ids:
            return ids.index(current) + 1

        # Not past the last step, while a job is finishing up.
        return max(1, min(self.done_count + 1, len(ids)))

    def first_unfinished_job(self) -> str | None:
        """Where a resume starts. None when the plan is done."""
        for job in self.jobs:
            for step_id, _title, _description in self.catalog.of(job):
                if self.steps[step_id] not in ("done", "skipped"):
                    return job

        return None

    def begin_job(self, job: str) -> None:
        """A job starts. Its steps start over."""
        for step_id, _title, _description in self.catalog.of(job):
            self.steps[step_id] = "pending"

    def finish_job(self, job: str) -> None:
        """The job finished, so the steps it did not report are done too."""
        for step_id, _title, _description in self.catalog.of(job):
            if self.steps[step_id] in ("pending", "running"):
                self.steps[step_id] = "done"
