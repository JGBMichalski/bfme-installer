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
from .download import Progress, download, verify_sha256
from .errors import SetupError
from .events import Emit, Log, report_speed
from .paths import Paths

PROTON_URL = (f"https://github.com/Open-Wine-Components/umu-proton/releases/download/"
              f"{DEFAULT_PROTONPATH}/{DEFAULT_PROTONPATH}.tar.gz")
PROTON_SHA256 = "62e99e029a18fa313e6fa63d42390918101730a940e3491c54d9d58cab887c69"
D3D_DLLS = "d3d8,d3d9,d3d10core,d3d11,dxgi"

NO_WINE_SERVER = ("Could not find the Wine server to close the programs in the game environment. Close any that are still "
                  "open.")


def proton_dir(paths: Paths) -> Path:
    """Where our own copy of the pinned Proton goes."""
    return paths.base / "proton" / DEFAULT_PROTONPATH


def protonpath(paths: Paths, config: Config) -> str:
    """PROTONPATH for umu: our copy of the pinned Proton once it is there. Any other value is passed as it is."""
    if config.protonpath == DEFAULT_PROTONPATH and proton_dir(paths).is_dir():
        return str(proton_dir(paths))

    return config.protonpath


def ensure_proton(paths: Paths, config: Config, on_progress: Progress | None = None,
                  cancel: threading.Event | None = None, url: str = PROTON_URL, sha256: str = PROTON_SHA256,
                  emit: Emit | None = None) -> str:
    """Download and unpack the pinned Proton if it is missing. Returns PROTONPATH for umu."""
    if config.protonpath != DEFAULT_PROTONPATH:
        return config.protonpath

    target = proton_dir(paths)

    if (target / "toolmanifest.vdf").is_file():
        return str(target)

    tarball = paths.downloads / f"{DEFAULT_PROTONPATH}.tar.gz"
    on_speed = None

    if emit is not None:
        emit(Log(f"Downloading {tarball.name}."))
        on_speed = report_speed(emit)

    download(url, tarball, on_progress, cancel, on_speed)
    verify_sha256(tarball, sha256)

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


def use_nvidia() -> bool:
    """Whether to send the games to an NVIDIA card: only on a computer with more than one graphics card, one of them NVIDIA."""
    lspci = shutil.which("lspci")

    if lspci is None:
        return False

    try:
        out = subprocess.run([lspci], capture_output=True, text=True, timeout=10, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return False

    cards = []

    for line in out.splitlines():
        lower = line.lower()

        if "vga" in lower or "3d" in lower:
            cards.append(lower)

    has_nvidia = False

    for card in cards:
        if "nvidia" in card:
            has_nvidia = True

    return len(cards) > 1 and has_nvidia


def runner_env(paths: Paths, config: Config, proton: str, inprefix: bool, environ: dict[str, str] | None = None) -> dict[str, str]:
    """The environment umu runs a program with."""
    env = dict(os.environ if environ is None else environ)
    env["WINEPREFIX"] = str(paths.prefix)
    env["DXVK_STATE_CACHE_PATH"] = str(paths.base / "dxvk-cache")

    if use_nvidia():
        env["__NV_PRIME_RENDER_OFFLOAD"] = "1"
        env["__GLX_VENDOR_LIBRARY_NAME"] = "nvidia"
        env["__VK_LAYER_NV_optimus"] = "NVIDIA_only"

    env["PROTONPATH"] = proton
    env["GAMEID"] = "0"

    # runinprefix stops umu from waiting for another Wine session. Do not use it on the first start.
    if inprefix:
        env["PROTON_VERB"] = "runinprefix"

    if config.graphics == "opengl":
        # Proton copies Wine's builtin Direct3D DLLs into the prefix instead of DXVK's. The old GL renderer is what older
        # cards (Intel HD 4600, say) handle better than Vulkan.
        env["PROTON_USE_WINED3D"] = "1"
        env.setdefault("WINE_D3D_CONFIG", "renderer=gl")

        # The registry says the same, but an override in the environment also covers a prefix made before this choice.
        overrides = f"{D3D_DLLS}=b"

        if env.get("WINEDLLOVERRIDES"):
            overrides += "," + env["WINEDLLOVERRIDES"]

        env["WINEDLLOVERRIDES"] = overrides

    env.update(config.extra_env)

    return env


def umu_run() -> str:
    """The umu-run the Flatpak ships."""
    found = shutil.which("umu-run")

    if found is None:
        raise SetupError("umu-run was not found.")

    return found


def start(paths: Paths, config: Config, proton: str, args: list[str], inprefix: bool, output: IO | None = None,
          environ: dict[str, str] | None = None, cwd: Path | None = None) -> subprocess.Popen:
    """Start a program in the game environment, in folder `cwd` if given. Its output goes to `output` (a log file), else
    nowhere."""
    (paths.base / "dxvk-cache").mkdir(parents=True, exist_ok=True)
    env = runner_env(paths, config, proton, inprefix, environ)
    sink = output if output is not None else subprocess.DEVNULL

    return subprocess.Popen([umu_run(), *args], env=env, stdout=sink, stderr=sink, stdin=subprocess.DEVNULL, cwd=cwd)


def run(paths: Paths, config: Config, proton: str, args: list[str], inprefix: bool, output: IO | None = None,
        environ: dict[str, str] | None = None, cwd: Path | None = None) -> int:
    """Run a program in the game environment and wait for it. Returns its exit status."""
    return start(paths, config, proton, args, inprefix, output, environ, cwd).wait()


def wineserver(proton: str, environ: dict[str, str] | None = None) -> Path | None:
    """Proton's Wine server: in the Proton folder, or where umu keeps the Protons it downloads."""
    env = os.environ if environ is None else environ
    data_home = env.get("XDG_DATA_HOME") or os.path.join(env.get("HOME", ""), ".local/share")
    candidates = [
        Path(proton) / "files/bin/wineserver",
        Path(data_home) / "umu/compatibilitytools" / proton / "files/bin/wineserver",
    ]

    for candidate in candidates:
        if os.access(candidate, os.X_OK):
            return candidate

    return None


def stop_wine_session(paths: Paths, proton: str, environ: dict[str, str] | None = None) -> bool:
    """End every program in the Wine session and wait until it has saved and exited. False without a Wine server."""
    server = wineserver(proton, environ)

    if server is None:
        return False

    env = dict(os.environ if environ is None else environ)
    env["WINEPREFIX"] = str(paths.prefix)

    subprocess.run([str(server), "-k"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

    try:
        subprocess.run([str(server), "-w"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20,
                       check=False)
    except subprocess.TimeoutExpired:
        pass

    return True


def end_wine_session(paths: Paths, config: Config, environ: dict[str, str] | None = None) -> bool:
    """End every program in the game environment. A program still open would lose its files under it, and Wine would
    write its registry back afterwards. False when there is a game environment but no Wine server to end it with."""
    if not paths.prefix.is_dir():
        return True

    return stop_wine_session(paths, protonpath(paths, config), environ)
