"""engine.config: reads and writes config.env the way the setup script does."""
import subprocess
from pathlib import Path

import pytest

from bfme_wizard.engine.config import DEFAULT_PROTONPATH, Config, ConfigError, load, read_file, save

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "bfme-linux-setup.sh"


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


# Parity with the setup script, while it still exists.

def script(base, *args):
    env = {"BFME_HOME": str(base), "PATH": "/usr/bin:/bin", "HOME": str(base)}
    return subprocess.run([str(SCRIPT), "--machine", *args], env=env, capture_output=True, text=True, timeout=60)


def script_graphics(base):
    out = script(base, "status").stdout
    return next(line.split()[3] for line in out.splitlines() if line.startswith("@bfme STATUS graphics "))


def test_what_the_script_saves_the_engine_reads(tmp_path):
    (tmp_path / "config.env").write_text("BFME_NVIDIA=1\n# keep me\n")
    assert script(tmp_path, "graphics", "opengl").returncode == 0
    config = load(tmp_path / "config.env", {})
    assert (config.graphics, config.graphics_chosen) == ("opengl", True)
    assert read_file(tmp_path / "config.env")["BFME_NVIDIA"] == "1"


def test_what_the_engine_saves_the_script_reads(tmp_path):
    (tmp_path / "config.env").write_text("BFME_NVIDIA=1\n# keep me\n")
    save(tmp_path / "config.env", "BFME_GRAPHICS", "opengl")
    assert script_graphics(tmp_path) == "opengl"
    save(tmp_path / "config.env", "BFME_GRAPHICS", "vulkan")
    assert script_graphics(tmp_path) == "vulkan"


@pytest.mark.parametrize("text", ["BFME_GRAPHICS=opengl\n", "export BFME_GRAPHICS=opengl\n", "BFME_GRAPHICS='opengl'\n",
                                  'BFME_GRAPHICS="opengl"\n', "  BFME_GRAPHICS=opengl\n", "BFME_GRAPHICS=\n"])
def test_both_read_the_same_backend(tmp_path, text):
    (tmp_path / "config.env").write_text(text)
    assert load(tmp_path / "config.env", {}).graphics == script_graphics(tmp_path)
