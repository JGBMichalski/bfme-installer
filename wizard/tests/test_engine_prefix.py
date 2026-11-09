"""engine.prefix: the game environment, its settings and the graphics backend."""

from pathlib import Path

import pytest

from bfme_wizard.engine.config import Config, ConfigFile
from bfme_wizard.engine.errors import SetupError
from bfme_wizard.engine.events import Log, Warn
from bfme_wizard.engine.graphics import Graphics
from bfme_wizard.engine.paths import Paths
from bfme_wizard.engine.prefix import GameEnvironment
from tests.helpers import context

# Logs each call's arguments. Called with "" (the first start) it makes the prefix as umu would. `reg import` keeps a copy of
# the file in REG_COPY, and fails with IMPORT_FAIL. REG_FAIL makes `reg add`
# fail for that value name.
FAKE_UMU = r"""#!/bin/sh
printf '%s\n' "$*" >> "$UMU_LOG"
if [ "$1" = "" ]; then
  [ -n "$UMU_BROKEN" ] && { echo "umu: something broke"; exit 1; }
  mkdir -p "$WINEPREFIX/drive_c/windows" "$WINEPREFIX/drive_c/users/steamuser"
  exit 1
fi
if [ "$1" = "reg" ] && [ "$2" = "import" ]; then
  cp "$WINEPREFIX/drive_c/bfme-settings.reg" "$REG_COPY"
  [ -n "$IMPORT_FAIL" ] && exit 1
  exit 0
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
        "PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "BFME_HOME": str(tmp_path / "data"),
        "BFME_PROTONPATH": "fake-proton",
        "UMU_LOG": str(tmp_path / "umu.log"),
        "REG_COPY": str(tmp_path / "imported.reg"),
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
    assert not GameEnvironment(paths).ready()
    (paths.drive_c / "windows").mkdir(parents=True)
    assert not GameEnvironment(paths).ready()
    (paths.drive_c / "users/steamuser").mkdir(parents=True)
    assert GameEnvironment(paths).ready()
    (paths.prefix / ".bfme-creating").touch()
    assert not GameEnvironment(paths).ready()


# Creating it


def test_creating_runs_umu_once_without_runinprefix_and_leaves_no_marker(env, paths):
    events = []

    GameEnvironment(paths).create(context(paths, events.append, config=Config()))

    assert GameEnvironment(paths).ready()
    assert umu_calls(env) == [""]
    assert (paths.logs / "prefix-create.log").exists()
    assert logs(events) == ["Creating the Proton prefix. The first start downloads Proton and takes a few minutes."]


def test_a_failed_creation_says_where_to_look_and_stays_unfinished(env, paths, monkeypatch):
    monkeypatch.setenv("UMU_BROKEN", "1")
    events = []

    with pytest.raises(SetupError, match="Could not create the prefix. See .*prefix-create.log"):
        GameEnvironment(paths).create(context(paths, events.append, config=Config()))

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
# One by one, when the import fails.
SETTINGS = {"vulkan": SETTINGS_VULKAN, "opengl": SETTINGS_OPENGL}
IMPORT = "reg import C:\\bfme-settings.reg"

REG_FILE_START = (
    "REGEDIT4\r\n"
    "\r\n"
    "[HKEY_CURRENT_USER\\Software\\Wine\\DllOverrides]\r\n"
    '"mfc71"="native,builtin"\r\n'
    '"msvcp71"="native,builtin"\r\n'
    '"msvcr71"="native,builtin"\r\n'
    '"dinput8"="native,builtin"\r\n'
    "\r\n"
    "[HKEY_CURRENT_USER\\Software\\Microsoft\\Avalon.Graphics]\r\n"
    '"DisableHWAcceleration"=dword:00000001\r\n'
    "\r\n"
    "[HKEY_CURRENT_USER\\Software\\Wine\\DllOverrides]\r\n"
)
REG_FILE = {
    "vulkan": REG_FILE_START + '"d3d8"="native,builtin"\r\n"d3d9"="native,builtin"\r\n"d3d10core"="native,builtin"\r\n'
    '"d3d11"="native,builtin"\r\n"dxgi"="native,builtin"\r\n',
    "opengl": REG_FILE_START + '"d3d8"="builtin"\r\n"d3d9"="builtin"\r\n"d3d10core"="builtin"\r\n"d3d11"="builtin"\r\n'
    '"dxgi"="builtin"\r\n',
}


@pytest.mark.parametrize("backend", ["vulkan", "opengl"])
def test_the_settings_for_each_backend_are_imported_at_once(env, paths, backend):
    make_prefix(paths)

    GameEnvironment(paths).apply_settings(context(paths, [].append, config=Config(graphics=backend)), force=True)

    assert umu_calls(env) == [IMPORT]
    assert Path(env["REG_COPY"]).read_bytes().decode("ascii") == REG_FILE[backend]
    assert not (paths.drive_c / "bfme-settings.reg").exists()
    assert sorted(p.name for p in paths.prefix.glob(".bfme-settings-v*")) == [".bfme-settings-v4"]


def test_the_settings_are_applied_once_per_version(env, paths):
    make_prefix(paths)
    (paths.prefix / ".bfme-settings-v3").touch()

    GameEnvironment(paths).apply_settings(context(paths, [].append, config=Config()))
    assert umu_calls(env) == [IMPORT]
    assert [p.name for p in paths.prefix.glob(".bfme-settings-v*")] == [
        f".bfme-settings-v{GameEnvironment.SETTINGS_VERSION}"
    ]

    GameEnvironment(paths).apply_settings(context(paths, [].append, config=Config()))
    assert umu_calls(env) == []

    GameEnvironment(paths).apply_settings(context(paths, [].append, config=Config()), force=True)
    assert umu_calls(env) == [IMPORT]


@pytest.mark.parametrize("backend", ["vulkan", "opengl"])
def test_when_the_import_fails_they_are_set_one_by_one(env, paths, monkeypatch, backend):
    make_prefix(paths)
    monkeypatch.setenv("IMPORT_FAIL", "1")
    events = []

    GameEnvironment(paths).apply_settings(context(paths, events.append, config=Config(graphics=backend)))

    assert umu_calls(env) == [IMPORT, *SETTINGS[backend]]
    assert [e for e in events if isinstance(e, Warn)] == []
    assert not (paths.drive_c / "bfme-settings.reg").exists()


def test_a_setting_that_fails_one_by_one_is_a_warning(env, paths, monkeypatch):
    make_prefix(paths)
    monkeypatch.setenv("IMPORT_FAIL", "1")
    monkeypatch.setenv("REG_FAIL", "DisableHWAcceleration")
    events = []

    GameEnvironment(paths).apply_settings(context(paths, events.append, config=Config()))

    warnings = [e for e in events if isinstance(e, Warn)]
    assert warnings == [Warn(f"Could not set DisableHWAcceleration. See {paths.logs / 'prefix-settings.log'}")]
    assert (paths.prefix / f".bfme-settings-v{GameEnvironment.SETTINGS_VERSION}").exists()


def test_prepare_creates_a_missing_prefix_then_applies_the_settings(env, paths):
    GameEnvironment(paths).prepare(context(paths, [].append, config=Config()))

    assert umu_calls(env) == ["", IMPORT]

    GameEnvironment(paths).prepare(context(paths, [].append, config=Config()))
    assert umu_calls(env) == []


# The first setup's graphics backend


@pytest.fixture
def probe(monkeypatch):
    answer = {"value": ("opengl", "no graphics card with Vulkan was found")}
    monkeypatch.setattr(Graphics, "probe", lambda: answer["value"])
    return answer


def test_the_first_setup_saves_what_the_computer_suits(paths, probe):
    events = []

    ctx = context(paths, events.append)
    GameEnvironment(paths).detect_graphics(ctx)
    config = ctx.config

    assert (config.graphics, config.graphics_chosen) == ("opengl", True)
    assert ConfigFile(paths.config).load({}).graphics == "opengl"
    assert logs(events) == ["Graphics: OpenGL (WineD3D) (no graphics card with Vulkan was found)."]


def test_a_chosen_backend_is_kept(paths, probe):
    config = Config(graphics="vulkan", graphics_chosen=True)

    ctx = context(paths, config=config)
    GameEnvironment(paths).detect_graphics(ctx)
    assert ctx.config is config
    assert not paths.config.exists()


def test_an_existing_game_environment_is_left_as_it_is(paths, probe):
    make_prefix(paths)

    ctx = context(paths)
    GameEnvironment(paths).detect_graphics(ctx)
    assert ctx.config == Config()
    assert not paths.config.exists()


def test_a_probe_that_fails_changes_nothing(paths, probe):
    probe["value"] = ("unknown", "could not check Vulkan")

    ctx = context(paths)
    GameEnvironment(paths).detect_graphics(ctx)
    assert ctx.config == Config()
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

    ctx = context(paths, events.append, config=ConfigFile(paths.config).load({}))
    GameEnvironment(paths).set_graphics(ctx, wanted)
    config = ctx.config

    assert logs(events) == SWITCHES[(ready, saved, wanted)]
    assert paths.config.read_text() == f"BFME_NVIDIA=1\n# keep me\nBFME_GRAPHICS={wanted}\n"

    if ready:
        assert umu_calls(env) == [IMPORT]
        assert Path(env["REG_COPY"]).read_bytes().decode("ascii") == REG_FILE[wanted]
    else:
        assert umu_calls(env) == []

    assert (config.graphics, config.graphics_chosen) == (wanted, True)


def test_an_unknown_backend_is_refused(paths):
    with pytest.raises(SetupError, match="Unknown graphics backend: direct3d."):
        GameEnvironment(paths).set_graphics(context(paths), "direct3d")


# Deleting it


def test_reset_ends_the_wine_session_and_deletes_the_prefix(tmp_path, env, paths):
    make_prefix(paths)
    log = tmp_path / "wineserver.log"
    executable(tmp_path / "my-proton/files/bin/wineserver", f"#!/bin/sh\necho \"$*\" >> '{log}'\n")
    events = []

    GameEnvironment(paths).reset(context(paths, events.append, config=Config(protonpath=str(tmp_path / "my-proton"))))

    assert not paths.prefix.exists()
    assert log.read_text() == "-k\n-w\n"
    assert logs(events) == ["Prefix deleted."]
    assert paths.base.exists()


# The graphics card


@pytest.mark.parametrize(
    "option, value, key, field",
    [
        ("gpu", "integrated", "BFME_GPU", "gpu"),
    ],
)
def test_the_card_is_only_saved(env, paths, option, value, key, field):
    make_prefix(paths)
    paths.base.mkdir(parents=True, exist_ok=True)

    ctx = context(paths)
    GameEnvironment(paths).set_option(ctx, option, value)
    config = ctx.config

    assert getattr(config, field) == value
    assert paths.config.read_text() == f"{key}={value}\n"
    assert umu_calls(env) == []  # they apply when a program opens


@pytest.mark.parametrize(
    "option, value, message",
    [
        ("gpu", "nvidia", "Graphics card cannot be nvidia."),
        ("vsync", 1, "Unknown setting: vsync."),
    ],
)
def test_a_wrong_setting_is_refused(paths, option, value, message):
    with pytest.raises(SetupError, match=message):
        GameEnvironment(paths).set_option(context(paths), option, value)

    assert not paths.config.exists()


# The FPS counter: DXVK_HUD=fps in BFME_EXTRA_ENV


def test_the_fps_counter_is_added_to_the_extra_environment_and_keeps_the_rest(paths):
    paths.base.mkdir(parents=True)
    paths.config.write_text('BFME_EXTRA_ENV="WINEDEBUG=-all"\n')

    ctx = context(paths, config=ConfigFile(paths.config).load({}))
    GameEnvironment(paths).set_option(ctx, "fps-counter", 1)
    config = ctx.config

    assert paths.config.read_text() == "BFME_EXTRA_ENV=WINEDEBUG=-all DXVK_HUD=fps\n"
    assert config.extra_env == {"WINEDEBUG": "-all", "DXVK_HUD": "fps"}
    assert GameEnvironment.fps_counter_on(config)
    assert ConfigFile(paths.config).load({}).extra_env == {"WINEDEBUG": "-all", "DXVK_HUD": "fps"}


def test_turning_it_off_removes_any_dxvk_hud_and_only_that(paths):
    paths.base.mkdir(parents=True)
    paths.config.write_text('BFME_EXTRA_ENV="DXVK_HUD=full WINEDEBUG=-all"\n')
    config = ConfigFile(paths.config).load({})
    assert GameEnvironment.fps_counter_on(config)  # any DXVK_HUD counts as on

    ctx = context(paths, config=config)
    GameEnvironment(paths).set_option(ctx, "fps-counter", 0)
    config = ctx.config

    assert paths.config.read_text() == "BFME_EXTRA_ENV=WINEDEBUG=-all\n"
    assert not GameEnvironment.fps_counter_on(config)


def test_turning_it_off_with_nothing_else_leaves_it_empty(paths):
    paths.base.mkdir(parents=True)
    paths.config.write_text("BFME_EXTRA_ENV=DXVK_HUD=fps\n")

    events = []
    ctx = context(paths, events.append, config=ConfigFile(paths.config).load({}))
    GameEnvironment(paths).set_option(ctx, "fps-counter", 0)
    config = ctx.config

    assert paths.config.read_text() == "BFME_EXTRA_ENV=\n"
    assert config.extra_env == {}
    assert logs(events)[0] == "FPS counter: off. Saved for this game environment."
