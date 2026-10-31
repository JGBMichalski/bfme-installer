"""engine.config: reads and writes config.env."""

import re

import pytest

from bfme_wizard.engine.config import DEFAULT_PROTONPATH, Config, ConfigError, load, read_file, save


@pytest.fixture
def path(tmp_path):
    return tmp_path / "config.env"


def test_no_file_and_no_environment_means_the_defaults(path):
    assert load(path, {}) == Config("vulkan", False, DEFAULT_PROTONPATH, {})


def test_the_environment_is_used(path):
    config = load(path, {"BFME_GRAPHICS": "opengl", "BFME_PROTONPATH": "GE-Proton10-1"})
    assert (config.graphics, config.graphics_chosen, config.protonpath) == ("opengl", True, "GE-Proton10-1")


def test_the_file_wins_over_the_environment(path):
    path.write_text("BFME_GRAPHICS=opengl\n")
    assert load(path, {"BFME_GRAPHICS": "vulkan"}).graphics == "opengl"


def test_an_empty_value_is_not_a_choice(path):
    path.write_text("BFME_GRAPHICS=\nBFME_PROTONPATH=\n")
    config = load(path, {})
    assert (config.graphics, config.graphics_chosen, config.protonpath) == ("vulkan", False, DEFAULT_PROTONPATH)


def test_an_unknown_backend_is_refused(path):
    path.write_text("BFME_GRAPHICS=direct3d\n")
    with pytest.raises(ConfigError, match='BFME_GRAPHICS must be vulkan or opengl, not "direct3d".'):
        load(path, {})


def test_extra_env_is_split_into_variables(path):
    path.write_text('BFME_EXTRA_ENV="DXVK_HUD=fps WINEDEBUG=-all NOEQUALS"\n')
    assert load(path, {}).extra_env == {"DXVK_HUD": "fps", "WINEDEBUG": "-all"}


def test_the_file_syntax(path):
    path.write_text("# a comment\n\nexport BFME_A=1\n  BFME_B='two words'\nBFME_C=\"3\"\nnot a line\nBFME_D=x=y\n")
    assert read_file(path) == {"BFME_A": "1", "BFME_B": "two words", "BFME_C": "3", "BFME_D": "x=y"}


def test_save_replaces_the_key_and_keeps_everything_else(path):
    path.write_text("BFME_NVIDIA=1\n# keep me\nBFME_GRAPHICS=vulkan\nexport BFME_GRAPHICS=vulkan\n")
    save(path, "BFME_GRAPHICS", "opengl")
    assert path.read_text() == "BFME_NVIDIA=1\n# keep me\nBFME_GRAPHICS=opengl\n"
    assert [p.name for p in path.parent.iterdir()] == ["config.env"]


def test_save_makes_the_folder_and_file(tmp_path):
    path = tmp_path / "new" / "config.env"
    save(path, "BFME_GRAPHICS", "opengl")
    assert path.read_text() == "BFME_GRAPHICS=opengl\n"


# Saving and reading back


def test_a_saved_choice_is_read_back(path):
    path.write_text("BFME_NVIDIA=1\n# keep me\n")

    save(path, "BFME_GRAPHICS", "opengl")

    assert path.read_text() == "BFME_NVIDIA=1\n# keep me\nBFME_GRAPHICS=opengl\n"
    config = load(path, {})
    assert (config.graphics, config.graphics_chosen) == ("opengl", True)
    assert read_file(path)["BFME_NVIDIA"] == "1"

    save(path, "BFME_GRAPHICS", "vulkan")

    assert load(path, {}).graphics == "vulkan"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("BFME_GRAPHICS=opengl\n", "opengl"),
        ("export BFME_GRAPHICS=opengl\n", "opengl"),
        ("BFME_GRAPHICS='opengl'\n", "opengl"),
        ('BFME_GRAPHICS="opengl"\n', "opengl"),
        ("  BFME_GRAPHICS=opengl\n", "opengl"),
        ("BFME_GRAPHICS=\n", "vulkan"),
    ],
)
def test_the_backend_in_each_file_syntax(path, text, expected):
    path.write_text(text)
    assert load(path, {}).graphics == expected


# The graphics card


def test_the_other_graphics_settings_default_to_today(path):
    config = load(path, {})

    assert config.gpu == "auto"


def test_the_other_graphics_settings_are_read(path):
    path.write_text("BFME_GPU=integrated\n")
    config = load(path, {})

    assert config.gpu == "integrated"


@pytest.mark.parametrize(
    "text, message",
    [
        ("BFME_GPU=nvidia\n", 'BFME_GPU must be auto, dedicated or integrated, not "nvidia".'),
    ],
)
def test_a_wrong_value_is_refused(path, text, message):
    path.write_text(text)

    with pytest.raises(ConfigError, match=re.escape(message)):
        load(path, {})
