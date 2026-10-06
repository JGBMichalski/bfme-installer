import os
import stat
import tempfile
import unittest

from gi.repository import GLib

from bfme_wizard.updater import (
    Updater, installed_version, is_newer, parse_version, version_from_redirect,
)


class Versions(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_version("v0.2.3"), (0, 2, 3))
        self.assertEqual(parse_version("10.0.12"), (10, 0, 12))
        for bad in ("dev", "", None, "1.2", "1.2.3-rc1", "v1.2.3.4"):
            self.assertIsNone(parse_version(bad))

    def test_newer_compares_numbers_not_text(self):
        self.assertTrue(is_newer("0.2.10", "0.2.9"))
        self.assertTrue(is_newer("v1.0.0", "0.9.9"))
        self.assertFalse(is_newer("0.2.2", "0.2.2"))
        self.assertFalse(is_newer("0.2.1", "0.2.2"))

    def test_nothing_is_newer_for_a_development_build_or_a_bad_answer(self):
        self.assertFalse(is_newer("0.2.3", "dev"))
        self.assertFalse(is_newer(None, "0.2.2"))
        self.assertFalse(is_newer("garbage", "0.2.2"))

    def test_redirect(self):
        self.assertEqual(version_from_redirect("https://github.com/o/r/releases/tag/v0.2.3\n"), "0.2.3")
        self.assertIsNone(version_from_redirect(""))
        self.assertIsNone(version_from_redirect("https://github.com/o/r/releases"))

    def test_installed_version_from_the_metainfo(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "x.Y.metainfo.xml"), "w") as f:
            f.write('<releases>\n  <release version="0.2.2" date="2026-10-06"/>\n</releases>')
        self.assertEqual(installed_version("x.Y", d), "0.2.2")
        self.assertIsNone(installed_version("missing.App", d))
        with open(os.path.join(d, "dev.App.metainfo.xml"), "w") as f:
            f.write('<release version="dev" date="2026-10-06"/>')
        self.assertIsNone(installed_version("dev.App", d))


FAKE_CURL = """#!/usr/bin/env bash
case "$FAKE_CURL_MODE" in
  new)  printf 'https://github.com/o/r/releases/tag/v0.3.0' ;;
  same) printf 'https://github.com/o/r/releases/tag/v0.2.2' ;;
  none) printf '' ;;
  fail) exit 6 ;;
esac
"""


class Check(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "curl")
        with open(path, "w") as f:
            f.write(FAKE_CURL)
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
        self._path = os.environ["PATH"]
        os.environ["PATH"] = d + os.pathsep + self._path

    def tearDown(self):
        os.environ["PATH"] = self._path

    def run_check(self, mode, app_id="com.example.App", local="0.2.2"):
        os.environ["FAKE_CURL_MODE"] = mode
        loop, states = GLib.MainLoop(), []
        updater = Updater(app_id, lambda: (states.append(updater.state), loop.quit()), local=local)
        updater.check()
        GLib.timeout_add(1500, loop.quit)
        loop.run()
        return updater, states

    def test_a_newer_release_makes_an_update_available(self):
        u, states = self.run_check("new")
        self.assertEqual((u.state, u.remote, states), ("available", "0.3.0", ["available"]))

    def test_the_same_release_changes_nothing(self):
        u, states = self.run_check("same")
        self.assertEqual((u.state, states), ("idle", []))

    def test_no_answer_and_curl_errors_change_nothing(self):
        for mode in ("none", "fail"):
            self.assertEqual(self.run_check(mode)[0].state, "idle")

    def test_a_development_build_or_a_non_flatpak_run_never_checks(self):
        self.assertEqual(self.run_check("new", local=None)[0].state, "idle")
        u = Updater(None, lambda: None, local="0.2.2")
        self.assertFalse(u.enabled)


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


class Install(unittest.TestCase):
    def make(self, bus):
        states = []
        u = Updater("com.example.App", lambda: states.append(u.state), local="0.2.2", bus_factory=lambda: bus)
        u.state, u.remote = "available", "0.3.0"
        return u, states

    def test_a_successful_update(self):
        bus = FakeBus(); u, states = self.make(bus)
        u.install()
        bus.emit(op=0, n_ops=1, progress=40, status=0)
        self.assertEqual((u.state, u.progress), ("updating", 40))
        bus.emit(op=0, n_ops=1, progress=100, status=2)
        self.assertEqual(u.state, "done")
        self.assertEqual(bus.calls, ["CreateUpdateMonitor", "Update", "Close"])
        self.assertTrue(bus.unsubscribed)

    def test_the_repository_does_not_have_the_release_yet(self):
        bus = FakeBus(); u, _ = self.make(bus)
        u.install(); bus.emit(status=1)
        self.assertEqual(u.state, "empty")
        u.install()  # "try again" is allowed
        self.assertEqual(u.state, "updating")

    def test_a_failed_update_keeps_the_portals_message(self):
        bus = FakeBus(); u, _ = self.make(bus)
        u.install(); bus.emit(status=3, error_message="Disk is full")
        self.assertEqual((u.state, u.error), ("failed", "Disk is full"))

    def test_new_permissions_mean_the_portal_refuses(self):
        bus = FakeBus(fail_update="org.freedesktop.DBus.Error.NotSupported: new permissions"); u, _ = self.make(bus)
        u.install()
        self.assertEqual(u.state, "failed")
        self.assertIn("NotSupported", u.error)
        self.assertEqual(u.manual_command, "flatpak update --user com.example.App")

    def test_no_portal_fails_cleanly(self):
        bus = FakeBus(fail_create="no such service"); u, _ = self.make(bus)
        u.install()
        self.assertEqual((u.state, u.error), ("failed", "no such service"))

    def test_install_does_nothing_unless_an_update_is_available(self):
        bus = FakeBus(); u, _ = self.make(bus); u.state = "idle"
        u.install()
        self.assertEqual((u.state, bus.calls), ("idle", []))
        u.state = "updating"; u.install()
        self.assertEqual(bus.calls, [])


if __name__ == "__main__":
    unittest.main()
