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
from types import SimpleNamespace
from pathlib import Path

import pytest

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


@pytest.fixture
def box(tmp_path):
    """A temporary home folder with a fake `flatpak` first on the PATH that only logs what it was asked."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "flatpak"
    fake.write_text('#!/usr/bin/env bash\necho "$*" >> "$FLATPAK_LOG"\nexit 0\n')
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    home = tmp_path / "home"
    apps = home / ".local/share/applications"
    apps.mkdir(parents=True)
    log = tmp_path / "flatpak.log"
    env = {k: v for k, v in os.environ.items() if k not in ("XDG_DATA_HOME", "FLATPAK_ID")}
    env.update(HOME=str(home), PATH=f"{bin_dir}:{os.environ['PATH']}", FLATPAK_LOG=str(log))
    return SimpleNamespace(tmp=tmp_path, home=home, apps=apps, log=log, env=env)


def put(folder, names):
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_text(f"[Desktop Entry]\nName={name}\n")


def uninstall(box, *options, env=None):
    return subprocess.run([str(INSTALLER), "--uninstall", *options], env=env or box.env,
                          capture_output=True, text=True, timeout=60)


def names(folder):
    return sorted(p.name for p in folder.iterdir())


def test_the_apps_shortcuts_go_with_the_app_and_nothing_else_does(box):
    put(box.apps, SHORTCUTS + BYSTANDERS)
    done = uninstall(box)
    assert done.returncode == 0, done.stderr
    assert names(box.apps) == sorted(BYSTANDERS)
    assert "Removed the app's shortcuts" in done.stdout


def test_the_app_is_uninstalled_too(box):
    put(box.apps, SHORTCUTS)
    uninstall(box)
    assert f"uninstall --user -y --noninteractive {APP_ID}" in box.log.read_text()


def test_one_shortcut_alone_is_removed_and_the_others_are_not_invented(box):
    put(box.apps, SHORTCUTS[1:2] + BYSTANDERS)   # only the Arena's
    uninstall(box)
    assert names(box.apps) == sorted(BYSTANDERS)


def test_with_nothing_to_remove_it_says_nothing_about_shortcuts_and_still_succeeds(box):
    put(box.apps, BYSTANDERS)
    done = uninstall(box)
    assert done.returncode == 0, done.stderr
    assert "shortcuts" not in done.stdout
    assert names(box.apps) == sorted(BYSTANDERS)


def test_a_computer_without_a_menu_folder_is_fine(box):
    shutil.rmtree(box.home / ".local")
    assert uninstall(box).returncode == 0


def test_a_menu_folder_somewhere_else_is_found_through_xdg_data_home(box):
    elsewhere = box.tmp / "elsewhere"
    put(elsewhere / "applications", SHORTCUTS + BYSTANDERS)
    put(box.apps, SHORTCUTS)                        # the usual place is not the one in use here
    uninstall(box, env={**box.env, "XDG_DATA_HOME": str(elsewhere)})
    assert names(elsewhere / "applications") == sorted(BYSTANDERS)
    assert names(box.apps) == sorted(SHORTCUTS)


def test_a_shortcut_that_is_a_link_is_removed_without_touching_what_it_points_at(box):
    # Something that links the entry (a launcher that was pinned, say) leaves the target alone.
    target = box.tmp / "precious.desktop"
    target.write_text("keep me")
    (box.apps / SHORTCUTS[0]).symlink_to(target)
    uninstall(box)
    assert not ((box.apps / SHORTCUTS[0]).exists() or (box.apps / SHORTCUTS[0]).is_symlink())
    assert target.read_text() == "keep me"


def test_the_data_is_kept_unless_asked_and_the_shortcuts_go_either_way(box):
    data = box.home / ".var/app" / APP_ID
    put(data, ["setup.txt"])
    put(box.apps, SHORTCUTS)
    uninstall(box)
    assert data.exists()
    put(box.apps, SHORTCUTS)
    uninstall(box, "--purge")
    assert (data.exists(), names(box.apps)) == (False, [])
