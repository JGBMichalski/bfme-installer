"""Menu shortcuts for the installed programs. The app only runs as a Flatpak, so they open the program through it."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from . import programs
from .events import Emit, Log, Warn
from .paths import Paths, menu_dir

RELEASE_APP_ID = "com.jgbmichalski.BfmeInstaller"
FLATPAK_INFO = Path("/.flatpak-info")
MOUNTINFO = Path("/proc/self/mountinfo")


@dataclass(frozen=True)
class Shortcut:
    name: str
    comment: str
    suffix: str # The end of the shortcut's file name and of its icon's name, both <app id>.<suffix>.
    open_arg: str # What the shortcut passes to --open. Existing shortcuts on players' computers use these, so they stay as they are.


SHORTCUTS = {
    "aio-launcher": Shortcut(
        name="BFME All-in-One Launcher",
        comment="Install, mod and manage the Battle for Middle-earth games",
        suffix="Launcher",
        open_arg="launcher",
    ),
    "arena": Shortcut(
        name="BFME Online Arena",
        comment="Play Battle for Middle-earth online",
        suffix="Arena",
        open_arg="arena",
    ),
    "aotr": Shortcut(
        name="Age of the Ring",
        comment="Play the Age of the Ring mod for Battle for Middle-earth 2",
        suffix="Aotr",
        open_arg="aotr",
    ),
}


def app_id(environ: dict[str, str] | None = None) -> str:
    """Get the Flatpak app ID for the current environment, or the release app ID if not running in Flatpak."""
    env = os.environ if environ is None else environ
    return env.get("FLATPAK_ID") or RELEASE_APP_ID


def shortcut_file(app: str, program: str) -> str:
    """Get the file name of the shortcut for the given app and program."""
    return f"{app}.{SHORTCUTS[program].suffix}.desktop"


def flatpak_wrapper(app: str, info: Path = FLATPAK_INFO) -> str:
    """The command Flatpak exports for this app, for TryExec: a desktop hides a shortcut whose TryExec is gone. Empty when it
    cannot be worked out. Returns the path to the wrapper script for the given app."""
    try:
        text = info.read_text(encoding="utf-8")
    except OSError:
        return ""

    original = ""
    current = ""

    for line in text.splitlines():
        if line.startswith("original-app-path="):
            original = line[len("original-app-path="):]

        if line.startswith("app-path="):
            current = line[len("app-path="):]

    app_path = original or current
    marker = f"app/{app}/"

    if marker not in app_path:
        return ""

    install_root = app_path[:app_path.index(marker)]

    return f"{install_root}exports/bin/{app}"


def menu_folder_reachable(folder: Path, mountinfo: Path = MOUNTINFO) -> bool:
    """Whether the host's menu folder is really shared into the sandbox. Without the permission (a `flatpak override`,
    Flatseal) writes land in sandbox scratch space and never reach the menu. A shared folder has its own mount or sits under
    a bigger share; an unshared one sits under `/` only."""
    # The mount list has real paths, and /home links to /var/home on some systems.
    real = os.path.realpath(folder)

    try:
        lines = mountinfo.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False

    for line in lines:
        fields = line.split(" ")

        if len(fields) < 5:
            continue

        mount_point = fields[4].replace("\\040", " ")   # a space in a path is written \040

        if mount_point == "/":
            continue

        if real == mount_point or real.startswith(mount_point + "/"):
            return True

    return False


def shortcut_text(app: str, program: str, wrapper: str) -> str:
    """Generate the text content of a desktop shortcut for the given app, program, and wrapper script."""
    shortcut = SHORTCUTS[program]
    name = shortcut.name

    # A copy built under another app ID (dev/install-local.sh) says so, so it can sit beside the release.
    if app != RELEASE_APP_ID:
        name += " (Dev)"

    lines = [
        "[Desktop Entry]",
        "Type=Application",
        f"Name={name}",
        f"Comment={shortcut.comment}",
        f"Exec=flatpak run --command=bfme-installer {app} --open {shortcut.open_arg}",
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


def _sync_one(folder: Path, app: str, program: str, installed: bool, wrapper: str) -> bool:
    """Write or remove one shortcut. A correct shortcut is left alone, so the desktop does not rebuild its menu on every
    wizard start. False when the folder cannot be written."""
    file = folder / shortcut_file(app, program)

    try:
        if not installed:
            file.unlink(missing_ok=True)
            return True

        text = shortcut_text(app, program, wrapper)

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


def sync(paths: Paths, emit: Emit, environ: dict[str, str] | None = None, info: Path = FLATPAK_INFO,
         mountinfo: Path = MOUNTINFO) -> bool:
    """A shortcut for each installed program, and none for the others. False when they could not all be written."""
    app = app_id(environ)
    folder = menu_dir(environ)
    installed = {}
    any_installed = False

    for program in SHORTCUTS:
        installed[program] = programs.installed(paths, program)

        if installed[program]:
            any_installed = True

    # With nothing installed, create nothing (a first start leaves no folders). Leftover entries are still removed below.
    if any_installed and not menu_folder_reachable(folder, mountinfo):
        emit(Warn(f"This app cannot reach your menu folder ({folder}), so there are no shortcuts. To give it access: "
                  f"flatpak override --user --filesystem=xdg-data/applications:create {app}"))
        return False

    wrapper = flatpak_wrapper(app, info)
    failed = False

    for program in SHORTCUTS:
        if not _sync_one(folder, app, program, installed[program], wrapper):
            failed = True

    if failed:
        emit(Warn(f"Could not update the shortcuts in {folder}."))
        return False

    emit(Log(f"Shortcuts are up to date in {folder}"))

    return True
