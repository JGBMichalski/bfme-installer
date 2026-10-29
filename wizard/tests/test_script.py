"""The setup script's own contract with the wizard: what `status` calls complete, which shortcuts exist, and what each
job reports. Runs the real scripts/bfme-linux-setup.sh in a throwaway data directory, with a fake curl and a fake
umu-run in front of the real ones, so nothing is downloaded and nothing outside the temporary folder is touched.

`prepare` is left out on purpose: its only work is the system checks (unchanged), which depend on the computer the
tests run on.
"""
import fcntl
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.helpers import EXPORT_SUFFIX, manifest_app_id, manifest_icon_exports

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "bfme-linux-setup.sh"
PICTURES = SCRIPT.parents[1] / "wizard" / "bfme_wizard" / "icons"   # the pictures of the programs, beside the scripts folder
HAVE_SEVENZIP = any(shutil.which(c) for c in ("7zz", "7z", "7za"))

# Answers the few requests the script makes: the Arena's hash, a HEAD for a size, and any download.
FAKE_CURL = r"""#!/usr/bin/env bash
out=""; head=0; url=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -fsIL|-sI|-I) head=1; shift ;;
    -m|--retry|--retry-delay|--connect-timeout|--speed-limit|--speed-time|-C) shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
case "$url" in *versionHash*) printf '%s' "$(printf 'arena-binary' | md5sum | awk '{print $1}')"; exit 0 ;; esac
if [ "$head" = "1" ]; then printf 'HTTP/1.1 200 OK\r\ncontent-length: 12\r\n\r\n'; exit 0; fi
[ -n "$out" ] || exit 0
mkdir -p "$(dirname "$out")"
case "$url" in *online-arena*) printf 'arena-binary' > "$out" ;; *) printf 'fake-download' > "$out" ;; esac
"""

# "Creates" the prefix, "runs" the AIO Launcher's setup and the Age of the Ring installer, and ignores registry writes.
FAKE_UMU = r"""#!/usr/bin/env bash
case "${1:-}" in
  "") mkdir -p "$WINEPREFIX/drive_c/windows" "$WINEPREFIX/drive_c/users/steamuser" ;;
  *AllInOneLauncherSetup.exe)
      d="$WINEPREFIX/drive_c/users/steamuser/AppData/Roaming/BFME All In One Launcher"
      mkdir -p "$d"; printf 'launcher' > "$d/AllInOneLauncher.exe" ;;
  *AotR_Standalone*Installer.exe)
      mkdir -p "$WINEPREFIX/drive_c/AgeoftheRing"; printf 'aotr' > "$WINEPREFIX/drive_c/AgeoftheRing/AotR_Launcher.exe" ;;
esac
exit 0
"""


def executable(path, text):
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class ScriptCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        executable(bin_dir / "curl", FAKE_CURL)
        executable(bin_dir / "umu-run", FAKE_UMU)
        self.base = self.tmp / "data"
        self.apps = self.tmp / "xdg" / "applications"
        self.prefix = self.base / "prefix"
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith("BFME_") and k not in ("FLATPAK_ID", "XDG_DATA_HOME")}
        self.env.update(
            BFME_HOME=str(self.base), XDG_DATA_HOME=str(self.tmp / "xdg"), BFME_UMU_RUN=str(bin_dir / "umu-run"),
            BFME_PROTONPATH="fake-proton",   # anything but the pinned build: the real one would be downloaded
            PATH=f"{bin_dir}:{os.environ['PATH']}",
        )

    def run_script(self, *args, machine=True, script=None):
        command = [str(script or SCRIPT), *(["--machine"] if machine else []), *args]
        return subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=120)

    def status_lines(self, proc):
        return [line for line in proc.stdout.splitlines() if line.startswith("@bfme ")]

    def status(self):
        """What `status` says, as a dict: {"prefix": "ready", "launcher": "missing", ..., "complete": "no"}."""
        done = self.run_script("status")
        self.assertEqual(done.returncode, 0, done.stderr)
        parts = (line.split(" ", 3) for line in self.status_lines(done) if line.startswith("@bfme STATUS "))
        return {p[2]: p[3] for p in parts}

    def make_prefix(self):
        for folder in ("drive_c/windows", "drive_c/users/steamuser"):
            (self.prefix / folder).mkdir(parents=True, exist_ok=True)

    def program_file(self, program):
        roaming = self.prefix / "drive_c/users/steamuser/AppData/Roaming"
        return {
            "launcher": roaming / "BFME All In One Launcher/AllInOneLauncher.exe",
            "arena": roaming / "BFME Competetive Arena/BfmeFoundationProject_OnlineArena.exe",
            "aotr": self.prefix / "drive_c/AgeoftheRing/AotR_Launcher.exe",
        }[program]

    def install(self, program):
        target = self.program_file(program)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x")

    def remove(self, program):
        """What a player deleting a program by hand does: its file is gone. Nothing tells the script."""
        self.program_file(program).unlink()

    def make_games(self):
        """The games the AIO Launcher installed. They live beside the programs, not inside them."""
        for folder, exe in (("BFME2", "lotrbfme2.exe"), ("RotWK", "lotrbfme2ep1.exe")):
            (self.prefix / "drive_c" / folder).mkdir(parents=True, exist_ok=True)
            (self.prefix / "drive_c" / folder / exe).write_text("game")

    def aotr_user_data(self):
        """Age of the Ring keeps its settings away from the program, in the player's own folder."""
        return self.prefix / "drive_c/users/steamuser/AppData/Roaming/Age of the Ring/Options.ini"

    def program_folder(self, program):
        return self.program_file(program).parent

    def uninstall_everything(self):
        shutil.rmtree(self.prefix / "drive_c/users/steamuser/AppData", ignore_errors=True)
        shutil.rmtree(self.prefix / "drive_c/AgeoftheRing", ignore_errors=True)

    def entries(self):
        return sorted(p.name for p in self.apps.glob("bfme-*.desktop")) if self.apps.is_dir() else []


class Status(ScriptCase):
    def complete(self, *programs, prefix=True):
        if prefix:
            self.make_prefix()
        for program in programs:
            self.install(program)
        return self.status()["complete"]

    def test_nothing_set_up_is_not_complete(self):
        self.assertEqual(self.status(), {
            "runner": "proton", "graphics": "vulkan", "prefix": "missing", "launcher": "missing", "arena": "missing", "aotr": "missing",
            "workshop": "missing", "mission-control": "missing",
            "bfme1": "missing", "bfme2": "missing", "rotwk": "missing", "complete": "no",
        })

    def test_a_ready_environment_alone_is_not_complete(self):
        self.assertEqual(self.complete(), "no")
        self.assertEqual(self.status()["prefix"], "ready")

    def test_any_one_program_in_a_ready_environment_is_complete(self):
        # No single program is required.
        for program in ("launcher", "arena", "aotr"):
            with self.subTest(program):
                self.uninstall_everything()
                self.assertEqual(self.complete(program), "yes")
                self.assertEqual(self.status()[program], "installed")

    def test_age_of_the_ring_alone_does_not_need_the_aio_launcher_or_the_arena(self):
        self.assertEqual(self.complete("aotr"), "yes")
        status = self.status()
        self.assertEqual((status["launcher"], status["arena"]), ("missing", "missing"))

    def test_programs_without_a_game_environment_are_not_complete(self):
        self.assertEqual(self.complete("launcher", "aotr", prefix=False), "no")

    def test_an_installed_game_is_not_a_program(self):
        self.make_prefix()
        (self.prefix / "drive_c/BFME2").mkdir(parents=True)
        (self.prefix / "drive_c/BFME2/lotrbfme2.exe").write_text("x")
        status = self.status()
        self.assertEqual((status["bfme2"], status["complete"]), ("installed", "no"))

    def test_an_interrupted_age_of_the_ring_install_does_not_count(self):
        self.make_prefix()
        self.install("aotr")
        (self.prefix / ".bfme-aotr-installing").write_text("")
        status = self.status()
        self.assertEqual((status["aotr"], status["complete"]), ("missing", "no"))

    def test_the_text_output_is_unchanged_by_the_status_lines(self):
        self.make_prefix()
        plain = self.run_script("status", machine=False)
        self.assertIn("AIO Launcher: not installed", plain.stdout)
        self.assertIn("Age of the Ring: not installed", plain.stdout)
        self.assertNotIn("@bfme", plain.stdout)


class ShortcutLifetime:
    """A program's shortcut exists exactly while the program is installed, and goes the moment the script looks and finds
    the program gone. The tests run twice: for the shortcuts a copy of the script writes outside the Flatpak, and for the
    ones it writes into the host's menu folder from inside it."""

    PROGRAMS = ("launcher", "arena", "aotr")

    def shortcuts(self):
        """The programs that have a shortcut right now."""
        raise NotImplementedError

    def install_all(self):
        self.make_prefix()
        for program in self.PROGRAMS:
            self.install(program)
        self.assertEqual(self.run_script("shortcuts").returncode, 0)
        self.assertEqual(self.shortcuts(), ["aotr", "arena", "launcher"])

    def test_only_installed_programs_get_a_shortcut(self):
        self.make_prefix()
        self.install("aotr")
        self.assertEqual(self.run_script("shortcuts").returncode, 0)
        self.assertEqual(self.shortcuts(), ["aotr"])
        self.install("launcher")
        self.run_script("shortcuts")
        self.assertEqual(self.shortcuts(), ["aotr", "launcher"])
        self.install("arena")
        self.run_script("shortcuts")
        self.assertEqual(self.shortcuts(), ["aotr", "arena", "launcher"])

    def test_removing_the_aio_launcher_removes_its_shortcut_and_only_its_shortcut(self):
        self.install_all()
        self.remove("launcher")
        self.assertEqual(self.run_script("shortcuts").returncode, 0)
        self.assertEqual(self.shortcuts(), ["aotr", "arena"])

    def test_every_program_takes_its_own_shortcut_with_it(self):
        for gone in self.PROGRAMS:
            with self.subTest(gone):
                self.uninstall_everything()
                self.install_all()
                self.remove(gone)
                self.run_script("shortcuts")
                self.assertEqual(self.shortcuts(), sorted(set(self.PROGRAMS) - {gone}))

    def test_the_last_program_to_go_takes_the_last_shortcut(self):
        self.make_prefix()
        self.install("launcher")
        self.run_script("shortcuts")
        self.assertEqual(self.shortcuts(), ["launcher"])
        self.remove("launcher")
        self.assertEqual(self.run_script("shortcuts").returncode, 0)   # no program left to ask for anything
        self.assertEqual(self.shortcuts(), [])

    def test_a_program_that_is_back_gets_its_shortcut_back(self):
        self.install_all()
        self.remove("arena")
        self.run_script("shortcuts")
        self.install("arena")
        self.run_script("shortcuts")
        self.assertEqual(self.shortcuts(), ["aotr", "arena", "launcher"])

    def test_a_half_finished_install_has_no_shortcut_yet(self):
        self.make_prefix()
        self.install("launcher")
        (self.prefix / ".bfme-launcher-installing").write_text("")
        self.run_script("shortcuts")
        self.assertEqual(self.shortcuts(), [])

    def test_reset_removes_every_shortcut_with_the_game_environment(self):
        self.install_all()
        self.assertEqual(self.run_script("reset-prefix", "--yes").returncode, 0)
        self.assertEqual((self.shortcuts(), self.prefix.exists()), ([], False))

    def test_nothing_installed_creates_nothing(self):
        # A first start leaves no folders or script copies.
        self.assertEqual(self.run_script("shortcuts").returncode, 0)
        self.assertEqual((self.apps.exists(), (self.base / "bin").exists(), (self.base / "icons").exists()),
                         (False, False, False))

    def test_a_shortcut_that_is_already_right_is_left_alone(self):
        # The desktop rebuilds its menu on file changes, and the wizard asks on every start.
        self.make_prefix()
        self.install("launcher")
        self.run_script("shortcuts")
        before = {p.name: (p.stat().st_ino, p.stat().st_mtime_ns) for p in self.apps.glob("*.desktop")}
        self.run_script("shortcuts")
        self.assertEqual({p.name: (p.stat().st_ino, p.stat().st_mtime_ns) for p in self.apps.glob("*.desktop")}, before)

    def test_a_shortcut_that_is_wrong_is_written_again(self):
        self.make_prefix()
        self.install("launcher")
        self.run_script("shortcuts")
        (path,) = self.apps.glob("*.desktop")
        path.write_text("[Desktop Entry]\nName=Something else\n")
        self.run_script("shortcuts")
        self.assertIn("All-in-One Launcher", path.read_text())

    def test_no_temporary_file_is_left_in_the_menu_folder(self):
        self.install_all()
        self.assertEqual(sorted(p.name for p in self.apps.iterdir() if p.suffix != ".desktop" and p.name != "mimeinfo.cache"), [])


class ShortcutsOutsideFlatpak(ShortcutLifetime, ScriptCase):
    def shortcuts(self):
        if not self.apps.is_dir():
            return []
        return sorted(p.name[len("bfme-"):-len(".desktop")] for p in self.apps.glob("bfme-*.desktop"))

    def test_the_shortcuts_start_the_program_through_the_copy_of_the_script(self):
        self.make_prefix()
        self.install("aotr")
        self.run_script("shortcuts")
        text = (self.apps / "bfme-aotr.desktop").read_text()
        self.assertIn(f'"{self.base}/bin/bfme-linux-setup.sh" aotr', text)
        self.assertTrue((self.base / "bin/bfme-linux-setup.sh").is_file())

    # ------------------------------------------------------------------ the pictures
    def icon_line(self, program):
        return re.search(r"^Icon=(.*)$", (self.apps / f"bfme-{program}.desktop").read_text(), re.M).group(1)

    def a_copy_of_the_script_elsewhere(self):
        """The script as it is when it sits outside a checkout: no folder of pictures near it."""
        folder = self.tmp / "elsewhere"
        folder.mkdir(exist_ok=True)
        copy = folder / "bfme-linux-setup.sh"
        shutil.copy2(SCRIPT, copy)
        return copy

    def test_each_shortcut_shows_its_programs_own_picture_from_a_copy_in_the_data_folder(self):
        self.make_prefix()
        for program in self.PROGRAMS:
            self.install(program)
        self.assertEqual(self.run_script("shortcuts").returncode, 0)
        for program in self.PROGRAMS:
            with self.subTest(program):
                self.assertEqual(self.icon_line(program), f"{self.base}/icons/{program}.png")
                self.assertEqual((self.base / "icons" / f"{program}.png").read_bytes(), (PICTURES / f"{program}.png").read_bytes())

    def test_the_pictures_are_copied_so_the_shortcuts_do_not_depend_on_the_checkout(self):
        # The same reason the script copies itself: a checkout that is moved or deleted must not take the icons with it.
        self.make_prefix()
        self.install("arena")
        self.run_script("shortcuts")
        self.assertNotIn(str(PICTURES), (self.apps / "bfme-arena.desktop").read_text())

    def test_without_the_pictures_anywhere_the_shortcut_falls_back_to_a_themed_icon(self):
        self.make_prefix()
        self.install("launcher")
        done = self.run_script("shortcuts", script=self.a_copy_of_the_script_elsewhere())
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.icon_line("launcher"), "applications-games")
        self.assertFalse((self.base / "icons").exists())

    def test_a_later_run_that_cannot_find_the_pictures_keeps_the_ones_already_copied(self):
        # The shortcuts' own copy of the script in <data dir>/bin has no checkout beside it.
        self.make_prefix()
        self.install("launcher")
        self.run_script("shortcuts")
        self.install("aotr")
        self.assertEqual(self.run_script("shortcuts", script=self.base / "bin" / "bfme-linux-setup.sh").returncode, 0)
        self.assertEqual(self.icon_line("launcher"), f"{self.base}/icons/launcher.png")
        self.assertEqual(self.icon_line("aotr"), f"{self.base}/icons/aotr.png")     # copied for all three the first time

    def test_a_picture_that_changed_is_copied_again_and_one_that_did_not_is_left_alone(self):
        self.make_prefix()
        self.install("launcher")
        self.run_script("shortcuts")
        stamp = lambda name: (self.base / "icons" / name).stat().st_mtime_ns
        before = {name: stamp(name) for name in ("arena.png", "aotr.png")}
        (self.base / "icons" / "launcher.png").write_bytes(b"an older version of the picture")
        self.run_script("shortcuts")
        self.assertEqual((self.base / "icons" / "launcher.png").read_bytes(), (PICTURES / "launcher.png").read_bytes())
        self.assertEqual({name: stamp(name) for name in before}, before)

    def test_a_removed_programs_picture_stays_so_installing_it_again_from_the_copy_of_the_script_still_has_one(self):
        self.make_prefix()
        self.install("launcher")
        self.install("arena")
        self.run_script("shortcuts")
        self.remove("launcher")
        self.run_script("shortcuts")
        self.assertTrue((self.base / "icons" / "launcher.png").is_file())
        self.assertFalse((self.apps / "bfme-launcher.desktop").exists())

    def test_a_picture_that_cannot_be_copied_does_not_stop_the_shortcut(self):
        self.make_prefix()
        self.install("launcher")
        (self.base).mkdir(parents=True, exist_ok=True)
        (self.base / "icons").write_text("a file where the folder should be")
        done = self.run_script("shortcuts")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.icon_line("launcher"), "applications-games")
        self.assertIn("Could not copy the picture", done.stderr)

    def test_an_install_does_not_fail_because_its_shortcuts_cannot_be_written(self):
        # The programs are installed whatever happens to the menu. A file where the folder should be stops the write.
        self.make_prefix()
        self.apps.parent.mkdir(parents=True, exist_ok=True)
        self.apps.write_text("not a folder")
        done = self.run_script("launcher-install")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.status_lines(done)[-1], "@bfme DONE")
        self.assertIn("Could not update the shortcuts", done.stderr)
        self.assertEqual((self.status()["launcher"], self.status()["arena"]), ("installed", "installed"))


class ShortcutsInFlatpak(ShortcutLifetime, ScriptCase):
    """Inside the sandbox the shortcuts go to the host's menu folder, which the manifest shares with the app."""
    APP_ID = "com.example.Dev"
    SUFFIX = {"Launcher": "launcher", "Arena": "arena", "Aotr": "aotr"}

    def setUp(self):
        super().setUp()
        self.sandbox()

    def sandbox(self, app_id=APP_ID, reachable=True, info=True, original=False, mounts=None):
        """Stand in for the sandbox: the app ID, a home folder, the file that says where the app is installed, and the
        list of mounts. By default that has the menu folder in it, as it does when the app has the permission; `mounts`
        names what is mounted instead (folders, as the sandbox lists them), always besides the root."""
        self.app_id = app_id
        self.home = self.tmp / "home"
        self.home.mkdir(exist_ok=True)
        self.apps = self.home / ".local/share/applications"
        self.installation = self.tmp / "flatpak"
        self.wrapper = self.installation / "exports/bin" / app_id
        app_path = self.installation / "app" / app_id / "x86_64/master/0123abc/files"
        lines = ["[Instance]", f"app-path={app_path}"]
        if original:   # the path the app was installed under before something moved it: it wins when it is there
            lines.append(f"original-app-path={self.tmp}/elsewhere/app/{app_id}/x86_64/master/0123abc/files")
        (self.tmp / "flatpak-info").write_text("\n".join(lines) + "\n")
        lines = ["20 1 0:20 / / rw,nosuid,nodev - tmpfs tmpfs rw", "36 20 0:32 / /run rw - tmpfs tmpfs rw"]
        if mounts is None:
            mounts = [self.apps] if reachable else []
        for number, folder in enumerate(mounts, start=40):
            escaped = str(folder).replace(" ", "\\040")   # the list writes a space in a path as \040
            lines.append(f"{number} 20 0:{number} / {escaped} rw,relatime - ext4 /dev/sda1 rw")
        (self.tmp / "mountinfo").write_text("\n".join(lines) + "\n")
        self.env.update(FLATPAK_ID=app_id, HOME=str(self.home), BFME_MOUNTINFO=str(self.tmp / "mountinfo"))
        if info:
            self.env["BFME_FLATPAK_INFO"] = str(self.tmp / "flatpak-info")
        else:
            self.env["BFME_FLATPAK_INFO"] = str(self.tmp / "no-such-file")

    def shortcuts(self):
        if not self.apps.is_dir():
            return []
        found = []
        for path in self.apps.glob(f"{self.app_id}.*.desktop"):
            found.append(self.SUFFIX[path.name[len(self.app_id) + 1:-len(".desktop")]])
        return sorted(found)

    def shortcut_text(self, program):
        suffix = {v: k for k, v in self.SUFFIX.items()}[program]
        return (self.apps / f"{self.app_id}.{suffix}.desktop").read_text()

    def with_launcher(self):
        self.make_prefix()
        self.install("launcher")
        self.assertEqual(self.run_script("shortcuts").returncode, 0)

    def test_it_runs_the_app_and_says_which_program_to_open(self):
        self.make_prefix()
        for program in self.PROGRAMS:
            self.install(program)
        self.run_script("shortcuts")
        for program in self.PROGRAMS:
            with self.subTest(program):
                text = self.shortcut_text(program)
                self.assertIn(f"Exec=flatpak run --command=bfme-installer {self.app_id} --open {program}\n", text)
                self.assertIn(f"Icon={self.app_id}.{EXPORT_SUFFIX[program]}\n", text)   # its own, not the app's
                self.assertIn(f"X-Flatpak={self.app_id}\n", text)
                self.assertTrue(text.startswith("[Desktop Entry]\nType=Application\n"))

    def test_every_program_has_a_different_icon_and_none_is_the_apps_own(self):
        self.make_prefix()
        for program in self.PROGRAMS:
            self.install(program)
        self.run_script("shortcuts")
        icons = {program: re.search(r"^Icon=(.*)$", self.shortcut_text(program), re.M).group(1) for program in self.PROGRAMS}
        self.assertEqual(len(set(icons.values())), 3)
        self.assertNotIn(self.app_id, icons.values())

    def test_the_icon_of_each_shortcut_is_the_one_the_manifest_exports_for_it(self):
        # Two files say the same name: the manifest installs the picture under it, and the script asks for it. If they drift
        # apart the menu shows a missing-icon box, and nothing else notices.
        self.sandbox(app_id=manifest_app_id())
        self.make_prefix()
        for program in self.PROGRAMS:
            self.install(program)
        self.assertEqual(self.run_script("shortcuts").returncode, 0)
        exported = {name for _width, _height, name in manifest_icon_exports().values()}
        used = {re.search(r"^Icon=(.*)$", self.shortcut_text(program), re.M).group(1) for program in self.PROGRAMS}
        self.assertEqual(used, exported)

    def test_a_copy_built_under_another_id_says_so_and_the_release_does_not(self):
        self.with_launcher()
        self.assertIn("Name=BFME All-in-One Launcher (Dev)\n", self.shortcut_text("launcher"))
        self.uninstall_everything()
        self.run_script("shortcuts")
        self.sandbox(app_id="com.jgbmichalski.BfmeInstaller")
        self.with_launcher()
        self.assertIn("Name=BFME All-in-One Launcher\n", self.shortcut_text("launcher"))

    def test_the_shortcut_hides_itself_when_the_app_is_uninstalled(self):
        # Flatpak removes the wrapper it exports for the app, and a desktop hides a shortcut whose TryExec is gone.
        self.with_launcher()
        self.assertIn(f"TryExec={self.wrapper}\n", self.shortcut_text("launcher"))

    def test_the_path_the_app_was_installed_under_wins_over_where_it_runs_from(self):
        self.sandbox(original=True)
        self.with_launcher()
        self.assertIn(f"TryExec={self.tmp}/elsewhere/exports/bin/{self.app_id}\n", self.shortcut_text("launcher"))

    def test_without_a_known_installation_the_shortcut_has_no_tryexec_and_still_works(self):
        self.sandbox(info=False)
        self.with_launcher()
        self.assertNotIn("TryExec", self.shortcut_text("launcher"))
        self.assertIn("Exec=flatpak run", self.shortcut_text("launcher"))

    def test_without_access_to_the_menu_folder_nothing_is_written_and_it_says_how_to_fix_that(self):
        self.sandbox(reachable=False)
        self.make_prefix()
        self.install("launcher")
        done = self.run_script("shortcuts")
        self.assertEqual(done.returncode, 1)
        self.assertIn("cannot reach your menu folder", done.stderr)
        self.assertIn(f"flatpak override --user --filesystem=xdg-data/applications:create {self.app_id}", done.stderr)
        self.assertEqual(self.shortcuts(), [])
        self.assertFalse(self.apps.exists())   # writing there would only have worked inside the sandbox

    def test_a_bigger_share_covers_the_menu_folder_too(self):
        # A player who gave the app their whole home folder has no mount for the menu folder, only one above it.
        for share in (self.home, self.home / ".local", self.home / ".local/share"):
            with self.subTest(share=str(share.relative_to(self.tmp))):
                self.uninstall_everything()
                self.run_script("shortcuts")
                self.sandbox(mounts=[share])
                self.with_launcher()
                self.assertEqual(self.shortcuts(), ["launcher"])

    def test_a_folder_that_only_looks_alike_does_not_cover_it(self):
        # .../share/app is not above .../share/applications.
        self.sandbox(mounts=[self.home / ".local/share/app", self.home / ".local/share/applications2", self.home / "x"])
        self.make_prefix()
        self.install("launcher")
        done = self.run_script("shortcuts")
        self.assertEqual(done.returncode, 1)
        self.assertIn("cannot reach your menu folder", done.stderr)

    def test_a_folder_shared_below_the_menu_folder_does_not_cover_it(self):
        self.sandbox(mounts=[self.apps / "sub"])
        self.make_prefix()
        self.install("launcher")
        self.assertEqual(self.run_script("shortcuts").returncode, 1)

    def test_a_home_folder_that_is_a_link_is_found_by_its_real_path(self):
        # On some systems (Silverblue, Bazzite) /home is a link to /var/home, and the sandbox lists real paths.
        real = self.tmp / "var-home"
        (real / ".local/share").mkdir(parents=True)
        link = self.tmp / "home-link"
        link.symlink_to(real)
        self.sandbox()
        self.env["HOME"] = str(link)
        self.apps = link / ".local/share/applications"
        (self.tmp / "mountinfo").write_text(
            "20 1 0:20 / / rw - tmpfs tmpfs rw\n" f"41 20 0:41 / {real}/.local/share/applications rw - ext4 /dev/sda1 rw\n")
        self.make_prefix()
        self.install("launcher")
        self.assertEqual(self.run_script("shortcuts").returncode, 0)
        self.assertTrue((real / ".local/share/applications" / f"{self.app_id}.Launcher.desktop").is_file())

    def test_a_menu_folder_with_a_space_in_its_path_is_found(self):
        spaced = self.tmp / "my home"
        spaced.mkdir()
        menu = spaced / ".local/share/applications"
        self.sandbox(mounts=[menu])   # written as \040 in the list, as the sandbox does
        self.env["HOME"] = str(spaced)
        self.apps = menu
        self.make_prefix()
        self.install("launcher")
        self.assertEqual(self.run_script("shortcuts").returncode, 0)
        self.assertEqual(self.shortcuts(), ["launcher"])

    def test_with_nothing_installed_the_menu_folder_is_not_needed(self):
        self.sandbox(reachable=False)
        done = self.run_script("shortcuts")
        self.assertEqual((done.returncode, done.stderr), (0, ""))

    def test_other_copies_and_the_script_outside_the_flatpak_are_left_alone(self):
        self.apps.mkdir(parents=True)
        others = {
            "bfme-launcher.desktop": "[Desktop Entry]\nName=From the script outside the Flatpak\n",
            "com.jgbmichalski.BfmeInstaller.Launcher.desktop": "[Desktop Entry]\nName=The release\n",
        }
        for name, text in others.items():
            (self.apps / name).write_text(text)
        self.with_launcher()
        self.uninstall_everything()
        self.run_script("shortcuts")   # this copy has nothing installed any more
        self.assertEqual({name: (self.apps / name).read_text() for name in others}, others)
        self.assertEqual(self.shortcuts(), [])


class Remove(ScriptCase):
    """`remove <program>` takes one program out of the game environment: its folder and its shortcut. Everything else stays:
    the other programs, the games the AIO Launcher installed, and the settings a program keeps in the player's own folder."""

    PROGRAMS = ("launcher", "arena", "aotr")

    def everything_installed(self):
        self.make_prefix()
        for program in self.PROGRAMS:
            self.install(program)
            (self.program_folder(program) / "settings.txt").write_text("the program's own files")
        self.make_games()
        self.aotr_user_data().parent.mkdir(parents=True, exist_ok=True)
        self.aotr_user_data().write_text("Resolution = 2560 1080")
        self.assertEqual(self.run_script("shortcuts").returncode, 0)

    def shortcuts(self):
        return sorted(p.name[len("bfme-"):-len(".desktop")] for p in self.apps.glob("bfme-*.desktop")) if self.apps.is_dir() else []

    def test_it_takes_the_programs_folder_and_shortcut_and_nothing_else(self):
        for gone in self.PROGRAMS:
            with self.subTest(gone):
                self.uninstall_everything()
                shutil.rmtree(self.prefix / "drive_c", ignore_errors=True)
                self.everything_installed()
                done = self.run_script("remove", gone)
                self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
                self.assertFalse(self.program_folder(gone).exists())
                kept = [p for p in self.PROGRAMS if p != gone]
                self.assertTrue(all((self.program_folder(p) / "settings.txt").is_file() for p in kept))
                self.assertEqual(self.shortcuts(), sorted(kept))
                # the games, and what Age of the Ring keeps in the player's folder, were never part of a program
                self.assertTrue((self.prefix / "drive_c/BFME2/lotrbfme2.exe").is_file())
                self.assertTrue((self.prefix / "drive_c/RotWK/lotrbfme2ep1.exe").is_file())
                self.assertEqual(self.aotr_user_data().read_text(), "Resolution = 2560 1080")

    def test_the_status_is_reported_for_a_program_that_runs_several_jobs(self):
        self.everything_installed()
        done = self.run_script("remove", "launcher")
        lines = self.status_lines(done)
        self.assertEqual(lines[-1], "@bfme DONE")
        reported = dict(line.split(" ", 3)[2:] for line in lines if line.startswith("@bfme STATUS "))
        self.assertEqual((reported["launcher"], reported["arena"], reported["aotr"], reported["complete"]),
                         ("missing", "installed", "installed", "yes"))
        self.assertEqual((reported["bfme2"], reported["rotwk"]), ("installed", "installed"))
        self.assertEqual(reported, self.status())

    def test_removing_the_last_program_leaves_a_ready_environment_that_is_not_complete(self):
        self.make_prefix()
        self.install("aotr")
        self.run_script("shortcuts")
        self.assertEqual(self.run_script("remove", "aotr").returncode, 0)
        status = self.status()
        self.assertEqual((status["prefix"], status["aotr"], status["complete"]), ("ready", "missing", "no"))
        self.assertEqual(self.shortcuts(), [])

    def test_it_can_be_run_again_and_for_a_program_that_is_not_there(self):
        self.make_prefix()
        for _ in range(2):
            done = self.run_script("remove", "arena")
            self.assertEqual((done.returncode, self.status_lines(done)[-1]), (0, "@bfme DONE"))

    def test_a_half_installed_program_is_cleaned_up_as_well(self):
        # An interrupted install leaves a marker and a partial folder: not installed, but not nothing either.
        self.make_prefix()
        self.install("aotr")
        (self.prefix / ".bfme-aotr-installing").write_text("")
        (self.base / "downloads/aotr").mkdir(parents=True)
        (self.base / "downloads/aotr/part-1a.bin").write_text("15 GB of unpacked files, in real life")
        self.assertEqual(self.run_script("remove", "aotr").returncode, 0)
        self.assertEqual([self.program_folder("aotr").exists(), (self.prefix / ".bfme-aotr-installing").exists(),
                          (self.base / "downloads/aotr").exists()], [False, False, False])

    def test_the_arena_takes_its_leftover_download_with_it_and_the_aio_launcher_its_setup(self):
        self.make_prefix()
        self.install("arena")
        self.install("launcher")
        downloads = self.base / "downloads"
        downloads.mkdir(parents=True)
        for name in ("OnlineArena.exe.part", "AllInOneLauncherSetup.exe", "umu-launcher.tar", "Proton.tar.gz"):
            (downloads / name).write_text("x")
        self.run_script("remove", "arena")
        self.run_script("remove", "launcher")
        # what belongs to the runner stays: every program needs it
        self.assertEqual(sorted(p.name for p in downloads.iterdir()), ["Proton.tar.gz", "umu-launcher.tar"])

    def test_a_name_that_is_not_a_program_deletes_nothing(self):
        self.everything_installed()
        for name in ("everything", "prefix", "../x", "BFME2", "Launcher", ""):
            with self.subTest(name):
                done = self.run_script("remove", name) if name else self.run_script("remove")
                self.assertEqual(done.returncode, 1)
                self.assertTrue(self.status_lines(done)[-1].startswith("@bfme ERROR - Use: remove launcher|arena|aotr"))
        self.assertTrue(all(self.program_folder(p).is_dir() for p in self.PROGRAMS))
        self.assertTrue((self.prefix / "drive_c/BFME2").is_dir())

    def test_a_setup_that_is_running_blocks_it(self):
        self.everything_installed()
        self.base.mkdir(parents=True, exist_ok=True)
        with open(self.base / ".setup.lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            done = self.run_script("remove", "launcher")
        self.assertEqual(done.returncode, 1)
        self.assertIn("Another setup is already running", done.stdout + done.stderr)
        self.assertTrue(self.program_folder("launcher").is_dir())

    def test_the_wine_session_ends_before_anything_is_deleted(self):
        # A program that is still open would lose its files under it, and Wine would write its registry back afterwards.
        self.everything_installed()
        server = self.tmp / "xdg/umu/compatibilitytools/fake-proton/files/bin/wineserver"
        server.parent.mkdir(parents=True)
        server.write_text('#!/usr/bin/env bash\necho "$1 folder_still_there=$([ -d "$FAKE_TARGET" ] && echo yes || echo no)" >> "$WINESERVER_LOG"\n')
        server.chmod(0o755)
        self.env.update(FAKE_TARGET=str(self.program_folder("aotr")), WINESERVER_LOG=str(self.tmp / "wineserver.log"))
        self.assertEqual(self.run_script("remove", "aotr").returncode, 0)
        self.assertEqual((self.tmp / "wineserver.log").read_text().split("\n")[:-1],
                         ["-k folder_still_there=yes", "-w folder_still_there=yes"])
        self.assertFalse(self.program_folder("aotr").exists())

    def test_it_is_in_the_help_and_the_text_output_has_no_status_lines(self):
        self.assertIn("remove <program>", self.run_script("help", machine=False).stdout)
        self.everything_installed()
        plain = self.run_script("remove", "arena", machine=False)
        self.assertIn("Removed BFME Online Arena.", plain.stdout)
        self.assertNotIn("@bfme", plain.stdout)


class Graphics(ScriptCase):
    """`graphics` saves the renderer in config.env, so the shortcuts and the next setup run use it too."""

    def test_the_default_is_vulkan(self):
        self.assertEqual(self.status()["graphics"], "vulkan")

    def test_switching_to_opengl_is_saved_and_reported(self):
        done = self.run_script("graphics", "opengl")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.status()["graphics"], "opengl")
        self.assertIn("BFME_GRAPHICS=opengl", (self.base / "config.env").read_text())
        self.assertIn("@bfme DONE", self.status_lines(done))

    def test_switching_back_and_forth_keeps_one_line_and_the_other_settings(self):
        (self.base).mkdir(parents=True)
        (self.base / "config.env").write_text("BFME_NVIDIA=1\n# keep me\nBFME_GRAPHICS=vulkan\n")
        for value in ("opengl", "vulkan", "opengl"):
            self.assertEqual(self.run_script("graphics", value).returncode, 0)
        text = (self.base / "config.env").read_text()
        self.assertEqual(text.count("BFME_GRAPHICS="), 1)
        self.assertIn("BFME_NVIDIA=1", text)
        self.assertIn("# keep me", text)
        self.assertIn("BFME_GRAPHICS=opengl", text)

    def test_with_a_ready_environment_the_settings_are_applied_again(self):
        self.make_prefix()
        done = self.run_script("graphics", "opengl")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue((self.prefix / ".bfme-settings-v4").is_file())
        self.assertTrue((self.base / "logs/prefix-settings.log").is_file())

    def test_an_unknown_value_is_refused_and_changes_nothing(self):
        done = self.run_script("graphics", "direct3d")
        self.assertEqual(done.returncode, 1)
        self.assertIn("Use: graphics vulkan|opengl", self.status_lines(done)[0])
        self.assertFalse((self.base / "config.env").exists())

    def test_asking_without_a_value_shows_the_backend_and_how_to_change_it(self):
        done = self.run_script("graphics", machine=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("Graphics: Vulkan (DXVK)", done.stdout)
        self.assertIn("graphics vulkan|opengl", done.stdout)

    def test_the_text_output_and_help_name_it(self):
        self.make_prefix()
        plain = self.run_script("status", machine=False)
        self.assertIn("Graphics:   Vulkan (DXVK)", plain.stdout)
        self.assertIn("graphics [vulkan|opengl]", self.run_script("help", machine=False).stdout)


class Jobs(ScriptCase):
    def test_age_of_the_ring_asks_only_for_the_game_environment(self):
        done = self.run_script("aotr-install", str(self.tmp / "AotR_Standalone_9.3.0_Installer.zip"))
        self.assertEqual(done.returncode, 1)
        self.assertEqual(self.status_lines(done), ["@bfme ERROR - Set up the game environment first. Run: prepare"])

    def test_the_launcher_job_asks_for_the_game_environment_too(self):
        # Without it the job would build Proton and the environment inside its "launcher" step, with no system checks.
        done = self.run_script("launcher-install")
        self.assertEqual(done.returncode, 1)
        self.assertEqual(self.status_lines(done), ["@bfme ERROR - Set up the game environment first. Run: prepare"])
        self.assertEqual(self.status()["prefix"], "missing")   # and it built nothing

    def test_age_of_the_ring_asks_for_the_file(self):
        self.make_prefix()
        done = self.run_script("aotr-install")
        self.assertEqual(done.returncode, 1)
        self.assertTrue(self.status_lines(done)[0].startswith("@bfme ERROR - Use: aotr-install <path"))

    def test_the_launcher_job_installs_the_aio_launcher_and_the_arena_reports_where_things_stand_and_can_run_again(self):
        self.make_prefix()
        done = self.run_script("launcher-install")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        lines = self.status_lines(done)
        steps = [line for line in lines if line.startswith("@bfme STEP ")]
        self.assertEqual(steps, [
            "@bfme STEP launcher start", "@bfme STEP launcher done", "@bfme STEP arena start", "@bfme STEP arena done",
            "@bfme STEP shortcuts start", "@bfme STEP shortcuts done",
        ])
        # Before DONE it reports what is installed, so multi-job programs need not ask again.
        self.assertEqual(lines[-1], "@bfme DONE")
        reported = dict(line.split(" ", 3)[2:] for line in lines if line.startswith("@bfme STATUS "))
        self.assertEqual((reported["launcher"], reported["arena"], reported["aotr"], reported["complete"]),
                         ("installed", "installed", "missing", "yes"))
        self.assertEqual(reported, self.status())
        self.assertEqual(self.entries(), ["bfme-arena.desktop", "bfme-launcher.desktop"])
        # A retry or resume does not install the AIO Launcher twice.
        self.assertIn("@bfme STEP launcher skip", self.status_lines(self.run_script("launcher-install")))

    def test_the_help_says_aio_launcher_where_it_means_that_program_and_not_the_other_launcher(self):
        text = self.run_script("help", machine=False).stdout
        self.assertIn("Everything for the AIO Launcher and the Arena", text)
        self.assertIn("not from the AIO Launcher's Multiplayer tab", text)
        self.assertIn("Start the Age of the Ring Launcher", text)       # the other launcher keeps the name it has

    def test_starting_the_aio_launcher_from_a_terminal_says_which_launcher_it_is(self):
        self.make_prefix()
        self.install("launcher")
        proc = self.run_script("launcher", machine=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Starting the AIO Launcher. Log: ", proc.stdout)
        self.assertNotIn("Starting launcher", proc.stdout)
        # The key still names the log files: Troubleshoot and the diagnostics look for them by it.
        self.assertTrue(list((self.base / "logs").glob("launcher-*.log")))

    def test_what_the_terminal_says_while_it_installs_names_the_aio_launcher(self):
        self.make_prefix()
        proc = self.run_script("launcher-install", machine=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Installing the AIO Launcher. ", proc.stdout)
        self.assertIn("Do not switch patches in the AIO Launcher after a game is installed.", proc.stdout)

    def test_the_other_programs_are_started_with_the_words_they_had(self):
        self.make_prefix()
        self.install("aotr")
        proc = self.run_script("aotr", machine=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Starting aotr. Log: ", proc.stdout)

    def test_a_game_that_is_not_there_sends_the_player_to_the_aio_launcher_by_name(self):
        self.make_prefix()
        proc = self.run_script("game", "bfme2", machine=False)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("Install it in the AIO Launcher first.", proc.stdout + proc.stderr)

    def test_the_commands_are_in_the_help(self):
        text = self.run_script("help", machine=False).stdout
        for command in ("prepare ", "launcher-install ", "install ", "aotr-install <zip>"):
            self.assertIn(command, text)

    @unittest.skipUnless(HAVE_SEVENZIP, "7-Zip is needed to read the Age of the Ring download")
    def test_age_of_the_ring_installs_into_a_bare_game_environment(self):
        # Only the environment (`prepare`) is needed, not the AIO Launcher or Arena.
        self.make_prefix()
        source = self.tmp / "zip-source"
        source.mkdir()
        (source / "AotR_Standalone_9.3.0_Installer.exe").write_text("installer")
        (source / "AotR_Standalone_9.3.0_Installer-1a.bin").write_bytes(os.urandom(2048))
        zip_path = self.tmp / "AotR_Standalone_9.3.0_Installer.zip"
        seven = next(shutil.which(c) for c in ("7zz", "7z", "7za") if shutil.which(c))
        subprocess.run([seven, "a", "-bso0", "-bsp0", str(zip_path), "."], cwd=source, check=True)
        done = self.run_script("aotr-install", str(zip_path))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        lines = self.status_lines(done)
        self.assertEqual([line for line in lines if line.startswith("@bfme STEP ") and line.endswith(" done")],
                         ["@bfme STEP aotr-check done", "@bfme STEP aotr-unpack done", "@bfme STEP aotr-install done",
                          "@bfme STEP aotr-settings done"])
        self.assertEqual(lines[-1], "@bfme DONE")
        status = self.status()
        self.assertEqual((status["aotr"], status["launcher"], status["arena"], status["complete"]),
                         ("installed", "missing", "missing", "yes"))
        self.assertEqual(self.entries(), ["bfme-aotr.desktop"])


class Tools(ScriptCase):
    FILES = {
        "workshop": "drive_c/BFME Tools/Workshop Studio/WorkshopStudio.exe",
        "mission-control": "drive_c/BFME Tools/Mission Control/MissionControl.exe",
    }
    STEPS = {
        "workshop": ["workshop"], "mission-control": ["mission-control"],
    }

    def test_each_tool_installs_reports_its_steps_and_counts_as_installed(self):
        for tool, steps in self.STEPS.items():
            with self.subTest(tool):
                self.make_prefix()
                done = self.run_script("tool-install", tool)
                self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
                lines = self.status_lines(done)
                self.assertEqual([l for l in lines if l.startswith("@bfme STEP ") and l.endswith(" done")],
                                 [f"@bfme STEP {s} done" for s in steps])
                self.assertEqual(lines[-1], "@bfme DONE")
                self.assertTrue((self.prefix / self.FILES[tool]).is_file())
                self.assertEqual(self.status()[tool], "installed")

    def test_a_tool_alone_does_not_make_the_setup_complete(self):
        self.make_prefix()
        self.run_script("tool-install", "workshop")
        self.assertEqual(self.status()["complete"], "no")

    def test_it_asks_for_the_game_environment_and_a_known_tool(self):
        done = self.run_script("tool-install", "workshop")
        self.assertEqual(done.returncode, 1)
        self.assertEqual(self.status_lines(done), ["@bfme ERROR - Set up the game environment first. Run: prepare"])
        self.make_prefix()
        done = self.run_script("tool-install", "bogus")
        self.assertEqual(done.returncode, 1)
        self.assertIn("Use: tool-install", self.status_lines(done)[0])

    def test_a_tool_that_is_not_installed_does_not_start(self):
        self.make_prefix()
        done = self.run_script("tool", "workshop")
        self.assertEqual(done.returncode, 1)
        self.assertIn("is not installed", done.stderr)

    def test_remove_takes_only_that_tool(self):
        self.make_prefix()
        self.install("launcher")
        for tool in self.FILES:
            self.assertEqual(self.run_script("tool-install", tool).returncode, 0)
        done = self.run_script("remove", "workshop")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        status = self.status()
        self.assertEqual((status["workshop"], status["mission-control"], status["launcher"]),
                         ("missing", "installed", "installed"))


if __name__ == "__main__":
    unittest.main()
