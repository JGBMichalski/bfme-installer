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

    def test_three_games_in_order(self):
        self.assertEqual([g.name for g in game_folders({"BFME_HOME": "/b"})], ["BFME", "BFME 2", "Rise of the Witch-king"])

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
