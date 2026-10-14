"""The pictures of the programs: the files, the places that show them, and that they reach those places with no network.

Most of this needs no display. The checks of what the window draws start with gtk_or_skip, like every test that builds a widget.
"""
import hashlib
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bfme_wizard import catalog
from bfme_wizard.catalog import CATALOG, ICONS_DIR, program
from tests.helpers import (
    EXPORT_SUFFIX, MANIFEST, PNG_SIGNATURE, ROOT, descendants, gtk_or_skip, make_script, manifest_app_id,
    manifest_icon_exports, png_size,
)

# The icon of BFME Installer itself: the file as it was downloaded, the page it came from, and the licence it is used under.
APP_ICON_SHA256 = "5d6fe21c636b0c3ba598afa2d81a635b267a3d70e70325016e390248702a22cf"
APP_ICON_SOURCE = ("https://www.iconarchive.com/show/mega-games-pack-28-icons-by-3xhumed/"
                   "The-Lord-of-the-Rings-The-Battle-for-Middle-Earth-II-1-icon.html")
APP_ICON_LICENCE = "https://creativecommons.org/licenses/by-nc-nd/4.0/"
IDLE = "#!/usr/bin/env bash\nexit 0\n"


class Pictures(unittest.TestCase):
    def test_every_program_has_a_picture_named_for_it_and_nothing_else_is_shipped(self):
        shipped = sorted(p.name for p in ICONS_DIR.iterdir())
        self.assertEqual(shipped, sorted(f"{p.key}.png" for p in CATALOG))
        for info in CATALOG:
            self.assertEqual(info.icon, ICONS_DIR / f"{info.key}.png")

    def test_each_is_a_whole_png_that_is_square_and_a_sensible_size(self):
        for info in CATALOG:
            with self.subTest(info.key):
                data = info.icon.read_bytes()
                self.assertEqual(data[:8], PNG_SIGNATURE)
                width, height = png_size(info.icon)
                self.assertEqual(width, height)                     # a menu draws it in a square
                self.assertTrue(64 <= width <= 512, width)          # sharp enough for a menu, not wasteful
                self.assertTrue(data.endswith(b"IEND\xaeB`\x82"))   # not cut off
                self.assertLess(len(data), 150_000)                 # it is in the repository and in every Flatpak

    def test_they_are_three_different_pictures(self):
        digests = {hashlib.sha256(info.icon.read_bytes()).hexdigest() for info in CATALOG}
        self.assertEqual(len(digests), len(CATALOG))


class FlatpakExport(unittest.TestCase):
    """The shortcuts the app writes name their icon `<app id>.<Name>`. Flatpak exports an icon only when its name is the app ID
    plus a suffix, into the folder for its real size, so the manifest has to install each picture exactly like that."""

    def test_each_picture_is_exported_as_an_icon_of_the_app_in_the_folder_for_its_real_size(self):
        exported = manifest_icon_exports()
        app_id = manifest_app_id()
        self.assertEqual(sorted(exported), sorted(f"{p.key}.png" for p in CATALOG))
        for info in CATALOG:
            with self.subTest(info.key):
                width, height = png_size(info.icon)
                self.assertEqual(exported[f"{info.key}.png"], (width, height, f"{app_id}.{EXPORT_SUFFIX[info.key]}"))

    def test_the_names_are_all_different(self):
        names = [name for _w, _h, name in manifest_icon_exports().values()]
        self.assertEqual(len(set(names)), len(names))

    def test_the_wizard_is_copied_with_its_pictures_for_the_window(self):
        # The window loads them from its own folder. The one thing that would lose them is skipping them when it is copied.
        text = MANIFEST.read_text()
        wizard = text[text.index("- name: bfme-wizard"):]
        skipped = re.findall(r"skip:\n((?: {10}- .*\n)+)", wizard)
        self.assertEqual(skipped, ["          - __pycache__\n"])
        self.assertIn("cp -r bfme_wizard /app/lib/bfme-wizard/", wizard)

    def test_the_programs_get_no_menu_entry_from_the_flatpak_only_their_pictures_are_exported(self):
        # A menu entry for a program that is not installed would lead nowhere: the app writes them when it installs one.
        desktops = re.findall(r"/app/share/applications/(\S+\.desktop)", MANIFEST.read_text())
        self.assertEqual(desktops, [f"{manifest_app_id()}.desktop"])


class AppIcon(unittest.TestCase):
    """The icon of BFME Installer itself, in the menu and on its window. It is a designer's picture, used under a licence that
    forbids changing it and asks for credit, so the file has to be exactly what was downloaded and the credit has to stay."""

    ICON = ROOT / "flatpak" / "com.jgbmichalski.BfmeInstaller.png"

    def test_it_is_a_whole_square_png_in_a_size_a_menu_can_use(self):
        data = self.ICON.read_bytes()
        self.assertEqual(data[:8], PNG_SIGNATURE)
        width, height = png_size(self.ICON)
        self.assertEqual(width, height)
        self.assertTrue(128 <= width <= 512, width)
        self.assertTrue(data.endswith(b"IEND\xaeB`\x82"))   # not cut off
        self.assertLess(len(data), 150_000)                 # it is in the repository and in every Flatpak

    def test_it_is_not_the_picture_of_a_program(self):
        # The menu shows the installer and the programs it added side by side, so they have to look different.
        digest = hashlib.sha256(self.ICON.read_bytes()).hexdigest()
        self.assertNotIn(digest, {hashlib.sha256(info.icon.read_bytes()).hexdigest() for info in CATALOG})

    def test_the_file_is_exactly_what_was_downloaded(self):
        # The licence forbids changing it, so a re-saved, resized or edited copy would be a breach and not a fix.
        self.assertEqual(hashlib.sha256(self.ICON.read_bytes()).hexdigest(), APP_ICON_SHA256)

    def test_the_manifest_installs_it_as_the_icon_of_the_app_in_the_folder_for_its_real_size(self):
        app_id = manifest_app_id()
        width, height = png_size(self.ICON)
        self.assertIn(f"install -Dm644 {app_id}.png /app/share/icons/hicolor/{width}x{height}/apps/{app_id}.png",
                      MANIFEST.read_text())

    def test_the_manifest_takes_the_file_from_the_flatpak_folder(self):
        # The build copies the folder under another name for a Dev install (dev/install-local.sh renames what starts with the ID).
        self.assertEqual(self.ICON.name, f"{manifest_app_id()}.png")
        self.assertIn(f"- type: file\n        path: {self.ICON.name}\n", MANIFEST.read_text())

    def test_the_menu_entry_asks_for_that_icon_by_the_app_id(self):
        desktop = (ROOT / "flatpak" / f"{manifest_app_id()}.desktop").read_text()
        self.assertIn(f"\nIcon={manifest_app_id()}\n", desktop)


class OnScreen(unittest.TestCase):
    """What the window draws. Each program's own picture, in a circle, or its initials when the file cannot be used."""

    def setUp(self):
        self.Gtk = gtk_or_skip(self)
        from gi.repository import Adw, Gdk
        from bfme_wizard import widgets
        self.Adw, self.Gdk, self.widgets = Adw, Gdk, widgets
        widgets.read_picture.cache_clear()
        self.addCleanup(widgets.read_picture.cache_clear)

    def avatars(self, widget):
        return [w for w in descendants(widget) if isinstance(w, self.Adw.Avatar)]

    def controller(self, installed):
        from bfme_wizard.controller import Controller
        from bfme_wizard.runner import ScriptRunner
        c = Controller(ScriptRunner(make_script(IDLE)), lambda: None)
        c.model.installed = dict(installed)
        c.model.state = "done"
        return c

    def test_a_program_icon_is_its_own_picture_as_a_circle_of_the_size_asked_for(self):
        for info in CATALOG:
            for size in (64, 40):
                with self.subTest(f"{info.key} at {size}"):
                    avatar = self.widgets.program_icon(info, size)
                    self.assertIsInstance(avatar, self.Adw.Avatar)
                    self.assertEqual(avatar.get_size(), size)
                    texture = avatar.get_custom_image()
                    self.assertIsInstance(texture, self.Gdk.Texture)
                    self.assertEqual((texture.get_width(), texture.get_height()), png_size(info.icon))

    def test_it_is_drawn_at_exactly_that_size_and_not_stretched_by_its_container(self):
        # A circle clips to its own box: a box stretched by a taller neighbour would not be a circle.
        avatar = self.widgets.program_icon(program("aotr"), 40)
        self.assertEqual((avatar.get_halign(), avatar.get_valign()), (self.Gtk.Align.CENTER, self.Gtk.Align.CENTER))

    def test_the_picture_is_not_mixed_up_between_programs(self):
        shown = {info.key: self.widgets.program_icon(info, 64).get_custom_image() for info in CATALOG}
        self.assertEqual(len({id(t) for t in shown.values()}), 3)                       # three different textures...
        for info in CATALOG:                                                             # ...each from its own file
            self.assertIs(shown[info.key], self.widgets.read_picture(str(info.icon)))

    def test_a_picture_is_read_from_its_file_once_and_kept(self):
        info = program("launcher")
        first = self.widgets.read_picture(str(info.icon))
        self.assertIs(self.widgets.read_picture(str(info.icon)), first)
        self.assertEqual(self.widgets.read_picture.cache_info().hits, 1)
        for _ in range(5):                      # the home screen is rebuilt on every change: that must not read files again
            self.widgets.program_icon(info, 64)
        self.assertEqual(self.widgets.read_picture.cache_info().misses, 1)

    def test_a_missing_file_gives_the_initials_in_a_circle_and_not_a_broken_image(self):
        with mock.patch.object(catalog, "ICONS_DIR", Path(tempfile.mkdtemp())):
            avatar = self.widgets.program_icon(program("aotr"), 64)
        self.assertIsNone(avatar.get_custom_image())
        self.assertTrue(avatar.get_show_initials())
        self.assertEqual(avatar.get_text(), "Age of the Ring")
        self.assertEqual(avatar.get_size(), 64)

    def test_a_damaged_file_does_the_same(self):
        folder = Path(tempfile.mkdtemp())
        (folder / "launcher.png").write_bytes(b"\x89PNG\r\n\x1a\n this is not a picture")
        (folder / "arena.png").write_bytes(b"")
        with mock.patch.object(catalog, "ICONS_DIR", folder):
            avatars = [self.widgets.program_icon(program(key), 64) for key in ("launcher", "arena")]
        self.assertEqual([a.get_custom_image() for a in avatars], [None, None])
        self.assertEqual([a.get_text() for a in avatars], ["AIO Launcher", "Arena"])

    def test_a_failure_to_read_is_not_kept_so_a_file_that_appears_later_is_found(self):
        real = program("arena").icon.read_bytes()       # before the folder is pointed somewhere else
        folder = Path(tempfile.mkdtemp())
        with mock.patch.object(catalog, "ICONS_DIR", folder):
            self.assertIsNone(self.widgets.program_icon(program("arena"), 64).get_custom_image())
            (folder / "arena.png").write_bytes(real)
            self.assertIsNotNone(self.widgets.program_icon(program("arena"), 64).get_custom_image())

    def test_the_home_screen_shows_each_installed_programs_picture_at_64_and_only_those(self):
        from bfme_wizard.home import HomePage
        page = HomePage(self.controller({"launcher": "installed", "aotr": "installed"}), lambda: "1.0")
        page.refresh()
        shown = self.avatars(page.content)
        self.assertEqual([(a.get_text(), a.get_size()) for a in shown], [("AIO Launcher", 64), ("Age of the Ring", 64)])
        self.assertTrue(all(a.get_custom_image() is not None for a in shown))

    def test_the_programs_page_shows_every_programs_picture_at_40_installed_or_not(self):
        from bfme_wizard.programs import ProgramsPage
        c = self.controller({"launcher": "installed"})
        page = ProgramsPage(c, install=lambda key: None, remove=lambda key: None)
        shown = [self.avatars(row) for row in page.rows()]
        self.assertEqual([[(a.get_text(), a.get_size()) for a in found] for found in shown],
                         [[("AIO Launcher", 40)], [("Arena", 40)], [("Age of the Ring", 40)]])
        self.assertTrue(all(found[0].get_custom_image() is not None for found in shown))

    def test_the_old_generic_glyphs_are_gone_from_the_cards_and_rows(self):
        # They were symbolic icons from the icon theme, which differs between the host and the Flatpak. (libadwaita draws
        # symbolic icons of its own inside its widgets, so this looks for the ones the app used to name, and no others.)
        from bfme_wizard.home import HomePage
        from bfme_wizard.programs import ProgramsPage
        old = {"applications-games-symbolic", "input-gaming-symbolic", "network-workgroup-symbolic",
               "system-users-symbolic", "media-optical-symbolic", "starred-symbolic"}
        c = self.controller({"launcher": "installed", "arena": "installed", "aotr": "installed"})
        home = HomePage(c, lambda: "1.0")
        home.refresh()
        programs = ProgramsPage(c, install=lambda key: None, remove=lambda key: None)
        for root in (home.content, programs.view):
            names = {w.get_icon_name() for w in descendants(root) if isinstance(w, self.Gtk.Image)}
            self.assertEqual(names & old, set())


if __name__ == "__main__":
    unittest.main()
