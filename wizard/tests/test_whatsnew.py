"""whatsnew: the changelog's notes shown once after an update."""
import pytest

from bfme_wizard import whatsnew
from bfme_wizard.engine.paths import Paths

CHANGELOG = """# Changelog

Some words about the format.

## [Unreleased]

- Not out yet.

## [3.0.0]

### Added

- The app downloads **Age of the Ring** itself.

## [2.1.0]

### Changed

- A `graphics` switch.

## [2.0.2]

- Diagnostics.
"""


@pytest.fixture
def paths(tmp_path):
    return Paths(tmp_path / "data")


@pytest.fixture
def changelog(tmp_path):
    path = tmp_path / "CHANGELOG.md"
    path.write_text(CHANGELOG)
    return path


# Reading the changelog

def test_each_released_version_is_a_section_and_unreleased_is_not():
    found = whatsnew.sections(CHANGELOG)

    versions = []

    for version, _notes in found:
        versions.append(version)

    assert versions == ["3.0.0", "2.1.0", "2.0.2"]
    assert found[0][1] == "### Added\n\n- The app downloads **Age of the Ring** itself."


@pytest.mark.parametrize("seen, current, expected", [
    ("2.1.0", "3.0.0", ["3.0.0"]),
    ("2.0.2", "3.0.0", ["3.0.0", "2.1.0"]),          # versions in between are not skipped
    (None, "3.0.0", ["3.0.0"]),                       # unknown: this version only
    ("3.0.0", "3.0.0", []),
    ("2.0.2", "2.1.0", ["2.1.0"]),                    # nothing newer than the running version
])
def test_the_notes_since_the_version_seen(seen, current, expected):
    versions = []

    for version, _notes in whatsnew.notes_since(CHANGELOG, seen, current):
        versions.append(version)

    assert versions == expected


# When they are shown

def test_a_development_build_shows_nothing(paths, changelog):
    assert whatsnew.to_show(paths, "dev", changelog) == []
    assert whatsnew.to_show(paths, None, changelog) == []
    assert not (paths.base / "last-version").exists()


def test_a_first_install_shows_nothing_but_remembers_the_version(paths, changelog):
    assert whatsnew.to_show(paths, "3.0.0", changelog) == []
    assert (paths.base / "last-version").read_text() == "3.0.0\n"


def test_an_update_from_2x_shows_this_versions_notes(paths, changelog):
    # 2.x kept no version, but it left a data folder behind.
    paths.base.mkdir(parents=True)
    paths.config.write_text("BFME_GRAPHICS=vulkan\n")

    shown = whatsnew.to_show(paths, "3.0.0", changelog)

    assert [version for version, _notes in shown] == ["3.0.0"]


def test_an_update_shows_every_version_since_and_only_once(paths, changelog):
    paths.base.mkdir(parents=True)
    (paths.base / "last-version").write_text("2.0.2\n")

    first = whatsnew.to_show(paths, "3.0.0", changelog)
    again = whatsnew.to_show(paths, "3.0.0", changelog)

    assert [version for version, _notes in first] == ["3.0.0", "2.1.0"]
    assert again == []
    assert (paths.base / "last-version").read_text() == "3.0.0\n"


def test_without_the_changelog_nothing_is_shown(paths, tmp_path):
    paths.base.mkdir(parents=True)
    (paths.base / "last-version").write_text("2.1.0\n")

    assert whatsnew.to_show(paths, "3.0.0", tmp_path / "missing.md") == []


# How they look

def test_the_markup_of_a_section():
    notes = "### Added\n\n- The app downloads **Age of the Ring**, see [the page](https://x).\n- A `graphics` <switch> & more."

    assert whatsnew.markup(notes) == (
        "<b>Added</b>\n"
        "\n"
        "• The app downloads <b>Age of the Ring</b>, see the page.\n"
        "• A <tt>graphics</tt> &lt;switch&gt; &amp; more."
    )


def test_the_dialog_names_the_newest_version_and_holds_every_section(gtk, monkeypatch):
    from gi.repository import Adw
    from bfme_wizard import ui
    from tests.helpers import descendants

    monkeypatch.setattr(Adw.AlertDialog, "present", lambda dialog, parent=None: None)
    dialog = ui.show_whats_new(None, [("3.0.0", "- New."), ("2.1.0", "- Older.")])

    texts = []

    for widget in descendants(dialog.get_extra_child()):
        if isinstance(widget, gtk.Label):
            texts.append(widget.get_label())

    assert dialog.get_heading() == "What's new in 3.0.0"
    assert texts == ["<big><b>3.0.0</b></big>\n• New.\n\n<big><b>2.1.0</b></big>\n• Older."]
