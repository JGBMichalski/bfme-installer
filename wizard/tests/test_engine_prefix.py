"""engine.prefix: the game environment, its settings and the graphics backend."""
from pathlib import Path

import pytest

from bfme_wizard.engine import graphics, prefix
from bfme_wizard.engine.config import Config, load
from bfme_wizard.engine.errors import SetupError
from bfme_wizard.engine.events import Log, Warn
from bfme_wizard.engine.paths import Paths

# Logs each call's arguments. Called with "" (the first start) it makes the prefix as umu would. REG_FAIL makes `reg add`
# fail for that value name.
FAKE_UMU = r"""#!/bin/sh
printf '%s\n' "$*" >> "$UMU_LOG"
if [ "$1" = "" ]; then
  [ -n "$UMU_BROKEN" ] && { echo "umu: something broke"; exit 1; }
  mkdir -p "$WINEPREFIX/drive_c/windows" "$WINEPREFIX/drive_c/users/steamuser"
  exit 1
fi
[ -n "$REG_FAIL" ] && [ "$5" = "$REG_FAIL" ] && exit 1
exit 0
"""


def executable(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)


@pytest.fixture
def env(tmp_path, monkeypatch):
    """The environment for the engine: the fake umu-run first on PATH, its log, and the data folder."""
    executable(tmp_path / "bin" / "umu-run", FAKE_UMU)
    executable(tmp_path / "bin" / "lspci", "#!/bin/sh\n")
    values = {
        "PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin", "HOME": str(tmp_path), "BFME_HOME": str(tmp_path / "data"),
        "BFME_PROTONPATH": "fake-proton",
        "UMU_LOG": str(tmp_path / "umu.log"),
    }

    for name, value in values.items():
        monkeypatch.setenv(name, value)

    return values


@pytest.fixture
def paths(tmp_path):
    return Paths(tmp_path / "data")


def make_prefix(paths):
    for folder in ("windows", "users/steamuser"):
        (paths.drive_c / folder).mkdir(parents=True, exist_ok=True)


def umu_calls(env):
    log = Path(env["UMU_LOG"])
    calls = log.read_text().splitlines() if log.exists() else []
    log.unlink(missing_ok=True)
    return calls


def logs(events):
    out = []

    for event in events:
        if isinstance(event, Log):
            out.append(event.text)

    return out


# Ready or not

def test_ready_needs_both_folders_and_no_creation_marker(paths):
    assert not prefix.prefix_ready(paths)
    (paths.drive_c / "windows").mkdir(parents=True)
    assert not prefix.prefix_ready(paths)
    (paths.drive_c / "users/steamuser").mkdir(parents=True)
    assert prefix.prefix_ready(paths)
    (paths.prefix / ".bfme-creating").touch()
    assert not prefix.prefix_ready(paths)


# Creating it

def test_creating_runs_umu_once_without_runinprefix_and_leaves_no_marker(env, paths):
    events = []

    prefix.create_prefix(paths, Config(), "fake-proton", events.append)

    assert prefix.prefix_ready(paths)
    assert umu_calls(env) == [""]
    assert (paths.logs / "prefix-create.log").exists()
    assert logs(events) == ["Creating the Proton prefix. The first start downloads Proton and takes a few minutes."]


def test_a_failed_creation_says_where_to_look_and_stays_unfinished(env, paths, monkeypatch):
    monkeypatch.setenv("UMU_BROKEN", "1")
    events = []

    with pytest.raises(SetupError, match="Could not create the prefix. See .*prefix-create.log"):
        prefix.create_prefix(paths, Config(), "fake-proton", events.append)

    assert (paths.prefix / ".bfme-creating").exists()
    assert logs(events)[-1] == "umu: something broke"


# The settings

DLL_OVERRIDES = "HKCU\\Software\\Wine\\DllOverrides"
SETTINGS_ALWAYS = [
    f"reg add {DLL_OVERRIDES} /v mfc71 /t REG_SZ /d native,builtin /f",
    f"reg add {DLL_OVERRIDES} /v msvcp71 /t REG_SZ /d native,builtin /f",
    f"reg add {DLL_OVERRIDES} /v msvcr71 /t REG_SZ /d native,builtin /f",
    f"reg add {DLL_OVERRIDES} /v dinput8 /t REG_SZ /d native,builtin /f",
    "reg add HKCU\\Software\\Microsoft\\Avalon.Graphics /v DisableHWAcceleration /t REG_DWORD /d 1 /f",
]
SETTINGS_VULKAN = SETTINGS_ALWAYS + [
    f"reg add {DLL_OVERRIDES} /v d3d8 /t REG_SZ /d native,builtin /f",
    f"reg add {DLL_OVERRIDES} /v d3d9 /t REG_SZ /d native,builtin /f",
    f"reg add {DLL_OVERRIDES} /v d3d10core /t REG_SZ /d native,builtin /f",
    f"reg add {DLL_OVERRIDES} /v d3d11 /t REG_SZ /d native,builtin /f",
    f"reg add {DLL_OVERRIDES} /v dxgi /t REG_SZ /d native,builtin /f",
]
SETTINGS_OPENGL = SETTINGS_ALWAYS + [
    f"reg add {DLL_OVERRIDES} /v d3d8 /t REG_SZ /d builtin /f",
    f"reg add {DLL_OVERRIDES} /v d3d9 /t REG_SZ /d builtin /f",
    f"reg add {DLL_OVERRIDES} /v d3d10core /t REG_SZ /d builtin /f",
    f"reg add {DLL_OVERRIDES} /v d3d11 /t REG_SZ /d builtin /f",
    f"reg add {DLL_OVERRIDES} /v dxgi /t REG_SZ /d builtin /f",
]
SETTINGS = {"vulkan": SETTINGS_VULKAN, "opengl": SETTINGS_OPENGL}


@pytest.mark.parametrize("backend", ["vulkan", "opengl"])
def test_the_settings_for_each_backend(env, paths, backend):
    make_prefix(paths)

    prefix.apply_settings(paths, Config(graphics=backend), "fake-proton", [].append, force=True)

    assert umu_calls(env) == SETTINGS[backend]
    assert sorted(p.name for p in paths.prefix.glob(".bfme-settings-v*")) == [".bfme-settings-v4"]


def test_the_settings_are_applied_once_per_version(env, paths):
    make_prefix(paths)
    (paths.prefix / ".bfme-settings-v3").touch()

    prefix.apply_settings(paths, Config(), "fake-proton", [].append)
    assert len(umu_calls(env)) == 10
    assert [p.name for p in paths.prefix.glob(".bfme-settings-v*")] == [f".bfme-settings-v{prefix.SETTINGS_VERSION}"]

    prefix.apply_settings(paths, Config(), "fake-proton", [].append)
    assert umu_calls(env) == []

    prefix.apply_settings(paths, Config(), "fake-proton", [].append, force=True)
    assert len(umu_calls(env)) == 10


def test_a_setting_that_fails_is_a_warning(env, paths, monkeypatch):
    make_prefix(paths)
    monkeypatch.setenv("REG_FAIL", "DisableHWAcceleration")
    events = []

    prefix.apply_settings(paths, Config(), "fake-proton", events.append)

    warnings = [e for e in events if isinstance(e, Warn)]
    assert warnings == [Warn(f"Could not set DisableHWAcceleration. See {paths.logs / 'prefix-settings.log'}")]
    assert (paths.prefix / f".bfme-settings-v{prefix.SETTINGS_VERSION}").exists()


def test_prepare_creates_a_missing_prefix_then_applies_the_settings(env, paths):
    prefix.prepare_prefix(paths, Config(), "fake-proton", [].append)

    calls = umu_calls(env)
    assert calls[0] == ""
    assert len(calls) == 11

    prefix.prepare_prefix(paths, Config(), "fake-proton", [].append)
    assert umu_calls(env) == []


# The first setup's graphics backend

@pytest.fixture
def probe(monkeypatch):
    answer = {"value": ("opengl", "no graphics card with Vulkan was found")}
    monkeypatch.setattr(graphics, "probe", lambda: answer["value"])
    return answer


def test_the_first_setup_saves_what_the_computer_suits(paths, probe):
    events = []

    config = prefix.detect_graphics(paths, Config(), events.append)

    assert (config.graphics, config.graphics_chosen) == ("opengl", True)
    assert load(paths.config, {}).graphics == "opengl"
    assert logs(events) == ["Graphics: OpenGL (WineD3D) (no graphics card with Vulkan was found)."]


def test_a_chosen_backend_is_kept(paths, probe):
    config = Config(graphics="vulkan", graphics_chosen=True)

    assert prefix.detect_graphics(paths, config, [].append) is config
    assert not paths.config.exists()


def test_an_existing_game_environment_is_left_as_it_is(paths, probe):
    make_prefix(paths)

    assert prefix.detect_graphics(paths, Config(), [].append) == Config()
    assert not paths.config.exists()


def test_a_probe_that_fails_changes_nothing(paths, probe):
    probe["value"] = ("unknown", "could not check Vulkan")

    assert prefix.detect_graphics(paths, Config(), [].append) == Config()
    assert not paths.config.exists()


# The player's switch

SAVED_NEW = "Saved for this game environment."
LATER = "The game environment will be created with it."
APPLYING = "Applying prefix settings."
AGAIN = "The settings were applied again."
NEXT_TIME = "The change applies the next time you open a program."

# (ready, saved, wanted): what the switch says. Without a game environment nothing runs; with one the settings for the
# wanted backend are applied again.
SWITCHES = {
    (False, None, "vulkan"): ["Already using Vulkan (DXVK).", LATER],
    (False, None, "opengl"): [f"Graphics: OpenGL (WineD3D). {SAVED_NEW}", LATER],
    (False, "vulkan", "vulkan"): ["Already using Vulkan (DXVK).", LATER],
    (False, "vulkan", "opengl"): [f"Graphics: OpenGL (WineD3D). {SAVED_NEW}", LATER],
    (False, "opengl", "vulkan"): [f"Graphics: Vulkan (DXVK). {SAVED_NEW}", LATER],
    (False, "opengl", "opengl"): ["Already using OpenGL (WineD3D).", LATER],
    (True, None, "vulkan"): ["Already using Vulkan (DXVK).", APPLYING, AGAIN],
    (True, None, "opengl"): [f"Graphics: OpenGL (WineD3D). {SAVED_NEW}", APPLYING, NEXT_TIME],
    (True, "vulkan", "vulkan"): ["Already using Vulkan (DXVK).", APPLYING, AGAIN],
    (True, "vulkan", "opengl"): [f"Graphics: OpenGL (WineD3D). {SAVED_NEW}", APPLYING, NEXT_TIME],
    (True, "opengl", "vulkan"): [f"Graphics: Vulkan (DXVK). {SAVED_NEW}", APPLYING, NEXT_TIME],
    (True, "opengl", "opengl"): ["Already using OpenGL (WineD3D).", APPLYING, AGAIN],
}


@pytest.mark.parametrize("ready,saved,wanted", list(SWITCHES))
def test_switching(env, paths, ready, saved, wanted):
    if ready:
        make_prefix(paths)

    paths.base.mkdir(parents=True, exist_ok=True)
    start = f"BFME_NVIDIA=1\n# keep me\nBFME_GRAPHICS={saved}\n" if saved else "BFME_NVIDIA=1\n# keep me\n"
    paths.config.write_text(start)
    events = []

    config = prefix.set_graphics(paths, load(paths.config, {}), wanted, events.append)

    assert logs(events) == SWITCHES[(ready, saved, wanted)]
    assert paths.config.read_text() == f"BFME_NVIDIA=1\n# keep me\nBFME_GRAPHICS={wanted}\n"

    if ready:
        assert umu_calls(env) == SETTINGS[wanted]
    else:
        assert umu_calls(env) == []

    assert (config.graphics, config.graphics_chosen) == (wanted, True)


def test_an_unknown_backend_is_refused(paths):
    with pytest.raises(SetupError, match="Unknown graphics backend: direct3d."):
        prefix.set_graphics(paths, Config(), "direct3d", [].append)


# Deleting it

def test_reset_ends_the_wine_session_and_deletes_the_prefix(tmp_path, env, paths):
    make_prefix(paths)
    log = tmp_path / "wineserver.log"
    executable(tmp_path / "my-proton/files/bin/wineserver", f"#!/bin/sh\necho \"$*\" >> '{log}'\n")
    events = []

    prefix.reset_prefix(paths, Config(protonpath=str(tmp_path / "my-proton")), events.append)

    assert not paths.prefix.exists()
    assert log.read_text() == "-k\n-w\n"
    assert logs(events) == ["Prefix deleted."]
    assert paths.base.exists()
