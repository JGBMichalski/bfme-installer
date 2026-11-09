"""engine.games: where each game's files, settings and maps are."""

from pathlib import Path

import pytest

from bfme_wizard.engine.games import GAMES
from bfme_wizard.engine.paths import Paths

PATHS = Paths(Path("/b"))
AOTR_GAMES = GAMES[3]
ROAMING = Path("/b/prefix/drive_c/users/steamuser/AppData/Roaming")


def test_the_games_in_order_and_then_age_of_the_ring():
    names = []

    for game in GAMES:
        names.append(game.name)

    assert names == ["BFME", "BFME 2", "Rise of the Witch-king", "Age of the Ring"]


def test_a_game_and_its_user_data():
    bfme2 = GAMES[1]
    assert bfme2.game_dir(PATHS) == Path("/b/prefix/drive_c/BFME2")
    assert bfme2.user_data(PATHS) == ROAMING / "My Battle for Middle-earth II Files"


def test_age_of_the_ring_keeps_everything_apart_from_the_games():
    # Seen in a real install: its own game copies in C:\AgeoftheRing, and its settings and maps in AppData\Roaming\Age of
    # the Ring (the registry's UserDataLeafName for its Rise of the Witch-king copy). No "My ... Files" folder is made.
    assert AOTR_GAMES.key == "aotr-games"
    assert AOTR_GAMES.installed_by == "aotr"
    assert AOTR_GAMES.game_dir(PATHS) == Path("/b/prefix/drive_c/AgeoftheRing")
    assert AOTR_GAMES.user_data(PATHS) == ROAMING / "Age of the Ring"
    assert AOTR_GAMES.maps_folder == "maps"  # lowercase: the folder the Age of the Ring Launcher made

    for game in GAMES[:3]:
        assert game.maps_folder == "Maps"


def test_age_of_the_ring_is_found_through_its_own_folders_only(tmp_path):
    paths = Paths(tmp_path)
    assert not AOTR_GAMES.has_folders(paths)
    (paths.drive_c / "RotWK").mkdir(parents=True)  # the regular game is not Age of the Ring
    assert not AOTR_GAMES.has_folders(paths)
    AOTR_GAMES.game_dir(paths).mkdir(parents=True)
    assert AOTR_GAMES.has_folders(paths)
    assert not AOTR_GAMES.installed(paths)
    (AOTR_GAMES.game_dir(paths) / "AotR_Launcher.exe").write_text("x")
    assert AOTR_GAMES.installed(paths)  # its copies come with its launcher


def test_a_game_has_folders_once_its_folder_exists_and_is_installed_once_its_program_is_there(tmp_path):
    paths = Paths(tmp_path)
    rotwk = GAMES[2]
    assert not rotwk.has_folders(paths)
    rotwk.game_dir(paths).mkdir(parents=True)
    assert rotwk.has_folders(paths)
    assert not rotwk.installed(paths)
    (rotwk.game_dir(paths) / "lotrbfme2ep1.exe").write_text("x")
    assert rotwk.installed(paths)


def test_maps_target_falls_back(tmp_path):
    paths = Paths(tmp_path)
    game = GAMES[1]
    game.game_dir(paths).mkdir(parents=True)
    assert game.maps_target(paths) == game.game_dir(paths)
    game.user_data(paths).mkdir(parents=True)
    assert game.maps_target(paths) == game.user_data(paths)
    (game.user_data(paths) / "Maps").mkdir()
    assert game.maps_target(paths) == game.user_data(paths) / "Maps"


@pytest.mark.parametrize("index,key,folder", [(0, "bfme1", "BFME1"), (1, "bfme2", "BFME2"), (2, "rotwk", "RotWK")])
def test_each_game_folder(index, key, folder):
    game = GAMES[index]

    assert game.key == key
    assert game.game_dir(PATHS) == Path("/b/prefix/drive_c") / folder
