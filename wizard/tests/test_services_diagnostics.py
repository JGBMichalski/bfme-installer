"""services.diagnostics: the report Copy diagnostics makes, and where the logs are."""

import time
from pathlib import Path

from bfme_wizard.control.model import SetupModel
from bfme_wizard.engine.events import Check, Fix
from bfme_wizard.services.diagnostics import Diagnostics
from tests.helpers import status


def feed(model, *events):
    for event in events:
        model.feed_event(event)


# Diagnostics


def test_report_has_the_version_checks_fixes_and_log_tails(tmp_path):
    logs = tmp_path
    (logs / "aio-launcher-20260101-000000.log").write_text("old\n")
    time.sleep(0.02)
    (logs / "aio-launcher-20260102-000000.log").write_text("\n".join(f"line {i}" for i in range(100)))
    (logs / "arena-20260101-000000.log").write_text("arena says hi\n")
    m = SetupModel()
    m.status = status("aio-launcher", "arena", "bfme2", prefix_ready=True)
    feed(m, Check("cpu", "ok", "x86_64 processor"), Check("f", "fail", "parts missing"), Fix("f", "flatpak install X"))
    report = Diagnostics(logs).report("0.2.9", m)
    for expected in (
        "Version: 0.2.9",
        "Runner: proton",
        "Graphics: Vulkan (DXVK)",
        "Setup: prefix ready, aio-launcher installed, arena installed",
        "BFME 2 installed",
        "BFME missing",
        "[FAILED] parts missing",
        "fix: flatpak install X",
        "[ok] x86_64 processor",
        "--- latest AIO Launcher log (aio-launcher-20260102-000000.log",
        "line 99",
        "arena says hi",
        "--- no prefix creation log ---",
    ):
        assert expected in report
    assert "line 59" not in report  # only the last 40 lines
    assert "old\n" not in report  # only the newest log


def test_the_report_names_the_graphics_backend(tmp_path):
    m = SetupModel()
    m.status = status(graphics="opengl")
    report = Diagnostics(tmp_path).report("dev", m)
    assert "Graphics: OpenGL (WineD3D)" in report


def test_a_report_before_any_check_or_log_still_works(tmp_path):
    report = Diagnostics(tmp_path).report("dev", SetupModel())
    assert "(not run yet)" in report
    assert "--- no AIO Launcher log ---" in report


def test_the_report_says_what_computer_it_came_from(tmp_path):
    report = Diagnostics(tmp_path).report(
        "dev", SetupModel(), system=["Desktop: KDE, wayland session", "Graphics card: NVIDIA X"]
    )
    assert "Desktop: KDE, wayland session\nGraphics card: NVIDIA X\n" in report


def test_system_lines_name_the_session_and_the_desktop():
    lines = Diagnostics(Path("/nowhere"), {"XDG_SESSION_TYPE": "wayland", "XDG_CURRENT_DESKTOP": "KDE"}).system_lines()
    assert "Desktop: KDE, wayland session" in lines
    assert any(line.startswith("Graphics card: ") for line in lines)
    assert any(line.startswith("NVIDIA driver: ") for line in lines)
    assert any(line.startswith("Vulkan: ") for line in lines)


def test_system_lines_guess_the_session_without_a_session_type():
    assert "Desktop: unknown, x11 session" in Diagnostics(Path("/nowhere"), {"DISPLAY": ":0"}).system_lines()
    assert (
        "Desktop: unknown, wayland session"
        in Diagnostics(Path("/nowhere"), {"WAYLAND_DISPLAY": "wayland-0"}).system_lines()
    )
    assert "Desktop: unknown, unknown session" in Diagnostics(Path("/nowhere"), {}).system_lines()


def test_log_helpers(tmp_path):
    d = tmp_path
    assert Diagnostics(d).newest_log("x") is None
    assert Diagnostics(d).any_log() is None
    assert Diagnostics(d / "missing").any_log() is None
    (d / "prefix-create.log").write_text("a\nb\nc")
    assert Diagnostics(d).newest_log("prefix-create").name == "prefix-create.log"
    assert Diagnostics(d).any_log().name == "prefix-create.log"
    assert Diagnostics(d).tail(d / "prefix-create.log", 2) == "b\nc"
    assert "could not read" in Diagnostics(d).tail(d / "nope.log")
