"""engine.doctor: the system check, compared with the setup script's in the Flatpak."""
import subprocess
from collections import namedtuple
from pathlib import Path

import pytest

from bfme_wizard.engine import doctor, graphics
from bfme_wizard.engine.config import Config, load
from bfme_wizard.engine.events import Check, Fix, Log
from bfme_wizard.engine.paths import Paths

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "bfme-linux-setup.sh"
Usage = namedtuple("Usage", "total used free")
KEPT = ("cpu", "flatpak-32bit", "graphics", "disk", "firewall")


@pytest.fixture
def paths(tmp_path):
    return Paths(tmp_path / "data")


@pytest.fixture
def probe(monkeypatch):
    answer = {"value": ("vulkan", "Vulkan 1.4 on Test GPU")}
    monkeypatch.setattr(graphics, "probe", lambda: answer["value"])
    return answer


def lib_root(tmp_path, *files):
    """A stand-in for /usr/lib holding these files and folders (folders end in /)."""
    root = tmp_path / "lib"

    for name in files:
        if name.endswith("/"):
            (root / name).mkdir(parents=True, exist_ok=True)
        else:
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).touch()

    return root


def run(paths, config, root):
    events = []
    ok = doctor.run_checks(paths, config, events.append, root)
    return ok, events


def logs(events):
    out = []

    for event in events:
        if isinstance(event, Log):
            out.append(event.text)

    return out


LD = "i386-linux-gnu/ld-linux.so.2"
GL32 = "i386-linux-gnu/GL/default/"


# The 32-bit extensions

@pytest.mark.parametrize("files,missing", [
    ((), True),
    ((LD,), True),
    ((GL32,), True),
    ((LD, GL32), False),
    ((LD, GL32, "x86_64-linux-gnu/GL/nvidia-550-107-02/"), True),
    ((LD, "x86_64-linux-gnu/GL/nvidia-550-107-02/", "i386-linux-gnu/GL/nvidia-550-107-02/"), False),
])
def test_the_32bit_extensions(tmp_path, files, missing):
    assert doctor.flatpak_32bit_missing(lib_root(tmp_path, *files)) is missing


def test_the_fix_names_each_nvidia_drivers_32bit_match(tmp_path):
    root = lib_root(tmp_path, "x86_64-linux-gnu/GL/nvidia-560-35-03/", "x86_64-linux-gnu/GL/nvidia-550-107-02/")

    assert doctor.flatpak_32bit_fix(root) == (
        "flatpak install --user flathub org.freedesktop.Platform.Compat.i386//25.08 "
        "org.freedesktop.Platform.GL32.default//25.08 org.freedesktop.Platform.GL32.nvidia-550-107-02 "
        "org.freedesktop.Platform.GL32.nvidia-560-35-03")


def test_missing_extensions_fail_the_check_with_help_and_a_fix(tmp_path, paths, probe):
    ok, events = run(paths, Config(), lib_root(tmp_path))

    assert ok is False
    assert Check("flatpak-32bit", "fail", "the 32-bit Flatpak extensions are not installed") in events
    assert Fix("flatpak-32bit", doctor.flatpak_32bit_fix(lib_root(tmp_path))) in events
    assert "         The 32-bit parts of the Flatpak runtime are not installed, so the games and apps cannot start." in logs(events)
    assert logs(events)[-1] == "1 problem(s) must be fixed first."


# The other checks

def test_a_ready_computer_passes(tmp_path, paths, probe, monkeypatch):
    monkeypatch.setattr(doctor.shutil, "disk_usage", lambda path: Usage(0, 0, 100 * 1024 ** 3))
    ok, events = run(paths, Config(), lib_root(tmp_path, LD, GL32))

    checks = [e for e in events if isinstance(e, Check)]
    assert ok is True
    assert [c.id for c in checks] == list(KEPT)
    assert {c.level for c in checks} == {"ok"}
    assert logs(events)[0] == "System check (graphics: Vulkan (DXVK))"
    assert "  [ok]   free disk space: 100 GB (need about 30 GB)" in logs(events)
    assert logs(events)[-1] == "Ready."


def test_another_processor_fails(tmp_path, paths, probe, monkeypatch):
    monkeypatch.setattr(doctor.platform, "machine", lambda: "aarch64")
    ok, events = run(paths, Config(), lib_root(tmp_path, LD, GL32))

    assert ok is False
    assert Check("cpu", "fail", "processor is aarch64; only x86_64 is supported") in events


def test_little_disk_space_is_a_warning(tmp_path, paths, probe, monkeypatch):
    monkeypatch.setattr(doctor.shutil, "disk_usage", lambda path: Usage(0, 0, 5 * 1024 ** 3))
    ok, events = run(paths, Config(), lib_root(tmp_path, LD, GL32))

    assert ok is True
    assert Check("disk", "warn", f"less than 30 GB free where the data goes ({paths.base})") in events
    assert logs(events)[-1] == "Ready, with 1 warning(s) above."


def test_disk_space_is_measured_where_the_data_will_go(tmp_path, paths, probe, monkeypatch):
    asked = []

    def disk_usage(path):
        asked.append(path)
        return Usage(0, 0, 100 * 1024 ** 3)

    monkeypatch.setattr(doctor.shutil, "disk_usage", disk_usage)
    run(paths, Config(), lib_root(tmp_path, LD, GL32))

    assert asked == [tmp_path]


# Parity with the script's system check in the Flatpak

def script_checks(tmp_path, paths, probe_output, config_text):
    probe_file = tmp_path / "probe"
    probe_file.write_text(f"#!/bin/sh\necho '{probe_output}'\n")
    probe_file.chmod(0o755)
    paths.base.mkdir(parents=True, exist_ok=True)
    paths.config.write_text(config_text)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "BFME_HOME": str(paths.base), "FLATPAK_ID": "com.example.App",
           "BFME_VULKAN_PROBE": str(probe_file)}
    out = subprocess.run([str(SCRIPT), "--machine", "doctor"], env=env, capture_output=True, text=True, timeout=60).stdout
    found = []

    for line in out.splitlines():
        parts = line.split(" ", 3)

        if line.startswith("@bfme CHECK ") and parts[2] in KEPT:
            found.append(line)

        if line.startswith("@bfme FIX "):
            found.append(line)

    return found


def engine_checks(events):
    found = []

    for event in events:
        if isinstance(event, Check):
            found.append(f"@bfme CHECK {event.id} {event.level} {event.message}")

        if isinstance(event, Fix):
            found.append(f"@bfme FIX {event.check_id} {event.command}")

    return found


@pytest.mark.parametrize("probe_output", ["vulkan Vulkan 1.4 on Test GPU", "opengl no graphics card with Vulkan was found",
                                          "unknown could not check Vulkan (boom)"])
@pytest.mark.parametrize("config_text", ["", "BFME_GRAPHICS=vulkan\n", "BFME_GRAPHICS=opengl\n"])
def test_the_checks_are_the_scripts(tmp_path, paths, probe, probe_output, config_text):
    from_script = script_checks(tmp_path, paths, probe_output, config_text)
    backend, _, why = probe_output.partition(" ")
    probe["value"] = (backend, why)

    _, events = run(paths, load(paths.config, {}), doctor.LIB_ROOT)

    assert engine_checks(events) == from_script


def test_the_help_for_missing_extensions_is_the_scripts(tmp_path, paths, probe):
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "BFME_HOME": str(paths.base), "FLATPAK_ID": "com.example.App",
           "BFME_VULKAN_PROBE": "/bin/false"}
    out = subprocess.run([str(SCRIPT), "doctor"], env=env, capture_output=True, text=True, timeout=60).stdout
    from_script = [line for line in out.splitlines() if line.startswith("         ")]

    _, events = run(paths, Config(), lib_root(tmp_path))
    from_engine = [line for line in logs(events) if line.startswith("         ")]

    if not doctor.flatpak_32bit_missing():
        pytest.skip("this computer has the 32-bit libraries, so the script prints no help")

    assert from_engine == from_script
