import tempfile
import unittest
from pathlib import Path

from bfme_wizard.paths import game_folders, prefix_dir, wine_user


class Paths(unittest.TestCase):
    def test_proton_layout(self):
        env = {"BFME_HOME": "/b"}
        self.assertEqual(prefix_dir(env), Path("/b/prefix"))
        self.assertEqual(wine_user(env), "steamuser")
        bfme2 = game_folders(env)[1]
        self.assertEqual(bfme2.game, Path("/b/prefix/drive_c/BFME2"))
        self.assertEqual(bfme2.user_data, Path("/b/prefix/drive_c/users/steamuser/AppData/Roaming/My Battle for Middle-earth II Files"))

    def test_wine_layout_uses_the_login_name(self):
        env = {"BFME_HOME": "/b", "BFME_RUNNER": "wine", "USER": "ann"}
        self.assertEqual(prefix_dir(env), Path("/b/wineprefix"))
        self.assertIn("users/ann/", str(game_folders(env)[0].user_data))

    def test_the_games_in_order_and_then_age_of_the_ring(self):
        self.assertEqual([g.name for g in game_folders({"BFME_HOME": "/b"})],
                         ["BFME", "BFME 2", "Rise of the Witch-king", "Age of the Ring"])

    def test_age_of_the_ring_keeps_everything_apart_from_the_games(self):
        # Seen in a real install: its own game copies in C:\AgeoftheRing, and its settings and maps in AppData\Roaming\Age of
        # the Ring (the registry's UserDataLeafName for its Rise of the Witch-king copy). No "My ... Files" folder is made.
        aotr = game_folders({"BFME_HOME": "/b"})[3]
        self.assertEqual(aotr.key, "aotr")
        self.assertEqual(aotr.game, Path("/b/prefix/drive_c/AgeoftheRing"))
        self.assertEqual(aotr.user_data, Path("/b/prefix/drive_c/users/steamuser/AppData/Roaming/Age of the Ring"))
        self.assertEqual(aotr.maps_dir, "maps")                       # lowercase: the folder the launcher made
        self.assertEqual({g.maps_dir for g in game_folders({"BFME_HOME": "/b"})[:3]}, {"Maps"})

    def test_age_of_the_ring_is_found_through_its_own_folders_only(self):
        with tempfile.TemporaryDirectory() as home:
            env = {"BFME_HOME": home}
            aotr = game_folders(env)[3]
            self.assertFalse(aotr.installed)
            (Path(home) / "prefix/drive_c/RotWK").mkdir(parents=True)    # the regular game is not Age of the Ring
            self.assertFalse(game_folders(env)[3].installed)
            aotr.game.mkdir(parents=True)
            self.assertTrue(game_folders(env)[3].installed)
            self.assertEqual(aotr.maps_target(), aotr.game)
            aotr.user_data.mkdir(parents=True)
            self.assertEqual(aotr.maps_target(), aotr.user_data)
            (aotr.user_data / "maps").mkdir()
            self.assertEqual(aotr.maps_target(), aotr.user_data / "maps")

    def test_wine_uses_the_login_name_for_age_of_the_ring_too(self):
        env = {"BFME_HOME": "/b", "BFME_RUNNER": "wine", "USER": "ann"}
        self.assertEqual(game_folders(env)[3].user_data, Path("/b/wineprefix/drive_c/users/ann/AppData/Roaming/Age of the Ring"))

    def test_not_installed_until_the_folder_exists(self):
        with tempfile.TemporaryDirectory() as home:
            env = {"BFME_HOME": home}
            self.assertFalse(game_folders(env)[2].installed)
            (Path(home) / "prefix/drive_c/RotWK").mkdir(parents=True)
            self.assertTrue(game_folders(env)[2].installed)

    def test_maps_target_falls_back(self):
        with tempfile.TemporaryDirectory() as home:
            env = {"BFME_HOME": home}
            g = game_folders(env)[1]
            g.game.mkdir(parents=True)
            self.assertEqual(g.maps_target(), g.game)
            g.user_data.mkdir(parents=True)
            self.assertEqual(g.maps_target(), g.user_data)
            (g.user_data / "Maps").mkdir()
            self.assertEqual(g.maps_target(), g.user_data / "Maps")


if __name__ == "__main__":
    unittest.main()
