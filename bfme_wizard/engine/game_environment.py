"""The game environment (Wine prefix): creating it, its registry settings, the graphics settings, and deleting it."""

from __future__ import annotations

import dataclasses
import shutil
import struct
from pathlib import Path

from .config import GPUS, GRAPHICS, Config, ConfigFile
from .context import Context
from .errors import SetupError
from .events import Log, Warn
from .graphics import Graphics
from .overlay_pattern import CONSEQUENCE, OverlayPattern
from .paths import Paths
from .proton import NO_WINE_SERVER, Proton


class GameEnvironment:
    """The Wine prefix that holds the programs and the games. Asking whether it is ready needs only its paths; its
    actions take a context, and the ones that change a setting update the context's config."""

    # Raise it to roll out a new setting: every prefix gets the settings again once.
    SETTINGS_VERSION = 4
    CREATING_MARKER = ".bfme-creating"
    SETTINGS_FILE = "bfme-settings.reg"  # in drive_c while it is imported
    D3D_DLLS = ("d3d8", "d3d9", "d3d10core", "d3d11", "dxgi")
    # Where each architecture's d3d9.dll is. The games are 32-bit; the AIO Launcher and the Arena are 64-bit.
    D3D9_FOLDERS = (("i386", "syswow64"), ("x86_64", "system32"))
    DLL_OVERRIDES = r"HKCU\Software\Wine\DllOverrides"
    # The player's other graphics settings: (config key, allowed values, what it is called).
    OPTIONS = {
        "gpu": ("BFME_GPU", GPUS, "Graphics card"),
        "fps-counter": ("BFME_EXTRA_ENV", (0, 1), "FPS counter"),
    }

    def __init__(self, paths: Paths) -> None:
        self.paths = paths

    def _folders_exist(self) -> bool:
        drive_c = self.paths.drive_c
        return (drive_c / "windows").is_dir() and (drive_c / "users/steamuser").is_dir()

    def ready(self) -> bool:
        """It exists and its creation finished. create() leaves a marker until it is done, so a killed creation is
        redone."""
        if (self.paths.prefix / self.CREATING_MARKER).exists():
            return False

        return self._folders_exist()

    def create(self, ctx: Context) -> None:
        paths = self.paths
        emit = ctx.emit
        paths.prefix.mkdir(parents=True, exist_ok=True)
        paths.logs.mkdir(parents=True, exist_ok=True)
        (paths.prefix / self.CREATING_MARKER).touch()

        emit(Log("Creating the Proton prefix. The first start downloads Proton and takes a few minutes."))
        log = paths.logs / "prefix-create.log"

        # "umu-run ''" builds the prefix, then exits with an error because there is nothing to run. That is expected, so
        # check the files it created instead.
        with open(log, "w", encoding="utf-8") as out:
            ctx.proton.run([""], inprefix=False, output=out)

        if not self._folders_exist():
            for line in log.read_text(errors="replace").splitlines()[-20:]:
                emit(Log(line))

            raise SetupError(f"Could not create the prefix. See {log}")

        (paths.prefix / self.CREATING_MARKER).unlink()

    def prepare(self, ctx: Context) -> None:
        """Create it if it is missing, then make sure it has the current settings and the graphics' own d3d9.dll."""
        if not self.ready():
            self.create(ctx)

        self.apply_settings(ctx)
        self.put_d3d9(ctx)

    def put_d3d9(self, ctx: Context) -> None:
        """The chosen graphics' own d3d9.dll in the game environment, from the Proton that runs it: DXVK's for Vulkan,
        Wine's for OpenGL. Proton copies them in only when it creates the game environment, so after a switch of graphics
        the first ones would stay. The 32-bit one, which the games load, has what the Arena's in-game overlay looks for.
        Without Proton's own files, DXVK's d3d9.dll gets that where it is."""
        proton = ctx.proton

        for arch, folder in self.D3D9_FOLDERS:
            target = self.paths.drive_c / "windows" / folder / "d3d9.dll"
            source = proton.d3d9(arch)

            if source is None and arch == "i386" and proton.config.graphics == "vulkan" and target.is_file():
                source = target

            if source is not None:
                self._put(ctx, source, target, overlay=arch == "i386")

    def _put(self, ctx: Context, source: Path, target: Path, overlay: bool) -> None:
        tmp = target.with_name(target.name + ".bfme-new")
        added = False

        try:
            data = source.read_bytes()

            if overlay:
                try:
                    data = OverlayPattern.with_pattern(data) or data
                    added = True
                except (ValueError, struct.error) as error:
                    ctx.emit(
                        Warn(f"Could not prepare {target} for the Arena's in-game overlay: {error}. {CONSEQUENCE}")
                    )

            if target.is_file() and target.read_bytes() == data:
                return

            target.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes(data)
            tmp.chmod(0o755)
            tmp.replace(target)
        except OSError as error:
            tmp.unlink(missing_ok=True)
            ctx.emit(Warn(f"Could not put {source} in {target}: {error}."))
            return

        if added:
            ctx.emit(Log(f"Added what the Arena's in-game overlay looks for to {target}."))
        else:
            ctx.emit(Log(f"Copied {source} to {target}."))

    def reset(self, ctx: Context) -> None:
        """Delete it, with every game and program in it. Ends its Wine session first."""
        prefix = self.paths.prefix

        if prefix in (Path("/"), Path.home()):
            raise SetupError(f"Refusing to delete '{prefix}'.")

        if not Proton(self.paths, ctx.config).end_session():
            ctx.emit(Warn(NO_WINE_SERVER))

        shutil.rmtree(prefix, ignore_errors=True)
        ctx.emit(Log("Prefix deleted."))

    @classmethod
    def settings(cls, graphics_backend: str) -> list[tuple[str, str, str, str]]:
        """(registry key, value name, type, data) for each setting the prefix gets."""
        out = []

        # Use the games' own Microsoft C++ runtime. The runner's copy rounds numbers slightly differently, so Linux and
        # Windows players drift apart and the match ends in "Out of Sync".
        for dll in ("mfc71", "msvcp71", "msvcr71", "dinput8"):
            out.append((cls.DLL_OVERRIDES, dll, "REG_SZ", "native,builtin"))

        # Without this the AIO Launcher does not repaint a tab after you leave the Multiplayer tab.
        out.append((r"HKCU\Software\Microsoft\Avalon.Graphics", "DisableHWAcceleration", "REG_DWORD", "1"))

        # OpenGL: WineD3D's builtin DLLs, not DXVK's native ones.
        d3d = "builtin" if graphics_backend == "opengl" else "native,builtin"

        for dll in cls.D3D_DLLS:
            out.append((cls.DLL_OVERRIDES, dll, "REG_SZ", d3d))

        return out

    @classmethod
    def reg_file(cls, graphics_backend: str) -> str:
        """The settings as a .reg file for `reg import`, in the plain REGEDIT4 format, which Wine reads as it is."""
        lines = ["REGEDIT4", ""]
        current_key = None

        for key, name, kind, data in cls.settings(graphics_backend):
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

    def apply_settings(self, ctx: Context, force: bool = False) -> None:
        """Set the registry settings, once per SETTINGS_VERSION unless forced.

        All of them go in one `reg import`: each Proton start takes seconds, so setting them one by one took about a
        minute. If the import fails, they are set one by one, so a warning can name the one that failed.
        """
        paths = self.paths
        marker = paths.prefix / f".bfme-settings-v{self.SETTINGS_VERSION}"

        if marker.exists() and not force:
            return

        proton = ctx.proton
        emit = ctx.emit
        backend = proton.config.graphics
        emit(Log("Applying prefix settings."))
        paths.logs.mkdir(parents=True, exist_ok=True)
        log = paths.logs / "prefix-settings.log"
        reg = paths.drive_c / self.SETTINGS_FILE
        reg.write_text(self.reg_file(backend), encoding="ascii")

        with open(log, "w", encoding="utf-8") as out:
            code = proton.run(["reg", "import", f"C:\\{self.SETTINGS_FILE}"], inprefix=True, output=out)

            if code != 0:
                for key, name, kind, data in self.settings(backend):
                    args = ["reg", "add", key, "/v", name, "/t", kind, "/d", data, "/f"]

                    if proton.run(args, inprefix=True, output=out) != 0:
                        emit(Warn(f"Could not set {name}. See {log}"))

        reg.unlink(missing_ok=True)

        for old in paths.prefix.glob(".bfme-settings-v*"):
            old.unlink()

        marker.touch()

    def detect_graphics(self, ctx: Context) -> None:
        """On the first setup, pick the backend this computer suits and save it, so it is picked once. A backend the
        player chose, or one an existing game environment was made with, is kept."""
        if ctx.config.graphics_chosen or self.ready():
            return

        backend, why = Graphics.probe()

        if backend == "unknown":
            return

        ConfigFile(self.paths.config).save("BFME_GRAPHICS", backend)
        ctx.emit(Log(f"Graphics: {Graphics.label(backend)} ({why})."))
        ctx.config = dataclasses.replace(ctx.config, graphics=backend, graphics_chosen=True)

    def set_graphics(self, ctx: Context, backend: str) -> None:
        """The player's switch. Saved in config.env, which the shortcuts read too, and applied to a ready prefix at
        once."""
        config = ctx.config
        emit = ctx.emit

        if backend not in GRAPHICS:
            raise SetupError(f"Unknown graphics backend: {backend}.")

        changed = backend != config.graphics

        if changed:
            emit(Log(f"Graphics: {Graphics.label(backend)}. Saved for this game environment."))
        else:
            emit(Log(f"Already using {Graphics.label(backend)}."))

        # An explicit choice beats detection, so it is saved even when it is the default.
        if changed or not config.graphics_chosen:
            ConfigFile(self.paths.config).save("BFME_GRAPHICS", backend)

        ctx.config = dataclasses.replace(config, graphics=backend, graphics_chosen=True)

        if not self.ready():
            emit(Log("The game environment will be created with it."))
            return

        ctx.renew_proton()
        self.apply_settings(ctx, force=True)
        self.put_d3d9(ctx)

        if changed:
            emit(Log("The change applies the next time you open a program."))
        else:
            emit(Log("The settings were applied again."))

    @staticmethod
    def fps_counter_on(config: Config) -> bool:
        """Whether DXVK draws its frame counter: BFME_EXTRA_ENV sets DXVK_HUD, to anything."""
        return "DXVK_HUD" in config.extra_env

    def _with_fps_counter(self, config: Config, on: bool) -> dict[str, str]:
        """BFME_EXTRA_ENV with DXVK_HUD=fps in it or out of it. Everything else the player put there stays."""
        extra = {}

        for name, value in config.extra_env.items():
            if name != "DXVK_HUD":
                extra[name] = value

        if on:
            extra["DXVK_HUD"] = "fps"

        return extra

    def set_option(self, ctx: Context, option: str, value: str | int) -> None:
        """Save one of the player's graphics settings in config.env. They apply the next time a program opens."""
        config = ctx.config
        if option not in self.OPTIONS:
            raise SetupError(f"Unknown setting: {option}.")

        key, allowed, label = self.OPTIONS[option]

        if value not in allowed:
            raise SetupError(f"{label} cannot be {value}.")

        if option == "fps-counter":
            extra = self._with_fps_counter(config, bool(value))
            words = []

            for name, extra_value in extra.items():
                words.append(f"{name}={extra_value}")

            ConfigFile(self.paths.config).save(key, " ".join(words))
            config = dataclasses.replace(config, extra_env=extra)
        else:
            ConfigFile(self.paths.config).save(key, str(value))

        if option == "gpu":
            config = dataclasses.replace(config, gpu=value)

        shown = value

        if option == "fps-counter":
            shown = "on" if value else "off"

        ctx.config = config
        ctx.emit(Log(f"{label}: {shown}. Saved for this game environment."))
        ctx.emit(Log("The change applies the next time you open a program."))
