"""engine.shortcuts and engine.launch, compared with the setup script in the Flatpak."""
import os
import subprocess
import time
from pathlib import Path

import pytest
from bfme_wizard.engine import launch, shortcuts
from bfme_wizard.engine.config import Config
from bfme_wizard.engine.events import Log, Warn
from bfme_wizard.engine.paths import Paths

from tests.helpers import manifest_app_id, manifest_icon_exports

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "bfme-linux-setup.sh"
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

    def script(self, paths):
        """Run the script with the sandbox environment and return the completed process."""
        env = dict(self.environ, PATH="/usr/bin:/bin", BFME_HOME=str(paths.base), BFME_MOUNTINFO=str(self.mountinfo),
                   BFME_FLATPAK_INFO=str(self.info))
        return subprocess.run([str(SCRIPT), "--machine", "shortcuts"], env=env, capture_output=True, text=True, timeout=60)

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


def compare(tmp_path, paths, sandbox, before=None):
    """Run the script's shortcuts, then the engine's, from the same start. Both must leave the same files and say the same
    thing. Returns the files after running the script."""
    start = before or {}

    for name, text in start.items():
        put(sandbox.apps / name, text)

    done = sandbox.script(paths)
    from_script = sandbox.files()
    script_said = []

    for line in done.stdout.splitlines():
        if line.startswith("@bfme WARN "):
            script_said.append(Warn(line[len("@bfme WARN "):]))

    if done.returncode == 0:
        script_said.append(Log(done.stdout.splitlines()[-1]))

    if sandbox.apps.is_dir():
        for path in sandbox.apps.iterdir():
            path.unlink()

    for name, text in start.items():
        put(sandbox.apps / name, text)

    ok, events = sandbox.engine(paths)

    assert sandbox.files() == from_script
    assert events == script_said
    assert ok == (done.returncode == 0)

    return from_script


@pytest.fixture
def paths(tmp_path):
    return Paths(tmp_path / "data")


# Which shortcuts there are, compared with the script

@pytest.mark.parametrize("installed", [(), ("aio-launcher",), ("aotr",), ("aio-launcher", "arena", "aotr")])
@pytest.mark.parametrize("app_id", [DEV_ID, shortcuts.RELEASE_APP_ID])
def test_the_shortcuts_are_the_scripts(tmp_path, paths, installed, app_id):
    make_prefix(paths)

    for program in installed:
        install(paths, program)

    files = compare(tmp_path, paths, Sandbox(tmp_path, app_id=app_id))

    assert len(files) == len(installed)


@pytest.mark.parametrize("info,original", [(False, False), (True, True)])
def test_tryexec_follows_where_the_app_is_installed_as_the_script_does(tmp_path, paths, info, original):
    make_prefix(paths)
    install(paths, "arena")

    compare(tmp_path, paths, Sandbox(tmp_path, info=info, original=original))


def test_the_text_of_a_shortcut(tmp_path, paths):
    make_prefix(paths)
    install(paths, "aio-launcher")
    sandbox = Sandbox(tmp_path)

    sandbox.engine(paths)

    assert sandbox.files()[f"{DEV_ID}.Launcher.desktop"] == (
        "[Desktop Entry]\nType=Application\nName=BFME All-in-One Launcher (Dev)\n"
        "Comment=Install, mod and manage the Battle for Middle-earth games\n"
        f"Exec=flatpak run --command=bfme-installer {DEV_ID} --open launcher\n"
        f"TryExec={tmp_path}/flatpak/exports/bin/{DEV_ID}\n"
        f"Icon={DEV_ID}.Launcher\nTerminal=false\nCategories=Game;\nStartupNotify=true\nX-Flatpak={DEV_ID}\n")


def test_a_removed_programs_shortcut_goes_and_a_correct_one_is_left_alone(tmp_path, paths):
    make_prefix(paths)
    install(paths, "arena")
    sandbox = Sandbox(tmp_path)
    arena_text = shortcuts.shortcut_text(DEV_ID, "arena", shortcuts.flatpak_wrapper(DEV_ID, sandbox.info))
    before = {f"{DEV_ID}.Launcher.desktop": "stale", f"{DEV_ID}.Arena.desktop": arena_text, "other.desktop": "keep"}

    files = compare(tmp_path, paths, sandbox, before)

    assert files == {f"{DEV_ID}.Arena.desktop": arena_text, "other.desktop": "keep"}

    old = time.time() - 1000
    os.utime(sandbox.apps / f"{DEV_ID}.Arena.desktop", (old, old))
    sandbox.engine(paths)

    assert (sandbox.apps / f"{DEV_ID}.Arena.desktop").stat().st_mtime == old


# Whether the sandbox can reach the menu folder, compared with the script

@pytest.mark.parametrize("mounts", ["none", "home", "space", "sibling"])
def test_reaching_the_menu_folder_is_the_scripts(tmp_path, paths, mounts):
    make_prefix(paths)
    install(paths, "aotr")
    home = tmp_path / "home"
    choices = {
        "none": [],
        "home": [home],                                 # a bigger share holds the menu folder
        "space": [tmp_path / "a folder"],               # \040 in the list
        "sibling": [home / ".local/share/applications-old"],
    }

    compare(tmp_path, paths, Sandbox(tmp_path, mounts=choices[mounts]))


def test_unreachable_says_how_to_fix_it_and_writes_nothing(tmp_path, paths):
    make_prefix(paths)
    install(paths, "aotr")
    sandbox = Sandbox(tmp_path, mounts=[])

    ok, events = sandbox.engine(paths)

    assert ok is False
    assert sandbox.files() == {}
    assert events == [Warn(f"This app cannot reach your menu folder ({sandbox.apps}), so there are no shortcuts. To give "
                           f"it access: flatpak override --user --filesystem=xdg-data/applications:create {DEV_ID}")]


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
           "BFME_UMU_RUN": str(bin_dir / "umu-run"), "BFME_PROTONPATH": "fake-proton"}

    for name, value in env.items():
        monkeypatch.setenv(name, value)

    return env


def test_a_program_starts_from_its_folder_as_the_script_starts_it(tmp_path, paths, umu):
    make_prefix(paths)
    install(paths, "aotr")
    done = subprocess.run([str(SCRIPT), "aotr"], env=dict(umu, BFME_HOME=str(paths.base)), capture_output=True,
                          text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    from_script = Path(umu["UMU_LOG"]).read_text().splitlines()[-1]
    script_said = done.stdout.splitlines()[-1]
    os.remove(umu["UMU_LOG"])
    events = []

    code = launch.start_program(paths, Config(), "fake-proton", "aotr", paths.aotr_exe, "aotr", events.append)

    assert code == 0
    assert Path(umu["UMU_LOG"]).read_text().splitlines() == [from_script]
    assert events[0].text.split(". Log: ")[0] == script_said.split(". Log: ")[0]


def test_each_start_gets_its_own_log_and_the_newest_ten_are_kept(tmp_path, paths, umu):
    put(paths.aotr_exe)
    paths.logs.mkdir(parents=True)

    for number in range(12):
        old = paths.logs / f"aotr-2025010{number % 10}-00000{number}.log"
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
