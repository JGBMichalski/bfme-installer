"""`install-flatpak.sh --uninstall` takes the app's shortcuts out of the menu folder with the app.

The app is not the one that exports them (it writes them itself, when a program is installed), so Flatpak does not
remove them when the app is uninstalled. The script runs for real in a temporary home folder with a fake `flatpak` in
front, so nothing is uninstalled and nothing outside the temporary folder is touched. What matters most here is what it
must NOT delete: it is deleting files in the player's menu folder.
"""
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

INSTALLER = Path(__file__).resolve().parents[2] / "flatpak" / "install-flatpak.sh"
APP_ID = "com.jgbmichalski.BfmeInstaller"
SHORTCUTS = [f"{APP_ID}.{program}.desktop" for program in ("Launcher", "Arena", "Aotr")]
# Files in the same folder that belong to somebody else, or to another copy of the app. None may go.
BYSTANDERS = [
    "com.jgbmichalski.BfmeInstallerDev.Launcher.desktop",   # a build made by dev/install-local.sh
    "com.jgbmichalski.BfmeInstaller.desktop",                # the app's own entry (Flatpak exports it, not the app)
    "bfme-launcher.desktop",                                  # written by the script outside the Flatpak
    "firefox.desktop",
]


class Uninstall(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "flatpak"
        fake.write_text('#!/usr/bin/env bash\necho "$*" >> "$FLATPAK_LOG"\nexit 0\n')
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        self.home = self.tmp / "home"
        self.apps = self.home / ".local/share/applications"
        self.apps.mkdir(parents=True)
        self.log = self.tmp / "flatpak.log"
        self.env = {k: v for k, v in os.environ.items() if k not in ("XDG_DATA_HOME", "FLATPAK_ID")}
        self.env.update(HOME=str(self.home), PATH=f"{bin_dir}:{os.environ['PATH']}", FLATPAK_LOG=str(self.log))

    def put(self, folder, names):
        folder.mkdir(parents=True, exist_ok=True)
        for name in names:
            (folder / name).write_text(f"[Desktop Entry]\nName={name}\n")

    def uninstall(self, *options, env=None):
        return subprocess.run([str(INSTALLER), "--uninstall", *options], env=env or self.env,
                              capture_output=True, text=True, timeout=60)

    def names(self, folder=None):
        return sorted(p.name for p in (folder or self.apps).iterdir())

    def test_the_apps_shortcuts_go_with_the_app_and_nothing_else_does(self):
        self.put(self.apps, SHORTCUTS + BYSTANDERS)
        done = self.uninstall()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.names(), sorted(BYSTANDERS))
        self.assertIn("Removed the app's shortcuts", done.stdout)

    def test_the_app_is_uninstalled_too(self):
        self.put(self.apps, SHORTCUTS)
        self.uninstall()
        self.assertIn(f"uninstall --user -y --noninteractive {APP_ID}", self.log.read_text())

    def test_one_shortcut_alone_is_removed_and_the_others_are_not_invented(self):
        self.put(self.apps, SHORTCUTS[1:2] + BYSTANDERS)   # only the Arena's
        self.uninstall()
        self.assertEqual(self.names(), sorted(BYSTANDERS))

    def test_with_nothing_to_remove_it_says_nothing_about_shortcuts_and_still_succeeds(self):
        self.put(self.apps, BYSTANDERS)
        done = self.uninstall()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("shortcuts", done.stdout)
        self.assertEqual(self.names(), sorted(BYSTANDERS))

    def test_a_computer_without_a_menu_folder_is_fine(self):
        shutil.rmtree(self.home / ".local")
        self.assertEqual(self.uninstall().returncode, 0)

    def test_a_menu_folder_somewhere_else_is_found_through_xdg_data_home(self):
        elsewhere = self.tmp / "elsewhere"
        self.put(elsewhere / "applications", SHORTCUTS + BYSTANDERS)
        self.put(self.apps, SHORTCUTS)                        # the usual place is not the one in use here
        self.uninstall(env={**self.env, "XDG_DATA_HOME": str(elsewhere)})
        self.assertEqual(self.names(elsewhere / "applications"), sorted(BYSTANDERS))
        self.assertEqual(self.names(), sorted(SHORTCUTS))

    def test_a_shortcut_that_is_a_link_is_removed_without_touching_what_it_points_at(self):
        # Something that links the entry (a launcher that was pinned, say) leaves the target alone.
        target = self.tmp / "precious.desktop"
        target.write_text("keep me")
        (self.apps / SHORTCUTS[0]).symlink_to(target)
        self.uninstall()
        self.assertFalse((self.apps / SHORTCUTS[0]).exists() or (self.apps / SHORTCUTS[0]).is_symlink())
        self.assertEqual(target.read_text(), "keep me")

    def test_the_data_is_kept_unless_asked_and_the_shortcuts_go_either_way(self):
        data = self.home / ".var/app" / APP_ID
        self.put(data, ["setup.txt"])
        self.put(self.apps, SHORTCUTS)
        self.uninstall()
        self.assertTrue(data.exists())
        self.put(self.apps, SHORTCUTS)
        self.uninstall("--purge")
        self.assertEqual((data.exists(), self.names()), (False, []))


if __name__ == "__main__":
    unittest.main()
