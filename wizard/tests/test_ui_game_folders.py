"""The Game folders page."""

import os
from unittest import mock

from tests.helpers import descendants, labels


def feed(model, *events):
    for event in events:
        model.feed_event(event)


# Game folders page


def folders_page(home, opened):
    from bfme_wizard.ui.pages.game_folders import GameFoldersPage

    with mock.patch.dict(os.environ, {"BFME_HOME": str(home)}):
        return GameFoldersPage(opened.append)


def groups(page):
    from gi.repository import Adw

    return [w for w in descendants(page.view) if isinstance(w, Adw.PreferencesGroup)]


def test_only_the_installed_games_have_a_group_in_their_order_with_age_of_the_ring_last(gtk, tmp_path):
    drive = tmp_path / "prefix/drive_c"
    for folder in ("RotWK", "BFME1", "AgeoftheRing"):
        (drive / folder).mkdir(parents=True)
    page = folders_page(tmp_path, [])
    assert [g.get_title() for g in groups(page)] == ["BFME", "Rise of the Witch-king", "Age of the Ring"]


def test_a_game_that_is_not_installed_leaves_no_trace_of_itself(gtk, tmp_path):
    (tmp_path / "prefix/drive_c/BFME2").mkdir(parents=True)
    page = folders_page(tmp_path, [])
    text = " ".join(labels(page.view, gtk))
    for word in ("Not installed", "Rise of the Witch-king", "Age of the Ring"):
        assert word not in text
    assert [g.get_title() for g in groups(page)] == ["BFME 2"]


def test_with_no_game_installed_the_page_says_so_instead_of_being_empty(gtk, tmp_path):
    page = folders_page(tmp_path, [])
    assert groups(page) == []
    from gi.repository import Adw

    status = [w for w in descendants(page.view) if isinstance(w, Adw.StatusPage)]
    assert len(status) == 1
    assert status[0].get_title() == "No games installed"


def test_its_rows_open_its_program_folder_and_its_lowercase_maps_folder(gtk, tmp_path):
    drive = tmp_path / "prefix/drive_c"
    (drive / "AgeoftheRing").mkdir(parents=True)
    user = drive / "users/steamuser/AppData/Roaming/Age of the Ring"
    (user / "maps").mkdir(parents=True)
    opened = []
    page = folders_page(tmp_path, opened)
    from gi.repository import Adw

    rows = [w for w in descendants(groups(page)[0]) if isinstance(w, Adw.ActionRow)]
    assert [r.get_title() for r in rows] == ["Game folder", "Maps and user data"]
    for row in rows:
        row.emit("activated")
    assert opened == [drive / "AgeoftheRing", user / "maps"]
    assert [g.get_title() for g in groups(page)] == ["Age of the Ring"]  # the games are separate
