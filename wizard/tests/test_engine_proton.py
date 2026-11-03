"""engine.proton: getting Proton, the environment umu runs programs with, and ending the Wine session."""

import hashlib
import io
import tarfile

import pytest

from bfme_wizard.engine.config import DEFAULT_PROTONPATH, Config, ConfigFile
from bfme_wizard.engine.download import Download
from bfme_wizard.engine.errors import SetupError
from bfme_wizard.engine.events import Log
from bfme_wizard.engine.paths import Paths
from bfme_wizard.engine.proton import Proton

LSPCI_TWO_CARDS = (
    "00:02.0 VGA compatible controller: Intel Corporation CometLake-H GT2\n"
    "01:00.0 3D controller: NVIDIA Corporation TU106GLM [Quadro RTX 3000 Mobile]\n"
)
LSPCI_ONE_CARD = "01:00.0 VGA compatible controller: NVIDIA Corporation GA104 [GeForce RTX 3070]\n"


def executable(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)


def proton_tarball(with_manifest=True):
    out = io.BytesIO()

    with tarfile.open(fileobj=out, mode="w:gz") as archive:
        names = {f"{DEFAULT_PROTONPATH}/files/bin/wine": b"wine"}

        if with_manifest:
            names[f"{DEFAULT_PROTONPATH}/toolmanifest.vdf"] = b"manifest"

        for name, data in names.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))

    return out.getvalue()


@pytest.fixture
def paths(tmp_path):
    return Paths(tmp_path / "data")


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    monkeypatch.setattr(Download, "RETRY_DELAY_SEC", 0)


# Getting Proton


def test_another_proton_is_used_as_it_is(paths, file_server):
    config = Config(protonpath="GE-Proton10-1")

    assert Proton(paths, config).ensure(url=file_server.url("/p.tar.gz")) == "GE-Proton10-1"
    assert file_server.requests == []


def test_the_pinned_proton_is_downloaded_checked_and_unpacked_once(paths, file_server):
    data = proton_tarball()
    file_server.files["/p.tar.gz"] = data
    seen = []
    target = paths.base / "proton" / DEFAULT_PROTONPATH

    got = Proton(paths, Config()).ensure(
        seen.append, url=file_server.url("/p.tar.gz"), sha256=hashlib.sha256(data).hexdigest()
    )

    assert got == str(target)
    assert (target / "toolmanifest.vdf").read_bytes() == b"manifest"
    assert seen[-1] == 100
    assert not (paths.base / "proton" / ".extracting").exists()
    assert list(paths.downloads.iterdir()) == []

    Proton(paths, Config()).ensure(url=file_server.url("/p.tar.gz"), sha256="unused")

    assert len(file_server.requests) == 1


def test_a_wrong_checksum_installs_nothing(paths, file_server):
    file_server.files["/p.tar.gz"] = proton_tarball()

    with pytest.raises(SetupError, match="Checksum mismatch"):
        Proton(paths, Config()).ensure(url=file_server.url("/p.tar.gz"), sha256="0" * 64)

    assert not (paths.base / "proton" / DEFAULT_PROTONPATH).exists()


def test_a_tarball_without_proton_in_it_is_an_error(paths, file_server):
    data = proton_tarball(with_manifest=False)
    file_server.files["/p.tar.gz"] = data

    with pytest.raises(SetupError, match="Proton was not found after extracting"):
        Proton(paths, Config()).ensure(url=file_server.url("/p.tar.gz"), sha256=hashlib.sha256(data).hexdigest())

    assert not (paths.base / "proton" / DEFAULT_PROTONPATH).exists()


def test_a_broken_tarball_is_an_error(paths, file_server):
    data = b"not a tarball"
    file_server.files["/p.tar.gz"] = data

    with pytest.raises(SetupError, match="Proton could not be unpacked"):
        Proton(paths, Config()).ensure(url=file_server.url("/p.tar.gz"), sha256=hashlib.sha256(data).hexdigest())


def test_protonpath_is_our_copy_once_it_is_there(paths):
    assert Proton(paths, Config()).path == DEFAULT_PROTONPATH
    (paths.base / "proton" / DEFAULT_PROTONPATH).mkdir(parents=True)
    assert Proton(paths, Config()).path == str(paths.base / "proton" / DEFAULT_PROTONPATH)
    assert Proton(paths, Config(protonpath="GE-Proton10-1")).path == "GE-Proton10-1"


# NVIDIA


@pytest.mark.parametrize(
    "output,expected",
    [
        (LSPCI_TWO_CARDS, True),
        (LSPCI_ONE_CARD, False),
        ("00:02.0 VGA compatible controller: Intel\n01:00.0 VGA compatible controller: AMD\n", False),
    ],
)
def test_nvidia_offload_only_with_two_cards_one_of_them_nvidia(tmp_path, monkeypatch, output, expected):
    executable(tmp_path / "bin" / "lspci", f"#!/bin/sh\nprintf '%s' '{output}'\n")
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))

    assert Proton.use_nvidia() is expected


def test_no_lspci_means_no_offload(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))

    assert Proton.use_nvidia() is False


# The environment

WINE_OVERRIDES = {"WINEDLLOVERRIDES": "winemenubuilder.exe=d", "WINE_D3D_CONFIG": "csmt=0x1"}
NVIDIA_OFFLOAD = {
    "__GLX_VENDOR_LIBRARY_NAME": "nvidia",
    "__NV_PRIME_RENDER_OFFLOAD": "1",
    "__VK_LAYER_NV_optimus": "NVIDIA_only",
}
OPENGL = {"PROTON_USE_WINED3D": "1", "WINEDLLOVERRIDES": "d3d8,d3d9,d3d10core,d3d11,dxgi=b"}


def changed(env, base):
    """What env sets that base does not have."""
    out = {}

    for name, value in env.items():
        if base.get(name) != value:
            out[name] = value

    return out


# What Proton.env adds besides the variables every run gets. With WINE_D3D_CONFIG already set, OpenGL keeps it;
# an existing WINEDLLOVERRIDES is appended to.
@pytest.mark.parametrize(
    "graphics,lspci,extra_environ,expected",
    [
        ("vulkan", LSPCI_TWO_CARDS, {}, NVIDIA_OFFLOAD),
        ("vulkan", LSPCI_TWO_CARDS, WINE_OVERRIDES, NVIDIA_OFFLOAD),
        ("vulkan", LSPCI_ONE_CARD, {}, {}),
        ("vulkan", LSPCI_ONE_CARD, WINE_OVERRIDES, {}),
        ("opengl", LSPCI_TWO_CARDS, {}, {**OPENGL, "WINE_D3D_CONFIG": "renderer=gl", **NVIDIA_OFFLOAD}),
        (
            "opengl",
            LSPCI_TWO_CARDS,
            WINE_OVERRIDES,
            {**OPENGL, "WINEDLLOVERRIDES": "d3d8,d3d9,d3d10core,d3d11,dxgi=b,winemenubuilder.exe=d", **NVIDIA_OFFLOAD},
        ),
        ("opengl", LSPCI_ONE_CARD, {}, {**OPENGL, "WINE_D3D_CONFIG": "renderer=gl"}),
        (
            "opengl",
            LSPCI_ONE_CARD,
            WINE_OVERRIDES,
            {**OPENGL, "WINEDLLOVERRIDES": "d3d8,d3d9,d3d10core,d3d11,dxgi=b,winemenubuilder.exe=d"},
        ),
    ],
)
def test_the_environment(tmp_path, monkeypatch, graphics, lspci, extra_environ, expected):
    executable(tmp_path / "bin" / "lspci", f"#!/bin/sh\nprintf '%s' '{lspci}'\n")
    environ = {
        "PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "BFME_HOME": str(tmp_path / "data"),
        "BFME_PROTONPATH": "fake-proton",
        **extra_environ,
    }
    monkeypatch.setenv("PATH", environ["PATH"])
    paths = Paths(tmp_path / "data")
    paths.base.mkdir()
    paths.config.write_text(f'BFME_GRAPHICS={graphics}\nBFME_EXTRA_ENV="DXVK_HUD=fps WINEDEBUG=-all"\n')

    config = ConfigFile(paths.config).load(environ)
    env = Proton(paths, config, "fake-proton", environ).env(True)

    every_run = {
        "DXVK_CONFIG": "d3d9.cachedWriteOnlyBuffers = True",
        "DXVK_HUD": "fps",
        "DXVK_STATE_CACHE_PATH": str(paths.base / "dxvk-cache"),
        "GAMEID": "0",
        "PROTONPATH": "fake-proton",
        "PROTON_VERB": "runinprefix",
        "WINEDEBUG": "-all",
        "WINEPREFIX": str(paths.prefix),
    }
    assert changed(env, environ) == {**every_run, **expected}


def test_the_first_start_is_not_runinprefix(paths):
    env = Proton(paths, Config(), "p", {}).env(False)

    assert "PROTON_VERB" not in env


def test_run_starts_umu_with_the_program_and_logs_its_output(tmp_path, monkeypatch, paths):
    executable(tmp_path / "bin" / "umu-run", '#!/bin/sh\necho "args: $* prefix: $WINEPREFIX"\nexit 3\n')
    executable(tmp_path / "bin" / "lspci", "#!/bin/sh\n")
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:/usr/bin:/bin")
    log = tmp_path / "run.log"

    with open(log, "w") as out:
        code = Proton(paths, Config(), "p").run(["reg", "add", "X"], inprefix=True, output=out)

    assert code == 3
    assert log.read_text() == f"args: reg add X prefix: {paths.prefix}\n"
    assert (paths.base / "dxvk-cache").is_dir()


def test_without_umu_run_it_says_so(tmp_path, monkeypatch, paths):
    monkeypatch.setenv("PATH", str(tmp_path))

    with pytest.raises(SetupError, match="umu-run was not found"):
        Proton(paths, Config(), "p").run(["x"], inprefix=True)


# Ending the Wine session


def fake_wineserver(path, log):
    executable(path, f"#!/bin/sh\necho \"$WINEPREFIX $*\" >> '{log}'\n")


def test_the_wine_session_is_killed_and_waited_for(tmp_path):
    proton_folder = tmp_path / "my-proton"
    log = tmp_path / "wineserver.log"
    fake_wineserver(proton_folder / "files/bin/wineserver", log)
    environ = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "BFME_HOME": str(tmp_path / "data"),
        "BFME_PROTONPATH": str(proton_folder),
    }
    paths = Paths(tmp_path / "data")
    (paths.prefix / "drive_c/windows").mkdir(parents=True)
    (paths.prefix / "drive_c/users/steamuser").mkdir(parents=True)

    Proton(paths, ConfigFile(paths.config).load(environ), environ=environ).end_session()

    assert log.read_text() == f"{paths.prefix} -k\n{paths.prefix} -w\n"


def test_umus_own_protons_are_found_too(tmp_path, paths):
    log = tmp_path / "wineserver.log"
    fake_wineserver(tmp_path / "xdg/umu/compatibilitytools/GE-Proton10-1/files/bin/wineserver", log)

    assert Proton(paths, Config(), "GE-Proton10-1", {"XDG_DATA_HOME": str(tmp_path / "xdg")}).stop_session()
    assert log.read_text() == f"{paths.prefix} -k\n{paths.prefix} -w\n"


def test_without_a_wine_server_it_says_so(tmp_path, paths):
    assert Proton(paths, Config(), str(tmp_path / "nothing"), {"HOME": str(tmp_path)}).stop_session() is False


def test_without_a_game_environment_there_is_nothing_to_end(tmp_path, paths):
    log = tmp_path / "wineserver.log"
    fake_wineserver(tmp_path / "my-proton/files/bin/wineserver", log)

    Proton(paths, Config(protonpath=str(tmp_path / "my-proton")), environ={}).end_session()

    assert not log.exists()


def test_the_proton_download_says_so(paths, file_server):
    data = proton_tarball()
    file_server.files["/p.tar.gz"] = data
    events = []

    Proton(paths, Config()).ensure(
        url=file_server.url("/p.tar.gz"), sha256=hashlib.sha256(data).hexdigest(), emit=events.append
    )

    assert events == [Log(f"Downloading {DEFAULT_PROTONPATH}.tar.gz.")]


# The graphics card and DXVK's settings


def card_env(tmp_path, monkeypatch, gpu, lspci):
    executable(tmp_path / "bin" / "lspci", f"#!/bin/sh\nprintf '%s' '{lspci}'\n")
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    return Proton(Paths(tmp_path / "data"), Config(gpu=gpu), "p", {}).env(True)


CARD_VARIABLES = ("__NV_PRIME_RENDER_OFFLOAD", "__GLX_VENDOR_LIBRARY_NAME", "__VK_LAYER_NV_optimus", "DRI_PRIME")


def card_choice(env):
    chosen = {}

    for name in CARD_VARIABLES:
        if name in env:
            chosen[name] = env[name]

    return chosen


@pytest.mark.parametrize(
    "gpu, lspci, expected",
    [
        ("auto", LSPCI_TWO_CARDS, NVIDIA_OFFLOAD),
        ("auto", LSPCI_ONE_CARD, {}),
        ("dedicated", LSPCI_ONE_CARD, {**NVIDIA_OFFLOAD, "DRI_PRIME": "1"}),
        ("dedicated", LSPCI_TWO_CARDS, {**NVIDIA_OFFLOAD, "DRI_PRIME": "1"}),
        (
            "integrated",
            LSPCI_TWO_CARDS,
            {"__VK_LAYER_NV_optimus": "non_NVIDIA_only", "__GLX_VENDOR_LIBRARY_NAME": "mesa", "DRI_PRIME": "0"},
        ),
    ],
)
def test_the_graphics_card_the_player_chose(tmp_path, monkeypatch, gpu, lspci, expected):
    assert card_choice(card_env(tmp_path, monkeypatch, gpu, lspci)) == expected


def test_the_cards_are_listed_as_lspci_names_them(tmp_path, monkeypatch):
    executable(tmp_path / "bin" / "lspci", f"#!/bin/sh\nprintf '%s' '{LSPCI_TWO_CARDS}'\n")
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))

    assert len(Proton.graphics_cards()) == 2


@pytest.mark.parametrize(
    "player, expected",
    [
        (None, "d3d9.cachedWriteOnlyBuffers = True"),
        ("dxgi.syncInterval = 0", "d3d9.cachedWriteOnlyBuffers = True; dxgi.syncInterval = 0"),
    ],
)
def test_dxvks_settings_and_the_players_own(paths, player, expected):
    environ = {}

    if player:
        environ["DXVK_CONFIG"] = player

    env = Proton(paths, Config(), "p", environ).env(True)

    assert env["DXVK_CONFIG"] == expected
