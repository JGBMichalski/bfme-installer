"""One name for the AIO Launcher.

Age of the Ring has a launcher of its own, so "the Launcher" on its own could mean either program. Everything a person reads (the
wizard's words, the setup script's messages and help, the docs, the install page) says "AIO Launcher" for the community
All-in-One Launcher; CONTEXT.md has the term. This test reads those files as text and fails on a bare mention.

It leaves alone what is not a word of the language: the `launcher` command, key, step and file names, `.Launcher` at the end of
an icon's name, `AllInOneLauncher.exe`, `umu-launcher`. It also leaves the notes of releases that are out: they say what they
said then.
"""
import re

import pytest

from tests.helpers import ROOT

# What a person reads, as paths from the top of the repository.
READ = (
    "wizard/bfme_wizard/*.py", "wizard/bfme_wizard/icons/*.md", "scripts/*.sh", "dev/*.py",
    "README.md", "CONTEXT.md", "CONTRIBUTING.md", "CHANGELOG.md", "docs/*.md",
    "flatpak/*.html", "flatpak/*.xml", "flatpak/*.flatpakrepo", "flatpak/*.desktop", "flatpak/*.sh", ".github/ISSUE_TEMPLATE/*.yml",
)
# Where a bare "Launcher" is not a word: (file, a piece of the line). The icon of a program is named for it, and the suffix is
# `Launcher`.
NOT_A_WORD = (
    ("scripts/bfme-linux-setup.sh", "printf 'Launcher'"),
    ("flatpak/install-flatpak.sh", "for program in Launcher Arena Aotr"),
    # The glossary names the phrase it forbids, in quotes.
    ("CONTEXT.md", 'Never shortened to "the Launcher"'),
)

# "the launcher" with a small l. The other launcher is "its own launcher", never "the launcher".
THE_LAUNCHER = re.compile(r"\b[Tt]he launcher\b")
# "Launcher" on its own: not the end of AIO Launcher, All-in-One Launcher or Age of the Ring's launcher, and not part of a longer
# name (AllInOneLauncher.exe, AotR_Launcher.exe, <app id>.Launcher, UriLauncher).
BARE = re.compile(r"(?<![\w./-])(?<!AIO )(?<!All-in-One )(?<!All In One )(?<!Ring )(?<!own )Launcher(?![\w-])(?!\.\w)")


def bare_mention(line: str) -> bool:
    return bool(THE_LAUNCHER.search(line) or BARE.search(line))


def without_allowed(relative: str, line: str) -> str:
    """The line with the phrases that may be bare in this file taken out, so a second, real mention on the same line is still found."""
    for file, piece in NOT_A_WORD:
        if file == relative:
            line = line.replace(piece, "")
    return line


# The other way round: Age of the Ring's launcher is not the AIO Launcher, and must not be renamed into it.
OTHER_LAUNCHER_RENAMED = re.compile(r"\b(its|own|Ring's|Ring) AIO Launcher|Age of the Ring AIO Launcher", re.I)


def words_of(path):
    """(line number, line) for what a person reads in a file. Of the changelog, only what is not released yet. In the glossary,
    not the lines that list the words to avoid: they name the bare word on purpose."""
    lines = list(enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1))
    if path.name == "CHANGELOG.md":
        live, unreleased = [], False
        for number, line in lines:
            if line.startswith("## ["):
                unreleased = line.startswith("## [Unreleased]")
            elif unreleased:
                live.append((number, line))
        return live
    return [(number, line) for number, line in lines if not line.startswith("_Avoid_:")]


def test_nothing_a_person_reads_calls_the_aio_launcher_by_a_bare_name():
    found = []
    for pattern in READ:
        for path in sorted(ROOT.glob(pattern)):
            relative = path.relative_to(ROOT).as_posix()
            for number, line in words_of(path):
                if bare_mention(without_allowed(relative, line)):
                    found.append(f"{relative}:{number}: {line.strip()[:120]}")
    assert found == [], "Say 'AIO Launcher', in full: Age of the Ring has a launcher of its own (see CONTEXT.md)."


def test_age_of_the_rings_own_launcher_is_never_renamed_into_the_aio_launcher():
    found = []
    for pattern in READ:
        for path in sorted(ROOT.glob(pattern)):
            relative = path.relative_to(ROOT).as_posix()
            for number, line in words_of(path):
                if OTHER_LAUNCHER_RENAMED.search(line):
                    found.append(f"{relative}:{number}: {line.strip()[:120]}")
    assert found == [], "Age of the Ring has a launcher of its own, and it is not the AIO Launcher."


@pytest.mark.parametrize("line", ("It has its own AIO Launcher.", "Start the Age of the Ring AIO Launcher.",
                                  "Age of the Ring's AIO Launcher updates it."))
def test_the_other_launcher_check_finds_a_renamed_one(line):
    assert OTHER_LAUNCHER_RENAMED.search(line)


@pytest.mark.parametrize("line", ("It has its own launcher.", "The Age of the Ring Launcher updates the mod itself.",
                                  "not part of the AIO Launcher.", "Close the AIO Launcher and Age of the Ring first.",
                                  "the AIO Launcher, the Arena or Age of the Ring"))
def test_the_other_launcher_check_leaves_the_aio_launcher_alone(line):
    assert not OTHER_LAUNCHER_RENAMED.search(line)


@pytest.mark.parametrize("line", ("Open the Launcher to install your games.", "the launcher's Multiplayer tab",
                                  "The launcher was not installed.", "Remove the Launcher?",
                                  "One row each: **Launcher**, **Arena**", "| Launcher | Check your system |",
                                  "Launcher and Arena side by side", "Install it in the Launcher.",
                                  "(the Launcher and the Arena)"))
def test_the_check_finds_a_bare_name(line):
    assert bare_mention(line)


@pytest.mark.parametrize("line", ("Open the AIO Launcher to install your games.", "Install it in the AIO Launcher.",
                                  "BFME All-in-One Launcher", "The Age of the Ring Launcher updates the mod itself.",
                                  "It has its own launcher and its own games.", "a launcher of its own", "AotR_Launcher.exe",
                                  "AllInOneLauncher.exe", "BFME All In One Launcher", "`<app id>.Launcher`", "umu-launcher",
                                  "launcher-install", "--open launcher", "the launchers and games", "Gtk.UriLauncher",
                                  "AppLauncher", "AIO Launcher: not installed"))
def test_the_check_leaves_a_full_name_alone(line):
    assert not bare_mention(line)


def test_an_allowed_phrase_is_allowed_only_where_it_is_listed_and_only_that_phrase():
    phrase = 'Never shortened to "the Launcher"'
    assert not bare_mention(without_allowed("CONTEXT.md", phrase))
    assert bare_mention(without_allowed("README.md", phrase))                          # another file: not allowed
    assert bare_mention(without_allowed("CONTEXT.md", phrase + ", but open the Launcher"))   # a second mention: found
    assert not bare_mention(without_allowed("scripts/bfme-linux-setup.sh", "    launcher) printf 'Launcher' ;;"))
    assert bare_mention(without_allowed("scripts/bfme-linux-setup.sh", "say 'Open the Launcher'"))
