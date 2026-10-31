"""engine.shortcuts and engine.launch, in a stand-in for the Flatpak sandbox."""
import os
import time
from pathlib import Path

import pytest
from bfme_wizard.engine import launch, shortcuts
from bfme_wizard.engine.config import Config
from bfme_wizard.engine.events import Log, Warn
from bfme_wizard.engine.paths import Paths

from tests.helpers import manifest_app_id, manifest_icon_exports

DEV_ID = "com.example.Dev"


def put(path, text="x"):
    """Write text to a file, creating parent directories if necessary."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def make_prefix(paths):
    """Create the necessary folder structure for a Wine prefix."""
    for folder in ("windows", "users/steamuser"):
        (paths.drive_c / folder).mkdir(parents=True, exist_ok=True)


def install(paths, program):
    """Create the executable file for the given program in the Wine prefix."""
    exe = {"aio-launcher": paths.aio_launcher_exe, "arena": paths.arena_exe, "aotr": paths.aotr_exe}[program]
    put(exe)


class Sandbox:
    """Stands in for the Flatpak sandbox: the app ID, a home folder, the file that says where the app is installed, and the
    list of mounts. By default the menu folder is mounted, as it is when the app has the permission."""

    def __init__(self, tmp_path, app_id=DEV_ID, info=True, original=False, mounts=None):
        """Initialize the sandbox with the given temporary path, app ID, and optional settings for flatpak-info and mounts."""
        self.tmp = tmp_path
        self.app_id = app_id
        self.home = tmp_path / "home"
        self.home.mkdir(exist_ok=True)
        self.apps = self.home / ".local/share/applications"
        self.info = tmp_path / ("flatpak-info" if info else "no-such-file")
        self.mountinfo = tmp_path / "mountinfo"
        app_path = tmp_path / "flatpak/app" / app_id / "x86_64/master/0123abc/files"
        lines = ["[Instance]", f"app-path={app_path}"]

        # The path the app was installed under before something moved it: it wins when it is there.
        if original:
            lines.append(f"original-app-path={tmp_path}/elsewhere/app/{app_id}/x86_64/master/0123abc/files")

        (tmp_path / "flatpak-info").write_text("\n".join(lines) + "\n")
        lines = ["20 1 0:20 / / rw,nosuid,nodev - tmpfs tmpfs rw", "36 20 0:32 / /run rw - tmpfs tmpfs rw"]

        if mounts is None:
            mounts = [self.apps]

        number = 40

        for folder in mounts:
            escaped = str(folder).replace(" ", "\\040")
            lines.append(f"{number} 20 0:{number} / {escaped} rw,relatime - ext4 /dev/sda1 rw")
            number += 1

        self.mountinfo.write_text("\n".join(lines) + "\n")
        self.environ = {"FLATPAK_ID": app_id, "HOME": str(self.home)}

    def engine(self, paths):
        """Run the engine's shortcut synchronization with the sandbox environment and return the result and events."""
        events = []
        ok = shortcuts.sync(paths, events.append, self.environ, self.info, self.mountinfo)
        return ok, events

    def files(self):
        """Return a dictionary of the files in the sandbox's applications folder, keyed by file name."""
        found = {}

        if self.apps.is_dir():
            for path in sorted(self.apps.iterdir()):
                found[path.name] = path.read_text()

        return found


RELEASE_ID = shortcuts.RELEASE_APP_ID

# Per program: the shortcut's file suffix, name, comment and what it opens.
PROGRAM_SHORTCUTS = {
    "aio-launcher": ("AioLauncher", "BFME All-in-One Launcher", "Install, mod and manage the Battle for Middle-earth games"),
    "arena": ("Arena", "BFME Online Arena", "Play Battle for Middle-earth online"),
    "aotr": ("Aotr", "Age of the Ring", "Play the Age of the Ring mod for Battle for Middle-earth 2"),
}


def desktop_file(app_id, program, tryexec):
    """The file name and full text of a program's shortcut. A development build says so in the name. Without a
    known wrapper (tryexec is None) there is no TryExec line."""
    suffix, name, comment = PROGRAM_SHORTCUTS[program]

    if app_id != RELEASE_ID:
        name = f"{name} (Dev)"

    text = "[Desktop Entry]\nType=Application\n"
    text += f"Name={name}\n"
    text += f"Comment={comment}\n"
    text += f"Exec=flatpak run --command=bfme-installer {app_id} --open {program}\n"

    if tryexec is not None:
        text += f"TryExec={tryexec}\n"

    text += f"Icon={app_id}.{suffix}\nTerminal=false\nCategories=Game;\nStartupNotify=true\nX-Flatpak={app_id}\n"
    return f"{app_id}.{suffix}.desktop", text


def up_to_date(sandbox):
    return Log(f"Shortcuts are up to date in {sandbox.apps}")


def unreachable(sandbox):
    return Warn(f"This app cannot reach your menu folder ({sandbox.apps}), so there are no shortcuts. To give "
                f"it access: flatpak override --user --filesystem=xdg-data/applications:create {sandbox.app_id}")


@pytest.fixture
def paths(tmp_path):
    return Paths(tmp_path / "data")


# Which shortcuts there are

@pytest.mark.parametrize("installed", [(), ("aio-launcher",), ("aotr",), ("aio-launcher", "arena", "aotr")])
@pytest.mark.parametrize("app_id", [DEV_ID, RELEASE_ID])
def test_each_installed_program_gets_a_shortcut(tmp_path, paths, installed, app_id):
    make_prefix(paths)

    for program in installed:
        install(paths, program)

    sandbox = Sandbox(tmp_path, app_id=app_id)
    expected = {}

    for program in installed:
        name, text = desktop_file(app_id, program, f"{tmp_path}/flatpak/exports/bin/{app_id}")
        expected[name] = text

    ok, events = sandbox.engine(paths)

    assert ok is True
    assert sandbox.files() == expected
    assert events == [up_to_date(sandbox)]


@pytest.mark.parametrize("info,original,tryexec", [
    (False, False, None),                                   # no flatpak-info: no TryExec
    (True, True, "elsewhere/exports/bin/com.example.Dev"),  # the original install path wins
])
def test_tryexec_follows_where_the_app_is_installed(tmp_path, paths, info, original, tryexec):
    make_prefix(paths)
    install(paths, "arena")
    sandbox = Sandbox(tmp_path, info=info, original=original)

    if tryexec is not None:
        tryexec = f"{tmp_path}/{tryexec}"

    name, text = desktop_file(DEV_ID, "arena", tryexec)

    ok, events = sandbox.engine(paths)

    assert ok is True
    assert sandbox.files() == {name: text}
    assert events == [up_to_date(sandbox)]


def test_the_text_of_a_shortcut(tmp_path, paths):
    make_prefix(paths)
    install(paths, "aio-launcher")
    sandbox = Sandbox(tmp_path)

    sandbox.engine(paths)

    assert sandbox.files()[f"{DEV_ID}.AioLauncher.desktop"] == (
        "[Desktop Entry]\nType=Application\nName=BFME All-in-One Launcher (Dev)\n"
        "Comment=Install, mod and manage the Battle for Middle-earth games\n"
        f"Exec=flatpak run --command=bfme-installer {DEV_ID} --open aio-launcher\n"
        f"TryExec={tmp_path}/flatpak/exports/bin/{DEV_ID}\n"
        f"Icon={DEV_ID}.AioLauncher\nTerminal=false\nCategories=Game;\nStartupNotify=true\nX-Flatpak={DEV_ID}\n")


def test_a_removed_programs_shortcut_goes_and_a_correct_one_is_left_alone(tmp_path, paths):
    make_prefix(paths)
    install(paths, "arena")
    sandbox = Sandbox(tmp_path)
    _, arena_text = desktop_file(DEV_ID, "arena", f"{tmp_path}/flatpak/exports/bin/{DEV_ID}")
    before = {f"{DEV_ID}.Launcher.desktop": "stale", f"{DEV_ID}.Arena.desktop": arena_text, "other.desktop": "keep"}

    for name, text in before.items():
        put(sandbox.apps / name, text)

    ok, events = sandbox.engine(paths)

    assert ok is True
    assert sandbox.files() == {f"{DEV_ID}.Arena.desktop": arena_text, "other.desktop": "keep"}
    assert events == [up_to_date(sandbox)]

    old = time.time() - 1000
    os.utime(sandbox.apps / f"{DEV_ID}.Arena.desktop", (old, old))
    sandbox.engine(paths)

    assert (sandbox.apps / f"{DEV_ID}.Arena.desktop").stat().st_mtime == old


# Whether the sandbox can reach the menu folder

@pytest.mark.parametrize("mounts,reachable", [
    ("none", False),
    ("home", True),        # a bigger share holds the menu folder
    ("space", False),      # \040 in the list
    ("sibling", False),
])
def test_reaching_the_menu_folder(tmp_path, paths, mounts, reachable):
    make_prefix(paths)
    install(paths, "aotr")
    home = tmp_path / "home"
    choices = {
        "none": [],
        "home": [home],
        "space": [tmp_path / "a folder"],
        "sibling": [home / ".local/share/applications-old"],
    }
    sandbox = Sandbox(tmp_path, mounts=choices[mounts])

    ok, events = sandbox.engine(paths)

    if reachable:
        name, text = desktop_file(DEV_ID, "aotr", f"{tmp_path}/flatpak/exports/bin/{DEV_ID}")
        assert ok is True
        assert sandbox.files() == {name: text}
        assert events == [up_to_date(sandbox)]
    else:
        # It says how to fix it and writes nothing.
        assert ok is False
        assert sandbox.files() == {}
        assert events == [unreachable(sandbox)]


def test_each_icon_is_the_one_the_manifest_exports():
    # The manifest installs each picture under a name, and the shortcuts ask for it. If they drift apart the menu shows a
    # missing-icon box, and nothing else notices.
    app = manifest_app_id()
    exported = set()

    for _width, _height, name in manifest_icon_exports().values():
        exported.add(name)

    asked = set()

    for program in shortcuts.SHORTCUTS:
        asked.add(f"{app}.{shortcuts.SHORTCUTS[program].suffix}")

    assert asked == exported


# Starting a program

FAKE_UMU = r"""#!/bin/sh
printf '%s|%s|%s\n' "$*" "$(pwd)" "${PROTON_VERB:-}" >> "$UMU_LOG"
echo "running $1"
exit 0
"""


@pytest.fixture
def umu(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    put(bin_dir / "umu-run", FAKE_UMU)
    (bin_dir / "umu-run").chmod(0o755)
    put(bin_dir / "lspci", "#!/bin/sh\n")
    (bin_dir / "lspci").chmod(0o755)
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path), "UMU_LOG": str(tmp_path / "umu.log"),
           "BFME_PROTONPATH": "fake-proton"}

    for name, value in env.items():
        monkeypatch.setenv(name, value)

    return env


def test_a_program_starts_from_its_folder(tmp_path, paths, umu):
    make_prefix(paths)
    install(paths, "aotr")
    events = []

    code = launch.start_program(paths, Config(), "fake-proton", "aotr", paths.aotr_exe, "aotr", events.append)

    # Each call is logged as "arguments|working folder|PROTON_VERB"; the game is the last call, after the prefix settings.
    calls = Path(umu["UMU_LOG"]).read_text().splitlines()
    assert code == 0
    assert calls[-1] == f"{paths.aotr_exe}|{paths.aotr_exe.parent}|runinprefix"
    assert events[0].text.startswith(f"Starting aotr. Log: {paths.logs}/aotr-")


def test_each_start_gets_its_own_log_and_the_newest_ten_are_kept(tmp_path, paths, umu):
    put(paths.aotr_exe)
    paths.logs.mkdir(parents=True)

    for number in range(12):
        old = paths.logs / f"aotr-2025010{number % 10}-{number:06d}.log"
        old.write_text("old")
        os.utime(old, (1000 + number, 1000 + number))

    put(paths.logs / "arena-20250101-000000.log", "another program's")
    events = []

    launch.start_program(paths, Config(), "fake-proton", "aotr", paths.aotr_exe, "Age of the Ring", events.append)

    logs = sorted(paths.logs.glob("aotr-*.log"))
    newest = Path(events[0].text.split("Log: ")[1])
    assert len(logs) == 10
    assert newest in logs
    assert newest.read_text() == f"running {paths.aotr_exe}\n"
    assert (paths.logs / "arena-20250101-000000.log").exists()
    assert events == [Log(f"Starting Age of the Ring. Log: {newest}")]


def test_only_the_logs_of_starts_are_rotated(paths, umu):
    put(paths.aotr_exe)
    paths.logs.mkdir(parents=True)
    put(paths.logs / "aotr-setup.log", "a log of its own")       # like aio-launcher-setup.log

    for number in range(12):
        old = paths.logs / f"aotr-2025010{number % 10}-{number:06d}.log"
        old.write_text("old")
        os.utime(old, (1000 + number, 1000 + number))

    launch.start_program(paths, Config(), "fake-proton", "aotr", paths.aotr_exe, "Age of the Ring", [].append)

    assert (paths.logs / "aotr-setup.log").read_text() == "a log of its own"
    assert len(launch.program_logs(paths.logs, "aotr")) == 10
