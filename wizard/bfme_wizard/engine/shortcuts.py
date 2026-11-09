"""Menu shortcuts for the installed programs. The app only runs as a Flatpak, so they open the program through it."""

from __future__ import annotations

import os
from pathlib import Path

from .events import Emit, Log, Warn
from .paths import Paths
from .programs import PROGRAMS, Program


class MenuShortcuts:
    """The shortcuts in the host's menu folder: one for each installed program that has one, and none for the others."""

    RELEASE_APP_ID = "com.jgbmichalski.BfmeInstaller"
    FLATPAK_INFO = Path("/.flatpak-info")
    MOUNTINFO = Path("/proc/self/mountinfo")
    # Shortcuts the app wrote before, under names it no longer uses. Removed so the menu has no duplicates.
    OLD_SUFFIXES = ("Launcher",)

    def __init__(
        self,
        paths: Paths,
        environ: dict[str, str] | None = None,
        info: Path | None = None,
        mountinfo: Path | None = None,
    ) -> None:
        self.paths = paths
        self.environ = environ
        self.info = info or self.FLATPAK_INFO
        self.mountinfo = mountinfo or self.MOUNTINFO

    @property
    def app_id(self) -> str:
        """This app's Flatpak ID, or the release's outside the Flatpak."""
        env = os.environ if self.environ is None else self.environ
        return env.get("FLATPAK_ID") or self.RELEASE_APP_ID

    @property
    def folder(self) -> Path:
        return Paths.menu_dir(self.environ)

    @staticmethod
    def with_shortcut() -> list[Program]:
        """The programs that have a menu shortcut when they are installed."""
        found = []

        for program in PROGRAMS:
            if program.shortcut is not None:
                found.append(program)

        return found

    def file_name(self, program: Program) -> str:
        return f"{self.app_id}.{program.shortcut.suffix}.desktop"

    def flatpak_wrapper(self) -> str:
        """The command Flatpak exports for this app, for TryExec: a desktop hides a shortcut whose TryExec is gone. Empty
        when it cannot be worked out."""
        try:
            text = self.info.read_text(encoding="utf-8")
        except OSError:
            return ""

        original = ""
        current = ""

        for line in text.splitlines():
            if line.startswith("original-app-path="):
                original = line[len("original-app-path=") :]

            if line.startswith("app-path="):
                current = line[len("app-path=") :]

        app_path = original or current
        marker = f"app/{self.app_id}/"

        if marker not in app_path:
            return ""

        install_root = app_path[: app_path.index(marker)]

        return f"{install_root}exports/bin/{self.app_id}"

    def folder_reachable(self) -> bool:
        """Whether the host's menu folder is really shared into the sandbox. Without the permission (a `flatpak override`,
        Flatseal) writes land in sandbox scratch space and never reach the menu. A shared folder has its own mount or
        sits under a bigger share; an unshared one sits under `/` only."""
        # The mount list has real paths, and /home links to /var/home on some systems.
        real = os.path.realpath(self.folder)

        try:
            lines = self.mountinfo.read_text(encoding="utf-8").splitlines()
        except OSError:
            return False

        for line in lines:
            fields = line.split(" ")

            if len(fields) < 5:
                continue

            mount_point = fields[4].replace("\\040", " ")  # a space in a path is written \040

            if mount_point == "/":
                continue

            if real == mount_point or real.startswith(mount_point + "/"):
                return True

        return False

    def text(self, program: Program, wrapper: str) -> str:
        """The text of the program's shortcut. It opens the program through the app's Flatpak."""
        app = self.app_id
        shortcut = program.shortcut
        name = shortcut.name

        # A copy built under another app ID (dev/install-local.sh) says so, so it can sit beside the release.
        if app != self.RELEASE_APP_ID:
            name += " (Dev)"

        lines = [
            "[Desktop Entry]",
            "Type=Application",
            f"Name={name}",
            f"Comment={shortcut.comment}",
            f"Exec=flatpak run --command=bfme-installer {app} --open {program.key}",
        ]

        if wrapper:
            lines.append(f"TryExec={wrapper}")

        lines += [
            f"Icon={app}.{shortcut.suffix}",
            "Terminal=false",
            "Categories=Game;",
            "StartupNotify=true",
            f"X-Flatpak={app}",
        ]

        return "\n".join(lines) + "\n"

    def _sync_one(self, program: Program, installed: bool, wrapper: str) -> bool:
        """Write or remove one shortcut. A correct shortcut is left alone, so the desktop does not rebuild its menu on
        every wizard start. False when the folder cannot be written."""
        folder = self.folder
        file = folder / self.file_name(program)

        try:
            if not installed:
                file.unlink(missing_ok=True)
                return True

            text = self.text(program, wrapper)

            if file.is_file() and file.read_text() == text:
                return True

            folder.mkdir(parents=True, exist_ok=True)
            new = file.with_name(file.name + ".new")
            new.write_text(text)
            new.replace(file)
        except OSError:
            file.with_name(file.name + ".new").unlink(missing_ok=True)
            return False

        return True

    def sync(self, emit: Emit) -> bool:
        """A shortcut for each installed program, and none for the others. False when they could not all be written."""
        app = self.app_id
        folder = self.folder
        installed = {}
        any_installed = False

        for program in self.with_shortcut():
            installed[program.key] = program.installed(self.paths)

            if installed[program.key]:
                any_installed = True

        # With nothing installed, create nothing (a first start leaves no folders). Leftover entries are still removed
        # below.
        if any_installed and not self.folder_reachable():
            emit(
                Warn(
                    f"This app cannot reach your menu folder ({folder}), so there are no shortcuts. To give it access: "
                    f"flatpak override --user --filesystem=xdg-data/applications:create {app}"
                )
            )
            return False

        wrapper = self.flatpak_wrapper()
        failed = False

        for program in self.with_shortcut():
            if not self._sync_one(program, installed[program.key], wrapper):
                failed = True

        for suffix in self.OLD_SUFFIXES:
            try:
                (folder / f"{app}.{suffix}.desktop").unlink(missing_ok=True)
            except OSError:
                failed = True

        if failed:
            emit(Warn(f"Could not update the shortcuts in {folder}."))
            return False

        emit(Log(f"Shortcuts are up to date in {folder}"))

        return True
