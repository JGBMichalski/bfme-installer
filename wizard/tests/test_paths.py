from pathlib import Path

from bfme_wizard.paths import game_folders, prefix_dir, wine_user


def test_proton_layout():
    env = {"BFME_HOME": "/b"}
    assert prefix_dir(env) == Path("/b/prefix")
    assert wine_user(env) == "steamuser"
    bfme2 = game_folders(env)[1]
    assert bfme2.game == Path("/b/prefix/drive_c/BFME2")
    assert bfme2.user_data == Path("/b/prefix/drive_c/users/steamuser/AppData/Roaming/My Battle for Middle-earth II Files")


def test_wine_layout_uses_the_login_name():
    env = {"BFME_HOME": "/b", "BFME_RUNNER": "wine", "USER": "ann"}
    assert prefix_dir(env) == Path("/b/wineprefix")
    assert "users/ann/" in str(game_folders(env)[0].user_data)


def test_the_games_in_order_and_then_age_of_the_ring():
    assert [g.name for g in game_folders({"BFME_HOME": "/b"})] == \
        ["BFME", "BFME 2", "Rise of the Witch-king", "Age of the Ring"]


def test_age_of_the_ring_keeps_everything_apart_from_the_games():
    # Seen in a real install: its own game copies in C:\AgeoftheRing, and its settings and maps in AppData\Roaming\Age of
    # the Ring (the registry's UserDataLeafName for its Rise of the Witch-king copy). No "My ... Files" folder is made.
    aotr = game_folders({"BFME_HOME": "/b"})[3]
    assert aotr.key == "aotr"
    assert aotr.game == Path("/b/prefix/drive_c/AgeoftheRing")
    assert aotr.user_data == Path("/b/prefix/drive_c/users/steamuser/AppData/Roaming/Age of the Ring")
    assert aotr.maps_dir == "maps"                       # lowercase: the folder the launcher made
    assert {g.maps_dir for g in game_folders({"BFME_HOME": "/b"})[:3]} == {"Maps"}


def test_age_of_the_ring_is_found_through_its_own_folders_only(tmp_path):
    env = {"BFME_HOME": str(tmp_path)}
    aotr = game_folders(env)[3]
    assert not aotr.installed
    (tmp_path / "prefix/drive_c/RotWK").mkdir(parents=True)    # the regular game is not Age of the Ring
    assert not game_folders(env)[3].installed
    aotr.game.mkdir(parents=True)
    assert game_folders(env)[3].installed
    assert aotr.maps_target() == aotr.game
    aotr.user_data.mkdir(parents=True)
    assert aotr.maps_target() == aotr.user_data
    (aotr.user_data / "maps").mkdir()
    assert aotr.maps_target() == aotr.user_data / "maps"


def test_wine_uses_the_login_name_for_age_of_the_ring_too():
    env = {"BFME_HOME": "/b", "BFME_RUNNER": "wine", "USER": "ann"}
    assert game_folders(env)[3].user_data == Path("/b/wineprefix/drive_c/users/ann/AppData/Roaming/Age of the Ring")


def test_not_installed_until_the_folder_exists(tmp_path):
    env = {"BFME_HOME": str(tmp_path)}
    assert not game_folders(env)[2].installed
    (tmp_path / "prefix/drive_c/RotWK").mkdir(parents=True)
    assert game_folders(env)[2].installed


def test_maps_target_falls_back(tmp_path):
    g = game_folders({"BFME_HOME": str(tmp_path)})[1]
    g.game.mkdir(parents=True)
    assert g.maps_target() == g.game
    g.user_data.mkdir(parents=True)
    assert g.maps_target() == g.user_data
    (g.user_data / "Maps").mkdir()
    assert g.maps_target() == g.user_data / "Maps"
