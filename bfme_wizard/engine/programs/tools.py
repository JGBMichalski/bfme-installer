"""Workshop Studio and Mission Control: single programs from the BFME Arena site, downloaded straight into a folder of
their own."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ..context import Context
from ..download import Download
from ..events import Log, report_speed
from ..paths import Paths
from .base import Program, Step

if TYPE_CHECKING:
    from ..jobs import InstallJob


class Tool(Program):
    url: str
    folder_name: str  # under C:\BFME Tools
    exe_name: str

    removal = "Its folder is deleted. The AIO Launcher, the Arena, Age of the Ring and the games are not touched."
    before_install = "About 300 MB to download."
    is_tool = True

    @property
    def name(self) -> str:
        return self.title

    @property
    def steps(self) -> tuple[Step, ...]:
        return ((self.key, f"Download {self.title}", f"Fetching {self.title} from the BFME Arena site."),)

    def exe(self, paths: Paths) -> Path:
        return paths.drive_c / "BFME Tools" / self.folder_name / self.exe_name

    def run_install(self, job: InstallJob) -> list[str]:
        job.start(self.key)
        self.install(job)
        job.done(self.key)
        return [f"{self.name} is installed."]

    def install(self, ctx: Context, url: str | None = None) -> None:
        exe = self.exe(ctx.paths)
        emit = ctx.emit
        cancel = ctx.cancel
        emit(Log(f"Downloading {exe.name}."))
        Download(url or self.url, exe, cancel=cancel, on_speed=report_speed(emit)).run()
        exe.chmod(0o755)


class WorkshopStudio(Tool):
    key = "workshop"
    title = "Workshop Studio"
    summary = "Create workshop packages and publish them to the BFME Workshop"
    url = "https://bfmeladder.com/download-go?app=workshop"
    folder_name = "Workshop Studio"
    exe_name = "WorkshopStudio.exe"


class MissionControl(Tool):
    key = "mission-control"
    title = "Mission Control"
    summary = "For Arena operators, patch developers, event organizers and moderators"
    url = "https://bfmeladder.com/download-go?app=mission-control"
    folder_name = "Mission Control"
    exe_name = "MissionControl.exe"
