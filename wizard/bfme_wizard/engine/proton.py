"""Proton: getting the pinned build, and running Windows programs in the game environment through umu."""

from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import threading
from pathlib import Path
from typing import IO

from .config import DEFAULT_PROTONPATH, Config
from .download import Download, Progress
from .errors import SetupError
from .events import Emit, Log, report_speed
from .paths import Paths

NO_WINE_SERVER = (
    "Could not find the Wine server to close the programs in the game environment. Close any that are still open."
)


class Proton:
    """The Proton that runs the programs of one game environment, with the player's settings.

    `path` is PROTONPATH for umu. By default it is our copy of the pinned Proton once it is there; any other BFME_PROTONPATH
    is passed as it is.
    """

    URL = (
        f"https://github.com/Open-Wine-Components/umu-proton/releases/download/"
        f"{DEFAULT_PROTONPATH}/{DEFAULT_PROTONPATH}.tar.gz"
    )
    SHA256 = "62e99e029a18fa313e6fa63d42390918101730a940e3491c54d9d58cab887c69"
    D3D_DLLS = "d3d8,d3d9,d3d10core,d3d11,dxgi"

    def __init__(
        self, paths: Paths, config: Config, path: str | None = None, environ: dict[str, str] | None = None
    ) -> None:
        self.paths = paths
        self.config = config
        self._path = path
        self.environ = environ

    @property
    def folder(self) -> Path:
        """Where our own copy of the pinned Proton goes."""
        return self.paths.base / "proton" / DEFAULT_PROTONPATH

    @property
    def chosen_path(self) -> str | None:
        """The path given when it was made, if any."""
        return self._path

    @property
    def path(self) -> str:
        if self._path is not None:
            return self._path

        if self.config.protonpath == DEFAULT_PROTONPATH and self.folder.is_dir():
            return str(self.folder)

        return self.config.protonpath

    def _environ(self) -> dict[str, str]:
        return dict(os.environ if self.environ is None else self.environ)

    def ensure(
        self,
        on_progress: Progress | None = None,
        cancel: threading.Event | None = None,
        emit: Emit | None = None,
        url: str | None = None,
        sha256: str | None = None,
    ) -> str:
        """Download and unpack the pinned Proton if it is missing. Returns PROTONPATH for umu."""
        if self._path is not None or self.config.protonpath != DEFAULT_PROTONPATH:
            return self.path

        target = self.folder

        if (target / "toolmanifest.vdf").is_file():
            return str(target)

        tarball = self.paths.downloads / f"{DEFAULT_PROTONPATH}.tar.gz"
        on_speed = None

        if emit is not None:
            emit(Log(f"Downloading {tarball.name}."))
            on_speed = report_speed(emit)

        Download(url or self.URL, tarball, on_progress, cancel, on_speed).run()
        Download.verify_sha256(tarball, sha256 or self.SHA256)

        # Unpack beside the final place and rename when done, so an interrupted unpack cannot leave a Proton that looks
        # installed but is missing files.
        tmp = target.parent / ".extracting"
        shutil.rmtree(target, ignore_errors=True)
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)

        try:
            with tarfile.open(tarball) as archive:
                archive.extractall(tmp, filter="tar")
        except (tarfile.TarError, OSError) as error:
            raise SetupError("Proton could not be unpacked. Try again.") from error

        unpacked = tmp / DEFAULT_PROTONPATH

        if not (unpacked / "toolmanifest.vdf").is_file():
            raise SetupError(f"Proton was not found after extracting {tarball}.")

        unpacked.rename(target)
        shutil.rmtree(tmp)
        tarball.unlink()

        return str(target)

    @staticmethod
    def graphics_cards() -> list[str]:
        """One line per graphics card, as `lspci` names it, in lower case. Empty without `lspci`."""
        lspci = shutil.which("lspci")

        if lspci is None:
            return []

        try:
            out = subprocess.run([lspci], capture_output=True, text=True, timeout=10, check=False).stdout
        except (OSError, subprocess.SubprocessError):
            return []

        cards = []

        for line in out.splitlines():
            lower = line.lower()

            if "vga" in lower or "3d" in lower:
                cards.append(lower)

        return cards

    @classmethod
    def use_nvidia(cls) -> bool:
        """Whether to send the games to an NVIDIA card: only on a computer with more than one graphics card, one of them
        NVIDIA."""
        cards = cls.graphics_cards()
        has_nvidia = False

        for card in cards:
            if "nvidia" in card:
                has_nvidia = True

        return len(cards) > 1 and has_nvidia

    def _dedicated_card(self, env: dict[str, str]) -> None:
        """Send the programs to the dedicated card: NVIDIA's render offload, and DRI_PRIME for one that Mesa drives
        (AMD)."""
        env["__NV_PRIME_RENDER_OFFLOAD"] = "1"
        env["__GLX_VENDOR_LIBRARY_NAME"] = "nvidia"
        env["__VK_LAYER_NV_optimus"] = "NVIDIA_only"
        env["DRI_PRIME"] = "1"

    def _integrated_card(self, env: dict[str, str]) -> None:
        """Keep the programs on the built-in card: hide NVIDIA from Vulkan and OpenGL, and no DRI_PRIME offload."""
        env["__VK_LAYER_NV_optimus"] = "non_NVIDIA_only"
        env["__GLX_VENDOR_LIBRARY_NAME"] = "mesa"
        env["DRI_PRIME"] = "0"

    def _dxvk_config(self, env: dict[str, str]) -> str:
        """DXVK's settings for the games. Any the player set in DXVK_CONFIG come after, so theirs win."""
        # DXVK has this for BFME 2 and Rise of the Witch-king against slowdowns, but matches only their retail folder
        # names. The AIO Launcher and Age of the Ring install them elsewhere (C:\BFME2, C:\RotWK, C:\AgeoftheRing).
        settings = ["d3d9.cachedWriteOnlyBuffers = True"]

        if env.get("DXVK_CONFIG"):
            settings.append(env["DXVK_CONFIG"])

        return "; ".join(settings)

    def env(self, inprefix: bool) -> dict[str, str]:
        """The environment umu runs a program with."""
        env = self._environ()
        env["WINEPREFIX"] = str(self.paths.prefix)
        env["DXVK_STATE_CACHE_PATH"] = str(self.paths.base / "dxvk-cache")

        if self.config.gpu == "dedicated":
            self._dedicated_card(env)
        elif self.config.gpu == "integrated":
            self._integrated_card(env)
        elif self.use_nvidia():
            env["__NV_PRIME_RENDER_OFFLOAD"] = "1"
            env["__GLX_VENDOR_LIBRARY_NAME"] = "nvidia"
            env["__VK_LAYER_NV_optimus"] = "NVIDIA_only"

        env["DXVK_CONFIG"] = self._dxvk_config(env)

        env["PROTONPATH"] = self.path
        env["GAMEID"] = "0"

        # runinprefix stops umu from waiting for another Wine session. Do not use it on the first start.
        if inprefix:
            env["PROTON_VERB"] = "runinprefix"

        if self.config.graphics == "opengl":
            # Proton copies Wine's builtin Direct3D DLLs into the prefix instead of DXVK's. The old GL renderer is what
            # older cards (Intel HD 4600, say) handle better than Vulkan.
            env["PROTON_USE_WINED3D"] = "1"
            env.setdefault("WINE_D3D_CONFIG", "renderer=gl")

            # The registry says the same, but an override in the environment also covers a prefix made before this choice.
            overrides = f"{self.D3D_DLLS}=b"

            if env.get("WINEDLLOVERRIDES"):
                overrides += "," + env["WINEDLLOVERRIDES"]

            env["WINEDLLOVERRIDES"] = overrides

        env.update(self.config.extra_env)

        return env

    def umu_run(self) -> str:
        """The umu-run the Flatpak ships."""
        found = shutil.which("umu-run")

        if found is None:
            raise SetupError("umu-run was not found.")

        return found

    def start(
        self, args: list[str], inprefix: bool, output: IO | None = None, cwd: Path | None = None
    ) -> subprocess.Popen:
        """Start a program in the game environment, in folder `cwd` if given. Its output goes to `output` (a log file),
        else nowhere."""
        (self.paths.base / "dxvk-cache").mkdir(parents=True, exist_ok=True)
        env = self.env(inprefix)
        sink = output if output is not None else subprocess.DEVNULL

        return subprocess.Popen(
            [self.umu_run(), *args], env=env, stdout=sink, stderr=sink, stdin=subprocess.DEVNULL, cwd=cwd
        )

    def run(self, args: list[str], inprefix: bool, output: IO | None = None, cwd: Path | None = None) -> int:
        """Run a program in the game environment and wait for it. Returns its exit status."""
        return self.start(args, inprefix, output, cwd).wait()

    def wineserver(self) -> Path | None:
        """Proton's Wine server: in the Proton folder, or where umu keeps the Protons it downloads."""
        env = self._environ()
        data_home = env.get("XDG_DATA_HOME") or os.path.join(env.get("HOME", ""), ".local/share")
        candidates = [
            Path(self.path) / "files/bin/wineserver",
            Path(data_home) / "umu/compatibilitytools" / self.path / "files/bin/wineserver",
        ]

        for candidate in candidates:
            if os.access(candidate, os.X_OK):
                return candidate

        return None

    def stop_session(self) -> bool:
        """End every program in the Wine session and wait until it has saved and exited. False without a Wine server."""
        server = self.wineserver()

        if server is None:
            return False

        env = self._environ()
        env["WINEPREFIX"] = str(self.paths.prefix)
        quiet = {"env": env, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "check": False}

        subprocess.run([str(server), "-k"], **quiet)

        try:
            subprocess.run([str(server), "-w"], timeout=20, **quiet)
        except subprocess.TimeoutExpired:
            pass

        return True

    def end_session(self) -> bool:
        """End every program in the game environment. A program still open would lose its files under it, and Wine would
        write its registry back afterwards. False when there is a game environment but no Wine server to end it with."""
        if not self.paths.prefix.is_dir():
            return True

        return self.stop_session()
