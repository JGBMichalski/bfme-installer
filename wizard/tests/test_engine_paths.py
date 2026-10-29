"""engine.paths: the same folders the setup script uses."""
import subprocess
from pathlib import Path

import pytest

from bfme_wizard.engine.paths import data_dir, menu_dir, paths

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "bfme-linux-setup.sh"


def test_data_dir():
    assert data_dir({"BFME_HOME": "/x/y", "XDG_DATA_HOME": "/d"}) == Path("/x/y")
    assert data_dir({"XDG_DATA_HOME": "/d"}) == Path("/d/bfme-installer")
    assert data_dir({"HOME": "/h"}) == Path("/h/.local/share/bfme-installer")


def test_the_menu_folder_is_the_hosts_even_in_the_flatpak():
    assert menu_dir({"HOME": "/h", "XDG_DATA_HOME": "/h/.var/app/x/data"}) == Path("/h/.local/share/applications")


def test_proton_layout():
    p = paths({"BFME_HOME": "/b"})
    assert p.config == Path("/b/config.env")
    assert p.downloads == Path("/b/downloads")
    assert p.logs == Path("/b/logs")
    assert p.prefix == Path("/b/prefix")
    assert p.aotr_unpack == Path("/b/downloads/aotr")
    roaming = "/b/prefix/drive_c/users/steamuser/AppData/Roaming"
    assert p.aio_launcher_exe == Path(f"{roaming}/BFME All In One Launcher/AllInOneLauncher.exe")
    assert p.arena_exe == Path(f"{roaming}/BFME Competetive Arena/BfmeFoundationProject_OnlineArena.exe")
    assert p.aotr_exe == Path("/b/prefix/drive_c/AgeoftheRing/AotR_Launcher.exe")
    assert p.tool_exe("workshop") == Path("/b/prefix/drive_c/BFME Tools/Workshop Studio/WorkshopStudio.exe")
    assert p.tool_exe("mission-control") == Path("/b/prefix/drive_c/BFME Tools/Mission Control/MissionControl.exe")


# The game folders

def test_the_games_in_order_and_then_age_of_the_ring():
    assert [g.name for g in paths({"BFME_HOME": "/b"}).game_folders()] == \
        ["BFME", "BFME 2", "Rise of the Witch-king", "Age of the Ring"]


def test_a_game_and_its_user_data():
    bfme2 = paths({"BFME_HOME": "/b"}).game_folders()[1]
    assert bfme2.game == Path("/b/prefix/drive_c/BFME2")
    assert bfme2.user_data == Path("/b/prefix/drive_c/users/steamuser/AppData/Roaming/My Battle for Middle-earth II Files")


def test_age_of_the_ring_keeps_everything_apart_from_the_games():
    # Seen in a real install: its own game copies in C:\AgeoftheRing, and its settings and maps in AppData\Roaming\Age of
    # the Ring (the registry's UserDataLeafName for its Rise of the Witch-king copy). No "My ... Files" folder is made.
    folders = paths({"BFME_HOME": "/b"}).game_folders()
    aotr = folders[3]
    assert aotr.key == "aotr"
    assert aotr.game == Path("/b/prefix/drive_c/AgeoftheRing")
    assert aotr.user_data == Path("/b/prefix/drive_c/users/steamuser/AppData/Roaming/Age of the Ring")
    assert aotr.maps_dir == "maps"                       # lowercase: the folder the Age of the Ring Launcher made
    assert {g.maps_dir for g in folders[:3]} == {"Maps"}


def test_age_of_the_ring_is_found_through_its_own_folders_only(tmp_path):
    p = paths({"BFME_HOME": str(tmp_path)})
    aotr = p.game_folders()[3]
    assert not aotr.installed
    (tmp_path / "prefix/drive_c/RotWK").mkdir(parents=True)    # the regular game is not Age of the Ring
    assert not p.game_folders()[3].installed
    aotr.game.mkdir(parents=True)
    assert p.game_folders()[3].installed
    assert aotr.maps_target() == aotr.game
    aotr.user_data.mkdir(parents=True)
    assert aotr.maps_target() == aotr.user_data
    (aotr.user_data / "maps").mkdir()
    assert aotr.maps_target() == aotr.user_data / "maps"


def test_not_installed_until_the_folder_exists(tmp_path):
    p = paths({"BFME_HOME": str(tmp_path)})
    assert not p.game_folders()[2].installed
    (tmp_path / "prefix/drive_c/RotWK").mkdir(parents=True)
    assert p.game_folders()[2].installed


def test_maps_target_falls_back(tmp_path):
    g = paths({"BFME_HOME": str(tmp_path)}).game_folders()[1]
    g.game.mkdir(parents=True)
    assert g.maps_target() == g.game
    g.user_data.mkdir(parents=True)
    assert g.maps_target() == g.user_data
    (g.user_data / "Maps").mkdir()
    assert g.maps_target() == g.user_data / "Maps"


# Parity with the setup script: a file at each path here is what its `status` looks for.

def script_status(base):
    env = {"BFME_HOME": str(base), "PATH": "/usr/bin:/bin", "HOME": str(base)}
    out = subprocess.run([str(SCRIPT), "--machine", "status"], env=env, capture_output=True, text=True, timeout=60).stdout
    return dict(line.split(" ", 3)[2:] for line in out.splitlines() if line.startswith("@bfme STATUS "))


@pytest.mark.parametrize("program", ["aio-launcher", "arena", "aotr", "workshop", "mission-control"])
def test_the_script_finds_each_program_where_the_engine_puts_it(tmp_path, program):
    p = paths({"BFME_HOME": str(tmp_path)})

    if program == "aio-launcher":
        exe = p.aio_launcher_exe
    elif program == "arena":
        exe = p.arena_exe
    elif program == "aotr":
        exe = p.aotr_exe
    else:
        exe = p.tool_exe(program)

    # The setup script calls the AIO Launcher "launcher".
    key = "launcher" if program == "aio-launcher" else program

    assert script_status(tmp_path)[key] == "missing"
    exe.parent.mkdir(parents=True)
    exe.write_text("x")
    assert script_status(tmp_path)[key] == "installed"


@pytest.mark.parametrize("index,key,exe", [(0, "bfme1", "lotrbfme.exe"), (1, "bfme2", "lotrbfme2.exe"),
                                           (2, "rotwk", "lotrbfme2ep1.exe")])
def test_the_script_finds_each_game_in_the_engines_game_folder(tmp_path, index, key, exe):
    game = paths({"BFME_HOME": str(tmp_path)}).game_folders()[index]
    assert game.key == key
    game.game.mkdir(parents=True)
    (game.game / exe).write_text("x")
    assert script_status(tmp_path)[key] == "installed"


def test_the_script_uses_the_engines_prefix(tmp_path):
    p = paths({"BFME_HOME": str(tmp_path)})
    for folder in ("drive_c/windows", "drive_c/users/steamuser"):
        (p.prefix / folder).mkdir(parents=True)
    assert script_status(tmp_path)["prefix"] == "ready"
