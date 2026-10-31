"""The game environment (Wine prefix): creating it, its registry settings, the graphics backend, and deleting it."""
from __future__ import annotations

import dataclasses
import shutil
from pathlib import Path

from . import config as config_file
from . import graphics, proton
from .config import GRAPHICS, Config
from .events import Emit, Log, Warn
from .errors import SetupError
from .paths import Paths

# Raise it to roll out a new setting: every prefix gets the settings again once.
SETTINGS_VERSION = 4
CREATING_MARKER = ".bfme-creating"
SETTINGS_FILE = "bfme-settings.reg"   # in drive_c while it is imported
D3D_DLLS = ("d3d8", "d3d9", "d3d10core", "d3d11", "dxgi")
DLL_OVERRIDES = r"HKCU\Software\Wine\DllOverrides"


def _prefix_folders_exist(paths: Paths) -> bool:
    return (paths.drive_c / "windows").is_dir() and (paths.drive_c / "users/steamuser").is_dir()


def prefix_ready(paths: Paths) -> bool:
    """The prefix exists and its creation finished. create_prefix leaves a marker until it is done, so a killed creation is
    redone."""
    if (paths.prefix / CREATING_MARKER).exists():
        return False

    return _prefix_folders_exist(paths)


def create_prefix(paths: Paths, config: Config, proton_path: str, emit: Emit) -> None:
    paths.prefix.mkdir(parents=True, exist_ok=True)
    paths.logs.mkdir(parents=True, exist_ok=True)
    (paths.prefix / CREATING_MARKER).touch()
    
    emit(Log("Creating the Proton prefix. The first start downloads Proton and takes a few minutes."))
    log = paths.logs / "prefix-create.log"

    # "umu-run ''" builds the prefix, then exits with an error because there is nothing to run. That is expected, so check
    # the files it created instead.
    with open(log, "w", encoding="utf-8") as out:
        proton.run(paths, config, proton_path, [""], inprefix=False, output=out)

    if not _prefix_folders_exist(paths):
        for line in log.read_text(errors="replace").splitlines()[-20:]:
            emit(Log(line))

        raise SetupError(f"Could not create the prefix. See {log}")

    (paths.prefix / CREATING_MARKER).unlink()


def settings(graphics_backend: str) -> list[tuple[str, str, str, str]]:
    """(registry key, value name, type, data) for each setting the prefix gets."""
    out = []

    # Use the games' own Microsoft C++ runtime. The runner's copy rounds numbers slightly differently, so Linux and Windows
    # players drift apart and the match ends in "Out of Sync".
    for dll in ("mfc71", "msvcp71", "msvcr71", "dinput8"):
        out.append((DLL_OVERRIDES, dll, "REG_SZ", "native,builtin"))

    # Without this the AIO Launcher does not repaint a tab after you leave the Multiplayer tab.
    out.append((r"HKCU\Software\Microsoft\Avalon.Graphics", "DisableHWAcceleration", "REG_DWORD", "1"))

    # OpenGL: WineD3D's builtin DLLs, not DXVK's native ones.
    d3d = "builtin" if graphics_backend == "opengl" else "native,builtin"

    for dll in D3D_DLLS:
        out.append((DLL_OVERRIDES, dll, "REG_SZ", d3d))

    return out


def reg_file(graphics_backend: str) -> str:
    """The settings as a .reg file for `reg import`, in the plain REGEDIT4 format, which Wine reads as it is."""
    lines = ["REGEDIT4", ""]
    current_key = None

    for key, name, kind, data in settings(graphics_backend):
        full_key = key.replace("HKCU\\", "HKEY_CURRENT_USER\\", 1)

        if full_key != current_key:
            if current_key is not None:
                lines.append("")

            lines.append(f"[{full_key}]")
            current_key = full_key

        if kind == "REG_DWORD":
            lines.append(f'"{name}"=dword:{int(data):08x}')
        else:
            lines.append(f'"{name}"="{data}"')

    return "\r\n".join(lines) + "\r\n"


def apply_settings(paths: Paths, config: Config, proton_path: str, emit: Emit, force: bool = False) -> None:
    """Set the registry settings, once per SETTINGS_VERSION unless forced.

    All of them go in one `reg import`: each Proton start takes seconds, so setting them one by one took about a minute.
    If the import fails, they are set one by one, so a warning can name the one that failed.
    """
    marker = paths.prefix / f".bfme-settings-v{SETTINGS_VERSION}"

    if marker.exists() and not force:
        return

    emit(Log("Applying prefix settings."))
    paths.logs.mkdir(parents=True, exist_ok=True)
    log = paths.logs / "prefix-settings.log"
    reg = paths.drive_c / SETTINGS_FILE
    reg.write_text(reg_file(config.graphics), encoding="ascii")

    with open(log, "w", encoding="utf-8") as out:
        args = ["reg", "import", f"C:\\{SETTINGS_FILE}"]
        code = proton.run(paths, config, proton_path, args, inprefix=True, output=out)

        if code != 0:
            for key, name, kind, data in settings(config.graphics):
                args = ["reg", "add", key, "/v", name, "/t", kind, "/d", data, "/f"]

                if proton.run(paths, config, proton_path, args, inprefix=True, output=out) != 0:
                    emit(Warn(f"Could not set {name}. See {log}"))

    reg.unlink(missing_ok=True)

    for old in paths.prefix.glob(".bfme-settings-v*"):
        old.unlink()

    marker.touch()


def prepare_prefix(paths: Paths, config: Config, proton_path: str, emit: Emit) -> None:
    """Create the prefix if it is missing, then make sure it has the current settings."""
    if not prefix_ready(paths):
        create_prefix(paths, config, proton_path, emit)

    apply_settings(paths, config, proton_path, emit)


def detect_graphics(paths: Paths, config: Config, emit: Emit) -> Config:
    """On the first setup, pick the backend this computer suits and save it, so it is picked once. A backend the player
    chose, or one an existing game environment was made with, is kept."""
    if config.graphics_chosen or prefix_ready(paths):
        return config

    backend, why = graphics.probe()

    if backend == "unknown":
        return config

    config_file.save(paths.config, "BFME_GRAPHICS", backend)
    emit(Log(f"Graphics: {graphics.label(backend)} ({why})."))

    return dataclasses.replace(config, graphics=backend, graphics_chosen=True)


def set_graphics(paths: Paths, config: Config, backend: str, emit: Emit) -> Config:
    """The player's switch. Saved in config.env, which the shortcuts read too, and applied to a ready prefix at once."""
    if backend not in GRAPHICS:
        raise SetupError(f"Unknown graphics backend: {backend}.")

    changed = backend != config.graphics

    if changed:
        emit(Log(f"Graphics: {graphics.label(backend)}. Saved for this game environment."))
    else:
        emit(Log(f"Already using {graphics.label(backend)}."))

    # An explicit choice beats detection, so it is saved even when it is the default.
    if changed or not config.graphics_chosen:
        config_file.save(paths.config, "BFME_GRAPHICS", backend)

    config = dataclasses.replace(config, graphics=backend, graphics_chosen=True)

    if not prefix_ready(paths):
        emit(Log("The game environment will be created with it."))
        return config

    apply_settings(paths, config, proton.protonpath(paths, config), emit, force=True)

    if changed:
        emit(Log("The change applies the next time you open a program."))
    else:
        emit(Log("The settings were applied again."))

    return config


def reset_prefix(paths: Paths, config: Config, emit: Emit) -> None:
    """Delete the game environment, with every game and program in it. Ends its Wine session first."""
    if paths.prefix in (Path("/"), Path.home()):
        raise SetupError(f"Refusing to delete '{paths.prefix}'.")

    if not proton.end_wine_session(paths, config):
        emit(Warn(proton.NO_WINE_SERVER))
    shutil.rmtree(paths.prefix, ignore_errors=True)
    emit(Log("Prefix deleted."))
