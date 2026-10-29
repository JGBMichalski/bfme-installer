"""engine.proton: getting Proton, the environment umu runs programs with, and ending the Wine session."""
import hashlib
import io
import subprocess
import tarfile
from pathlib import Path

import pytest

from bfme_wizard.engine import download as download_module
from bfme_wizard.engine import proton
from bfme_wizard.engine.config import DEFAULT_PROTONPATH, Config, load
from bfme_wizard.engine.errors import SetupError
from bfme_wizard.engine.paths import Paths

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "bfme-linux-setup.sh"
LSPCI_TWO_CARDS = ("00:02.0 VGA compatible controller: Intel Corporation CometLake-H GT2\n"
                   "01:00.0 3D controller: NVIDIA Corporation TU106GLM [Quadro RTX 3000 Mobile]\n")
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
    monkeypatch.setattr(download_module, "RETRY_DELAY_SEC", 0)


# Getting Proton

def test_another_proton_is_used_as_it_is(paths, file_server):
    config = Config(protonpath="GE-Proton10-1")

    assert proton.ensure_proton(paths, config, url=file_server.url("/p.tar.gz")) == "GE-Proton10-1"
    assert file_server.requests == []


def test_the_pinned_proton_is_downloaded_checked_and_unpacked_once(paths, file_server):
    data = proton_tarball()
    file_server.files["/p.tar.gz"] = data
    seen = []
    target = paths.base / "proton" / DEFAULT_PROTONPATH

    got = proton.ensure_proton(paths, Config(), seen.append, url=file_server.url("/p.tar.gz"),
                               sha256=hashlib.sha256(data).hexdigest())

    assert got == str(target)
    assert (target / "toolmanifest.vdf").read_bytes() == b"manifest"
    assert seen[-1] == 100
    assert not (paths.base / "proton" / ".extracting").exists()
    assert list(paths.downloads.iterdir()) == []

    proton.ensure_proton(paths, Config(), url=file_server.url("/p.tar.gz"), sha256="unused")

    assert len(file_server.requests) == 1


def test_a_wrong_checksum_installs_nothing(paths, file_server):
    file_server.files["/p.tar.gz"] = proton_tarball()

    with pytest.raises(SetupError, match="Checksum mismatch"):
        proton.ensure_proton(paths, Config(), url=file_server.url("/p.tar.gz"), sha256="0" * 64)

    assert not (paths.base / "proton" / DEFAULT_PROTONPATH).exists()


def test_a_tarball_without_proton_in_it_is_an_error(paths, file_server):
    data = proton_tarball(with_manifest=False)
    file_server.files["/p.tar.gz"] = data

    with pytest.raises(SetupError, match="Proton was not found after extracting"):
        proton.ensure_proton(paths, Config(), url=file_server.url("/p.tar.gz"), sha256=hashlib.sha256(data).hexdigest())

    assert not (paths.base / "proton" / DEFAULT_PROTONPATH).exists()


def test_a_broken_tarball_is_an_error(paths, file_server):
    data = b"not a tarball"
    file_server.files["/p.tar.gz"] = data

    with pytest.raises(SetupError, match="Proton could not be unpacked"):
        proton.ensure_proton(paths, Config(), url=file_server.url("/p.tar.gz"), sha256=hashlib.sha256(data).hexdigest())


def test_protonpath_is_our_copy_once_it_is_there(paths):
    assert proton.protonpath(paths, Config()) == DEFAULT_PROTONPATH
    (paths.base / "proton" / DEFAULT_PROTONPATH).mkdir(parents=True)
    assert proton.protonpath(paths, Config()) == str(paths.base / "proton" / DEFAULT_PROTONPATH)
    assert proton.protonpath(paths, Config(protonpath="GE-Proton10-1")) == "GE-Proton10-1"


# NVIDIA

@pytest.mark.parametrize("output,expected", [(LSPCI_TWO_CARDS, True), (LSPCI_ONE_CARD, False),
                                             ("00:02.0 VGA compatible controller: Intel\n01:00.0 VGA compatible controller: AMD\n", False)])
def test_nvidia_offload_only_with_two_cards_one_of_them_nvidia(tmp_path, monkeypatch, output, expected):
    executable(tmp_path / "bin" / "lspci", f"#!/bin/sh\nprintf '%s' '{output}'\n")
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))

    assert proton.use_nvidia() is expected


def test_no_lspci_means_no_offload(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))

    assert proton.use_nvidia() is False


# The environment, compared with the setup script's

def script_runner_env(tmp_path, graphics, config_text, environ):
    """The environment the setup script gives umu when it sets the registry, as {name: value}."""
    dump = tmp_path / "env.txt"
    executable(tmp_path / "bin" / "umu-run", f"#!/bin/sh\nenv > '{dump}'\n")
    base = Path(environ["BFME_HOME"])

    for folder in ("prefix/drive_c/windows", "prefix/drive_c/users/steamuser"):
        (base / folder).mkdir(parents=True, exist_ok=True)

    (base / "config.env").write_text(config_text)
    env = dict(environ, BFME_UMU_RUN=str(tmp_path / "bin" / "umu-run"))
    done = subprocess.run([str(SCRIPT), "graphics", graphics], env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr

    values = {}

    for line in dump.read_text().splitlines():
        name, _, value = line.partition("=")
        values[name] = value

    return values


def changed(env, base):
    """What env sets that base does not have, without the variables every shell sets."""
    shell_own = {"PWD", "OLDPWD", "SHLVL", "_", "BFME_UMU_RUN"}
    out = {}

    for name, value in env.items():
        if name not in shell_own and base.get(name) != value:
            out[name] = value

    return out


@pytest.mark.parametrize("graphics", ["vulkan", "opengl"])
@pytest.mark.parametrize("lspci", [LSPCI_TWO_CARDS, LSPCI_ONE_CARD])
@pytest.mark.parametrize("extra_environ", [{}, {"WINEDLLOVERRIDES": "winemenubuilder.exe=d", "WINE_D3D_CONFIG": "csmt=0x1"}])
def test_the_environment_is_the_scripts(tmp_path, monkeypatch, graphics, lspci, extra_environ):
    executable(tmp_path / "bin" / "lspci", f"#!/bin/sh\nprintf '%s' '{lspci}'\n")
    environ = {
        "PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin", "HOME": str(tmp_path), "BFME_HOME": str(tmp_path / "data"),
        "BFME_PROTONPATH": "fake-proton", **extra_environ,
    }
    config_text = f'BFME_GRAPHICS={graphics}\nBFME_EXTRA_ENV="DXVK_HUD=fps WINEDEBUG=-all"\n'
    from_script = changed(script_runner_env(tmp_path, graphics, config_text, environ), environ)

    monkeypatch.setenv("PATH", environ["PATH"])
    paths = Paths(tmp_path / "data")
    config = load(paths.config, environ)
    from_engine = changed(proton.runner_env(paths, config, "fake-proton", inprefix=True, environ=environ), environ)

    assert from_engine == from_script


def test_the_first_start_is_not_runinprefix(paths):
    env = proton.runner_env(paths, Config(), "p", inprefix=False, environ={})

    assert "PROTON_VERB" not in env


def test_run_starts_umu_with_the_program_and_logs_its_output(tmp_path, monkeypatch, paths):
    executable(tmp_path / "bin" / "umu-run", '#!/bin/sh\necho "args: $* prefix: $WINEPREFIX"\nexit 3\n')
    executable(tmp_path / "bin" / "lspci", "#!/bin/sh\n")
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:/usr/bin:/bin")
    log = tmp_path / "run.log"

    with open(log, "w") as out:
        code = proton.run(paths, Config(), "p", ["reg", "add", "X"], inprefix=True, output=out)

    assert code == 3
    assert log.read_text() == f"args: reg add X prefix: {paths.prefix}\n"
    assert (paths.base / "dxvk-cache").is_dir()


def test_without_umu_run_it_says_so(tmp_path, monkeypatch, paths):
    monkeypatch.setenv("PATH", str(tmp_path))

    with pytest.raises(SetupError, match="umu-run was not found"):
        proton.run(paths, Config(), "p", ["x"], inprefix=True)


# Ending the Wine session, compared with the setup script's

def fake_wineserver(path, log):
    executable(path, f'#!/bin/sh\necho "$WINEPREFIX $*" >> \'{log}\'\n')


def test_the_wine_session_ends_as_the_script_ends_it(tmp_path):
    proton_folder = tmp_path / "my-proton"
    log = tmp_path / "wineserver.log"
    fake_wineserver(proton_folder / "files/bin/wineserver", log)
    environ = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "BFME_HOME": str(tmp_path / "data"),
               "BFME_PROTONPATH": str(proton_folder)}
    paths = Paths(tmp_path / "data")
    (paths.prefix / "drive_c/windows").mkdir(parents=True)
    (paths.prefix / "drive_c/users/steamuser").mkdir(parents=True)

    subprocess.run([str(SCRIPT), "remove", "launcher"], env=environ, capture_output=True, timeout=60)
    from_script = log.read_text()
    log.unlink()
    proton.end_wine_session(paths, load(paths.config, environ), environ)

    assert log.read_text() == from_script == f"{paths.prefix} -k\n{paths.prefix} -w\n"


def test_umus_own_protons_are_found_too(tmp_path, paths):
    log = tmp_path / "wineserver.log"
    fake_wineserver(tmp_path / "xdg/umu/compatibilitytools/GE-Proton10-1/files/bin/wineserver", log)

    assert proton.stop_wine_session(paths, "GE-Proton10-1", {"XDG_DATA_HOME": str(tmp_path / "xdg")})
    assert log.read_text() == f"{paths.prefix} -k\n{paths.prefix} -w\n"


def test_without_a_wine_server_it_says_so(tmp_path, paths):
    assert proton.stop_wine_session(paths, str(tmp_path / "nothing"), {"HOME": str(tmp_path)}) is False


def test_without_a_game_environment_there_is_nothing_to_end(tmp_path, paths):
    log = tmp_path / "wineserver.log"
    fake_wineserver(tmp_path / "my-proton/files/bin/wineserver", log)

    proton.end_wine_session(paths, Config(protonpath=str(tmp_path / "my-proton")), {})

    assert not log.exists()
