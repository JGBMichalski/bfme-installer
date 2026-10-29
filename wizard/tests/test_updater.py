import os
import stat

import pytest
from gi.repository import GLib

from bfme_wizard.updater import (
    Updater, installed_version, is_newer, parse_version, version_from_redirect,
)


def test_parse():
    assert parse_version("v0.2.3") == (0, 2, 3)
    assert parse_version("10.0.12") == (10, 0, 12)
    for bad in ("dev", "", None, "1.2", "1.2.3-rc1", "v1.2.3.4"):
        assert parse_version(bad) is None, bad


def test_newer_compares_numbers_not_text():
    assert is_newer("0.2.10", "0.2.9")
    assert is_newer("v1.0.0", "0.9.9")
    assert not is_newer("0.2.2", "0.2.2")
    assert not is_newer("0.2.1", "0.2.2")


def test_nothing_is_newer_for_a_development_build_or_a_bad_answer():
    assert not is_newer("0.2.3", "dev")
    assert not is_newer(None, "0.2.2")
    assert not is_newer("garbage", "0.2.2")


def test_redirect():
    assert version_from_redirect("https://github.com/o/r/releases/tag/v0.2.3\n") == "0.2.3"
    assert version_from_redirect("") is None
    assert version_from_redirect("https://github.com/o/r/releases") is None


def test_installed_version_from_the_metainfo(tmp_path):
    (tmp_path / "x.Y.metainfo.xml").write_text('<releases>\n  <release version="0.2.2" date="2026-10-06"/>\n</releases>')
    assert installed_version("x.Y", str(tmp_path)) == "0.2.2"
    assert installed_version("missing.App", str(tmp_path)) is None
    (tmp_path / "dev.App.metainfo.xml").write_text('<release version="dev" date="2026-10-06"/>')
    assert installed_version("dev.App", str(tmp_path)) is None


FAKE_CURL = """#!/usr/bin/env bash
case "$FAKE_CURL_MODE" in
  new)  printf 'https://github.com/o/r/releases/tag/v0.3.0' ;;
  same) printf 'https://github.com/o/r/releases/tag/v0.2.2' ;;
  none) printf '' ;;
  fail) exit 6 ;;
esac
"""


@pytest.fixture
def run_check(tmp_path, monkeypatch):
    """Runs a check against a fake curl on the PATH that answers as `mode` says."""
    curl = tmp_path / "curl"
    curl.write_text(FAKE_CURL)
    curl.chmod(curl.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")

    def run(mode, app_id="com.example.App", local="0.2.2"):
        monkeypatch.setenv("FAKE_CURL_MODE", mode)
        loop, states = GLib.MainLoop(), []
        updater = Updater(app_id, lambda: (states.append(updater.state), loop.quit()), local=local)
        updater.check()
        GLib.timeout_add(1500, loop.quit)
        loop.run()
        return updater, states
    return run


def test_a_newer_release_makes_an_update_available(run_check):
    u, states = run_check("new")
    assert (u.state, u.remote, states) == ("available", "0.3.0", ["available"])


def test_the_same_release_changes_nothing(run_check):
    u, states = run_check("same")
    assert (u.state, states) == ("idle", [])


@pytest.mark.parametrize("mode", ("none", "fail"))
def test_no_answer_and_curl_errors_change_nothing(run_check, mode):
    assert run_check(mode)[0].state == "idle"


def test_a_development_build_or_a_non_flatpak_run_never_checks(run_check):
    assert run_check("new", local=None)[0].state == "idle"
    u = Updater(None, lambda: None, local="0.2.2")
    assert not u.enabled


class FakeBus:
    """Stands in for the session bus and the Flatpak update portal."""

    def __init__(self, fail_create=None, fail_update=None):
        self.fail_create, self.fail_update = fail_create, fail_update
        self.calls, self.callback, self.unsubscribed = [], None, False

    def call_sync(self, _name, _path, _iface, method, _params, _reply, _flags, _timeout, _cancel):
        self.calls.append(method)
        if self.fail_create:
            raise GLib.Error(self.fail_create)
        return GLib.Variant("(o)", ("/org/freedesktop/portal/Flatpak/update_monitor/1/2",))

    def call(self, _name, _path, _iface, method, _params, _reply, _flags, _timeout, _cancel, callback):
        self.calls.append(method)
        if callback:
            callback(self, method)

    def call_finish(self, _result):
        if self.fail_update:
            raise GLib.Error(self.fail_update)

    def signal_subscribe(self, _s, _i, _name, _path, _a, _f, callback):
        self.callback = callback
        return 7

    def signal_unsubscribe(self, _ident):
        self.unsubscribed = True

    def emit(self, **info):
        self.callback(None, None, None, None, "Progress", GLib.Variant("(a{sv})", ({k: GLib.Variant("u" if isinstance(v, int) else "s", v) for k, v in info.items()},)))


def make(bus):
    states = []
    u = Updater("com.example.App", lambda: states.append(u.state), local="0.2.2", bus_factory=lambda: bus)
    u.state, u.remote = "available", "0.3.0"
    return u, states


def test_a_successful_update():
    bus = FakeBus(); u, states = make(bus)
    u.install()
    bus.emit(op=0, n_ops=1, progress=40, status=0)
    assert (u.state, u.progress) == ("updating", 40)
    bus.emit(op=0, n_ops=1, progress=100, status=2)
    assert u.state == "done"
    assert bus.calls == ["CreateUpdateMonitor", "Update", "Close"]
    assert bus.unsubscribed


def test_the_repository_does_not_have_the_release_yet():
    bus = FakeBus(); u, _ = make(bus)
    u.install(); bus.emit(status=1)
    assert u.state == "empty"
    u.install()  # "try again" is allowed
    assert u.state == "updating"


def test_a_failed_update_keeps_the_portals_message():
    bus = FakeBus(); u, _ = make(bus)
    u.install(); bus.emit(status=3, error_message="Disk is full")
    assert (u.state, u.error) == ("failed", "Disk is full")


def test_new_permissions_mean_the_portal_refuses():
    bus = FakeBus(fail_update="org.freedesktop.DBus.Error.NotSupported: new permissions"); u, _ = make(bus)
    u.install()
    assert u.state == "failed"
    assert "NotSupported" in u.error
    assert u.manual_command == "flatpak update --user com.example.App"


def test_no_portal_fails_cleanly():
    bus = FakeBus(fail_create="no such service"); u, _ = make(bus)
    u.install()
    assert (u.state, u.error) == ("failed", "no such service")


def test_install_does_nothing_unless_an_update_is_available():
    bus = FakeBus(); u, _ = make(bus); u.state = "idle"
    u.install()
    assert (u.state, bus.calls) == ("idle", [])
    u.state = "updating"; u.install()
    assert bus.calls == []
