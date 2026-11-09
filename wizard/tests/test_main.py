"""__main__: the command line, and what a menu shortcut does."""

import contextlib
import io
from unittest import mock

import pytest

from bfme_wizard.__main__ import CommandLine, main
from bfme_wizard.engine.menu_shortcuts import MenuShortcuts
from bfme_wizard.engine.programs import AIO_LAUNCHER


def feed(model, *events):
    for event in events:
        model.feed_event(event)


# Menu entries


# "launcher": shortcuts made before the AIO Launcher was called "aio-launcher".
@pytest.mark.parametrize(
    "args, app",
    [
        (["--open", "aio-launcher"], "aio-launcher"),
        (["--open", "launcher"], "aio-launcher"),
        (["x", "--open", "arena"], "arena"),
        ([], None),
        (["--open"], None),
        (["--open", "bfme2"], None),
        (["aio-launcher"], None),
    ],
)
def test_parse_args(args, app):
    assert CommandLine(["bfme-installer", *args]).offer == app


def test_a_shortcut_whose_program_is_there_opens_it_without_a_window():
    order = []

    def sync_shortcuts(emit, cancel):
        order.append("sync")
        return 0

    def open_program(program, emit, cancel):
        order.append(program)
        return 0

    with (
        mock.patch("bfme_wizard.__main__.Engine.ready_to_open", return_value=True) as ready,
        mock.patch("bfme_wizard.__main__.Engine.sync_shortcuts", side_effect=sync_shortcuts),
        mock.patch("bfme_wizard.__main__.Engine.open_program", side_effect=open_program),
        mock.patch("sys.argv", ["bfme-installer", "--open", "launcher"]),
    ):
        assert main() == 0

    ready.assert_called_once_with("aio-launcher")
    assert order == ["sync", "aio-launcher"]  # the shortcuts first, then the program


def test_the_program_opens_even_when_the_shortcuts_cannot_be_synced():
    with (
        mock.patch("bfme_wizard.__main__.Engine.ready_to_open", return_value=True),
        mock.patch("bfme_wizard.__main__.Engine.sync_shortcuts", return_value=1),
        mock.patch("bfme_wizard.__main__.Engine.open_program", return_value=0) as open_program,
        mock.patch("sys.argv", ["bfme-installer", "--open", "arena"]),
    ):
        assert main() == 0

    assert open_program.call_args.args[0] == "arena"


def test_a_2x_shortcut_is_replaced_the_first_time_it_is_used(tmp_path, monkeypatch):
    # 2.x named the AIO Launcher's shortcut <app id>.Launcher.desktop and passed --open launcher.
    from bfme_wizard.engine.paths import Paths

    app = "com.example.App"
    home = tmp_path / "home"
    apps = home / ".local/share/applications"
    apps.mkdir(parents=True)
    (apps / f"{app}.Launcher.desktop").write_text("[Desktop Entry]\nExec=... --open launcher\n")
    data = Paths(tmp_path / "data")

    for folder in ("windows", "users/steamuser"):
        (data.drive_c / folder).mkdir(parents=True)

    AIO_LAUNCHER.exe(data).parent.mkdir(parents=True)
    AIO_LAUNCHER.exe(data).write_text("x")
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(f"20 1 0:20 / / rw - tmpfs tmpfs rw\n40 20 0:40 / {home} rw - ext4 /dev/sda1 rw\n")
    monkeypatch.setattr(MenuShortcuts, "MOUNTINFO", mountinfo)

    for name, value in {"HOME": str(home), "BFME_HOME": str(data.base), "FLATPAK_ID": app}.items():
        monkeypatch.setenv(name, value)

    with (
        mock.patch("bfme_wizard.__main__.Engine.open_program", return_value=0),
        mock.patch("sys.argv", ["bfme-installer", "--open", "launcher"]),
    ):
        assert main() == 0

    names = []

    for path in sorted(apps.iterdir()):
        names.append(path.name)

    assert names == [f"{app}.AioLauncher.desktop"]


def test_a_shortcut_whose_program_is_gone_opens_the_wizard_offering_it(monkeypatch, gtk):
    from bfme_wizard.ui import app as ui

    with (
        mock.patch("bfme_wizard.__main__.Engine.ready_to_open", return_value=False),
        mock.patch("bfme_wizard.__main__.Engine.open_program") as open_program,
        mock.patch("bfme_wizard.__main__.CommandLine.has_display", return_value=True),
        mock.patch.object(ui, "WizardApp") as app,
        mock.patch("sys.argv", ["bfme-installer", "--open", "aotr"]),
    ):
        app.return_value.run.return_value = 0
        assert main() == 0

    open_program.assert_not_called()
    assert app.call_args.kwargs["offer"] == "aotr"


def test_without_a_display_it_says_so_and_stops():
    err = io.StringIO()

    with (
        mock.patch("bfme_wizard.__main__.CommandLine.has_display", return_value=False),
        mock.patch("sys.argv", ["bfme-installer"]),
        contextlib.redirect_stderr(err),
    ):
        assert main() == 1

    assert "No display found, so the setup wizard cannot open." in err.getvalue()
