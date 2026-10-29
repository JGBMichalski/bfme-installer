"""The pictures of the programs: the files, the places that show them, and that they reach those places with no network.

Most of this needs no display. The checks of what the window draws request the gtk fixture, like every test that builds a widget.
"""
import hashlib
import re

import pytest

from bfme_wizard import catalog
from bfme_wizard.catalog import CATALOG, ICONS_DIR, TOOLS, program

EVERY_PROGRAM = (*CATALOG, *TOOLS)   # each has a picture; only the CATALOG ones have menu shortcuts
from tests.helpers import (
    EXPORT_SUFFIX, MANIFEST, PNG_SIGNATURE, ROOT, descendants, make_script, manifest_app_id,
    manifest_icon_exports, png_size,
)

# The icon of BFME Installer itself: the file as it was downloaded, the page it came from, and the licence it is used under.
APP_ICON_SHA256 = "5d6fe21c636b0c3ba598afa2d81a635b267a3d70e70325016e390248702a22cf"
APP_ICON_SOURCE = ("https://www.iconarchive.com/show/mega-games-pack-28-icons-by-3xhumed/"
                   "The-Lord-of-the-Rings-The-Battle-for-Middle-Earth-II-1-icon.html")
APP_ICON_LICENCE = "https://creativecommons.org/licenses/by-nc-nd/4.0/"
IDLE = "#!/usr/bin/env bash\nexit 0\n"
APP_ICON = ROOT / "flatpak" / "com.jgbmichalski.BfmeInstaller.png"


# Pictures

def test_every_program_has_a_picture_named_for_it_and_nothing_else_is_shipped():
    shipped = sorted(p.name for p in ICONS_DIR.iterdir())
    assert shipped == sorted(f"{p.key}.png" for p in EVERY_PROGRAM)
    for info in EVERY_PROGRAM:
        assert info.icon == ICONS_DIR / f"{info.key}.png"


@pytest.mark.parametrize("info", EVERY_PROGRAM, ids=lambda info: info.key)
def test_each_is_a_whole_png_that_is_square_and_a_sensible_size(info):
    data = info.icon.read_bytes()
    assert data[:8] == PNG_SIGNATURE
    width, height = png_size(info.icon)
    assert width == height                     # a menu draws it in a square
    assert 64 <= width <= 512, width           # sharp enough for a menu, not wasteful
    assert data.endswith(b"IEND\xaeB`\x82")    # not cut off
    assert len(data) < 150_000                 # it is in the repository and in every Flatpak


def test_they_are_six_different_pictures():
    digests = {hashlib.sha256(info.icon.read_bytes()).hexdigest() for info in EVERY_PROGRAM}
    assert len(digests) == len(EVERY_PROGRAM)


# Flatpak export: the shortcuts the app writes name their icon `<app id>.<Name>`. Flatpak exports an icon only when its name is
# the app ID plus a suffix, into the folder for its real size, so the manifest has to install each picture exactly like that.

def test_each_picture_is_exported_as_an_icon_of_the_app():
    exported = manifest_icon_exports()
    assert sorted(exported) == sorted(f"{p.key}.png" for p in CATALOG)


@pytest.mark.parametrize("info", CATALOG, ids=lambda info: info.key)
def test_each_picture_is_exported_in_the_folder_for_its_real_size(info):
    width, height = png_size(info.icon)
    assert manifest_icon_exports()[f"{info.key}.png"] == (width, height, f"{manifest_app_id()}.{EXPORT_SUFFIX[info.key]}")


def test_the_names_are_all_different():
    names = [name for _w, _h, name in manifest_icon_exports().values()]
    assert len(set(names)) == len(names)


def test_the_wizard_is_copied_with_its_pictures_for_the_window():
    # The window loads them from its own folder. The one thing that would lose them is skipping them when it is copied.
    text = MANIFEST.read_text()
    wizard = text[text.index("- name: bfme-wizard"):]
    skipped = re.findall(r"skip:\n((?: {10}- .*\n)+)", wizard)
    assert skipped == ["          - __pycache__\n"]
    assert "cp -r bfme_wizard /app/lib/bfme-wizard/" in wizard


def test_the_programs_get_no_menu_entry_from_the_flatpak_only_their_pictures_are_exported():
    # A menu entry for a program that is not installed would lead nowhere: the app writes them when it installs one.
    desktops = re.findall(r"/app/share/applications/(\S+\.desktop)", MANIFEST.read_text())
    assert desktops == [f"{manifest_app_id()}.desktop"]


# The icon of BFME Installer itself, in the menu and on its window. It is a designer's picture, used under a licence that
# forbids changing it and asks for credit, so the file has to be exactly what was downloaded and the credit has to stay.

def test_app_icon_is_a_whole_square_png_in_a_size_a_menu_can_use():
    data = APP_ICON.read_bytes()
    assert data[:8] == PNG_SIGNATURE
    width, height = png_size(APP_ICON)
    assert width == height
    assert 128 <= width <= 512, width
    assert data.endswith(b"IEND\xaeB`\x82")   # not cut off
    assert len(data) < 150_000                # it is in the repository and in every Flatpak


def test_app_icon_is_not_the_picture_of_a_program():
    # The menu shows the installer and the programs it added side by side, so they have to look different.
    digest = hashlib.sha256(APP_ICON.read_bytes()).hexdigest()
    assert digest not in {hashlib.sha256(info.icon.read_bytes()).hexdigest() for info in CATALOG}


def test_app_icon_file_is_exactly_what_was_downloaded():
    # The licence forbids changing it, so a re-saved, resized or edited copy would be a breach and not a fix.
    assert hashlib.sha256(APP_ICON.read_bytes()).hexdigest() == APP_ICON_SHA256


def test_the_manifest_installs_the_app_icon_in_the_folder_for_its_real_size():
    app_id = manifest_app_id()
    width, height = png_size(APP_ICON)
    assert f"install -Dm644 {app_id}.png /app/share/icons/hicolor/{width}x{height}/apps/{app_id}.png" in MANIFEST.read_text()


def test_the_manifest_takes_the_app_icon_from_the_flatpak_folder():
    # The build copies the folder under another name for a Dev install (dev/install-local.sh renames what starts with the ID).
    assert APP_ICON.name == f"{manifest_app_id()}.png"
    assert f"- type: file\n        path: {APP_ICON.name}\n" in MANIFEST.read_text()


def test_the_menu_entry_asks_for_the_app_icon_by_the_app_id():
    desktop = (ROOT / "flatpak" / f"{manifest_app_id()}.desktop").read_text()
    assert f"\nIcon={manifest_app_id()}\n" in desktop


# On screen: what the window draws. Each program's own picture, in a circle, or its initials when the file cannot be used.

@pytest.fixture
def widgets(gtk):
    from bfme_wizard import widgets
    widgets.read_picture.cache_clear()
    yield widgets
    widgets.read_picture.cache_clear()


def avatars(widget):
    from gi.repository import Adw
    return [w for w in descendants(widget) if isinstance(w, Adw.Avatar)]


def make_controller(installed):
    from bfme_wizard.controller import Controller
    from bfme_wizard.runner import ScriptRunner
    c = Controller(ScriptRunner(make_script(IDLE)), lambda: None)
    c.model.installed = dict(installed)
    c.model.state = "done"
    return c


@pytest.mark.parametrize("size", (64, 40))
@pytest.mark.parametrize("info", CATALOG, ids=lambda info: info.key)
def test_a_program_icon_is_its_own_picture_as_a_circle_of_the_size_asked_for(widgets, info, size):
    from gi.repository import Adw, Gdk
    avatar = widgets.program_icon(info, size)
    assert isinstance(avatar, Adw.Avatar)
    assert avatar.get_size() == size
    texture = avatar.get_custom_image()
    assert isinstance(texture, Gdk.Texture)
    assert (texture.get_width(), texture.get_height()) == png_size(info.icon)


def test_it_is_drawn_at_exactly_that_size_and_not_stretched_by_its_container(gtk, widgets):
    # A circle clips to its own box: a box stretched by a taller neighbour would not be a circle.
    avatar = widgets.program_icon(program("aotr"), 40)
    assert (avatar.get_halign(), avatar.get_valign()) == (gtk.Align.CENTER, gtk.Align.CENTER)


def test_the_picture_is_not_mixed_up_between_programs(widgets):
    shown = {info.key: widgets.program_icon(info, 64).get_custom_image() for info in CATALOG}
    assert len({id(t) for t in shown.values()}) == 3                       # three different textures...
    for info in CATALOG:                                                   # ...each from its own file
        assert shown[info.key] is widgets.read_picture(str(info.icon))


def test_a_picture_is_read_from_its_file_once_and_kept(widgets):
    info = program("launcher")
    first = widgets.read_picture(str(info.icon))
    assert widgets.read_picture(str(info.icon)) is first
    assert widgets.read_picture.cache_info().hits == 1
    for _ in range(5):                      # the home screen is rebuilt on every change: that must not read files again
        widgets.program_icon(info, 64)
    assert widgets.read_picture.cache_info().misses == 1


def test_a_missing_file_gives_the_initials_in_a_circle_and_not_a_broken_image(widgets, monkeypatch, tmp_path):
    monkeypatch.setattr(catalog, "ICONS_DIR", tmp_path)
    avatar = widgets.program_icon(program("aotr"), 64)
    assert avatar.get_custom_image() is None
    assert avatar.get_show_initials()
    assert avatar.get_text() == "Age of the Ring"
    assert avatar.get_size() == 64


def test_a_damaged_file_does_the_same(widgets, monkeypatch, tmp_path):
    (tmp_path / "launcher.png").write_bytes(b"\x89PNG\r\n\x1a\n this is not a picture")
    (tmp_path / "arena.png").write_bytes(b"")
    monkeypatch.setattr(catalog, "ICONS_DIR", tmp_path)
    shown = [widgets.program_icon(program(key), 64) for key in ("launcher", "arena")]
    assert [a.get_custom_image() for a in shown] == [None, None]
    assert [a.get_text() for a in shown] == ["AIO Launcher", "Arena"]


def test_a_failure_to_read_is_not_kept_so_a_file_that_appears_later_is_found(widgets, monkeypatch, tmp_path):
    real = program("arena").icon.read_bytes()       # before the folder is pointed somewhere else
    monkeypatch.setattr(catalog, "ICONS_DIR", tmp_path)
    assert widgets.program_icon(program("arena"), 64).get_custom_image() is None
    (tmp_path / "arena.png").write_bytes(real)
    assert widgets.program_icon(program("arena"), 64).get_custom_image() is not None


def test_the_home_screen_shows_each_installed_programs_picture_at_64_and_only_those(widgets):
    from bfme_wizard.home import HomePage
    page = HomePage(make_controller({"launcher": "installed", "aotr": "installed"}), lambda: "1.0")
    page.refresh()
    shown = avatars(page.content)
    assert [(a.get_text(), a.get_size()) for a in shown] == [("AIO Launcher", 64), ("Age of the Ring", 64)]
    assert all(a.get_custom_image() is not None for a in shown)


def test_the_programs_page_shows_every_programs_picture_at_40_installed_or_not(widgets):
    from bfme_wizard.programs import ProgramsPage
    c = make_controller({"launcher": "installed"})
    page = ProgramsPage(c, install=lambda key: None, remove=lambda key: None, open_app=lambda key: None)
    shown = [avatars(row) for row in page.rows()]
    assert [[(a.get_text(), a.get_size()) for a in found] for found in shown] == \
        [[("AIO Launcher", 40)], [("Arena", 40)], [("Age of the Ring", 40)]]
    assert all(found[0].get_custom_image() is not None for found in shown)


def test_the_old_generic_glyphs_are_gone_from_the_cards_and_rows(gtk, widgets):
    # They were symbolic icons from the icon theme, which differs between the host and the Flatpak. (libadwaita draws
    # symbolic icons of its own inside its widgets, so this looks for the ones the app used to name, and no others.)
    from bfme_wizard.home import HomePage
    from bfme_wizard.programs import ProgramsPage
    old = {"applications-games-symbolic", "input-gaming-symbolic", "network-workgroup-symbolic",
           "system-users-symbolic", "media-optical-symbolic", "starred-symbolic"}
    c = make_controller({"launcher": "installed", "arena": "installed", "aotr": "installed"})
    home = HomePage(c, lambda: "1.0")
    home.refresh()
    programs = ProgramsPage(c, install=lambda key: None, remove=lambda key: None, open_app=lambda key: None)
    for root in (home.content, programs.view):
        names = {w.get_icon_name() for w in descendants(root) if isinstance(w, gtk.Image)}
        assert names & old == set()
