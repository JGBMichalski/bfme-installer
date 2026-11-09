"""The steps of every job, as the install page shows them, and the programs a plan can hold, in install order."""

from __future__ import annotations

from collections.abc import Iterable

from ..engine import programs as engine_programs
from ..engine.jobs import PrepareJob

# (step id, title, description)
Step = tuple[str, str, str]


class StepCatalog:
    def __init__(self) -> None:
        # The steps of each job: the game environment's, then each program's that has a job of its own.
        self.by_job: dict[str, list[Step]] = {PrepareJob.KEY: list(PrepareJob.STEPS)}
        self.choices: list[str] = []  # the start page's choices, in install order
        self.programs: list[str] = []  # everything that can be opened, and removed again
        self.tools: list[str] = []  # the Programs page's tools; each installs as a job of its own

        for program in engine_programs.EVERY_PROGRAM:
            if program.steps:
                self.by_job[program.key] = list(program.steps)

            if program.is_tool:
                self.tools.append(program.key)
                continue

            self.programs.append(program.key)

            if program.choice is not None:
                self.choices.append(program.key)

    def of(self, job: str) -> list[Step]:
        return self.by_job[job]

    def _find(self, step_id: str) -> Step | None:
        for steps in self.by_job.values():
            for step in steps:
                if step[0] == step_id:
                    return step

        return None

    def title_of(self, step_id: str) -> str:
        step = self._find(step_id)

        if step is None:
            return step_id

        return step[1]

    def description_of(self, step_id: str) -> str:
        step = self._find(step_id)

        if step is None:
            return ""

        return step[2]

    def in_order(self, programs: Iterable[str]) -> tuple[str, ...]:
        """The jobs of these programs that a plan can hold (the choices and the tools), in install order. Others are
        left out."""
        wanted = set(programs)
        ordered = []

        for key in (*self.choices, *self.tools):
            if key in wanted:
                ordered.append(key)

        return tuple(ordered)


STEPS = StepCatalog()
