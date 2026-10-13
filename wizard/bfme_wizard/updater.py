"""Check GitHub for a newer release and install it through the Flatpak update portal. No GTK.

Two jobs because the portal can only install; it cannot say whether an update exists.
"""
from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

LATEST_URL = "https://github.com/JGBMichalski/bfme-installer/releases/latest"
PORTAL = "org.freedesktop.portal.Flatpak"
PORTAL_PATH = "/org/freedesktop/portal/Flatpak"
MONITOR_IFACE = "org.freedesktop.portal.Flatpak.UpdateMonitor"

# Portal progress "status" values
RUNNING, EMPTY, DONE, FAILED = 0, 1, 2, 3


def parse_version(text: str | None) -> tuple[int, int, int] | None:
    """'v0.2.3' -> (0, 2, 3); None for anything else."""
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", (text or "").strip())
    return tuple(int(part) for part in match.groups()) if match else None  # type: ignore[return-value]


def is_newer(remote: str | None, local: str | None) -> bool:
    r, l = parse_version(remote), parse_version(local)
    return r is not None and l is not None and r > l


def installed_version(app_id: str, metainfo_dir: str = "/app/share/metainfo") -> str | None:
    """Version stamped into the metainfo by the release build; None in development."""
    path = Path(metainfo_dir) / f"{app_id}.metainfo.xml"
    try:
        match = re.search(r'<release\s+version="([^"]+)"', path.read_text(encoding="utf-8"))
    except OSError:
        return None
    return match.group(1) if match and parse_version(match.group(1)) else None


def version_from_redirect(url: str) -> str | None:
    """'https://github.com/o/r/releases/tag/v0.2.3' -> '0.2.3'."""
    tail = url.strip().rsplit("/", 1)[-1]
    return tail.lstrip("v") if parse_version(tail) else None


class Updater:
    """state: idle | available | updating | done | empty | failed"""

    def __init__(
        self,
        app_id: str | None,
        on_change: Callable[[], None],
        *,
        latest_url: str = LATEST_URL,
        local: str | None = None,
        bus_factory: Callable[[], Gio.DBusConnection] | None = None,
    ) -> None:
        self.app_id = app_id
        self.on_change = on_change
        self.latest_url = latest_url
        self.local = local if local is not None else (installed_version(app_id) if app_id else None)
        self._bus_factory = bus_factory or (lambda: Gio.bus_get_sync(Gio.BusType.SESSION, None))
        self.state = "idle"
        self.remote: str | None = None
        self.progress: int | None = None
        self.error = ""
        self._subscription: tuple[Gio.DBusConnection, int] | None = None

    @property
    def enabled(self) -> bool:
        """Only a release build running inside a Flatpak can update itself."""
        return bool(self.app_id) and self.local is not None

    @property
    def manual_command(self) -> str:
        return f"flatpak update --user {self.app_id}"

    def _set(self, state: str) -> None:
        self.state = state
        self.on_change()

    def check(self) -> None:
        if not self.enabled or self.state != "idle":
            return
        try:
            proc = Gio.Subprocess.new(
                ["curl", "-sS", "-m", "10", "-o", "/dev/null", "-w", "%{redirect_url}", self.latest_url],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE,
            )
        except GLib.Error:
            return  # no curl: stay silent

        def done(source: Gio.Subprocess, result: Gio.AsyncResult) -> None:
            try:
                _ok, out, _err = source.communicate_utf8_finish(result)
            except GLib.Error:
                return
            remote = version_from_redirect(out or "")
            if remote and is_newer(remote, self.local):
                self.remote = remote
                self._set("available")

        proc.communicate_utf8_async(None, None, done)

    def install(self) -> None:
        if self.state not in ("available", "empty", "failed"):
            return
        self.progress, self.error = None, ""
        try:
            bus = self._bus_factory()
            reply = bus.call_sync(
                PORTAL, PORTAL_PATH, PORTAL, "CreateUpdateMonitor",
                GLib.Variant("(a{sv})", ({},)), GLib.VariantType("(o)"), Gio.DBusCallFlags.NONE, 10000, None,
            )
            handle = reply.unpack()[0]
        except GLib.Error as error:
            self._fail(error.message)
            return
        self._subscription = (bus, bus.signal_subscribe(
            PORTAL, MONITOR_IFACE, "Progress", handle, None, Gio.DBusSignalFlags.NONE, self._progress,
        ))
        self._monitor = handle
        self._set("updating")
        bus.call(
            PORTAL, handle, MONITOR_IFACE, "Update", GLib.Variant("(sa{sv})", ("", {})), None,
            Gio.DBusCallFlags.NONE, 10000, None, self._update_called,
        )

    def _update_called(self, bus: Gio.DBusConnection, result: Gio.AsyncResult) -> None:
        try:
            bus.call_finish(result)
        except GLib.Error as error:  # e.g. NotSupported: the new version needs more permissions
            self._fail(error.message)

    def _progress(self, _conn, _sender, _path, _iface, _name, params: GLib.Variant) -> None:
        info = params.unpack()[0]
        status = info.get("status", RUNNING)
        if status == RUNNING:
            self.progress = info.get("progress", self.progress)
            self.on_change()
        elif status == DONE:
            self._finish("done")
        elif status == EMPTY:
            self._finish("empty")  # release exists, repository does not have it yet
        else:
            self._fail(info.get("error_message") or info.get("error") or "The update failed.")

    def _fail(self, message: str) -> None:
        self.error = message
        self._finish("failed")

    def _finish(self, state: str) -> None:
        if self._subscription is not None:
            bus, ident = self._subscription
            self._subscription = None
            bus.signal_unsubscribe(ident)
            bus.call(PORTAL, self._monitor, MONITOR_IFACE, "Close", None, None, Gio.DBusCallFlags.NONE, 5000, None, None)
        self._set(state)


def make_updater(on_change: Callable[[], None]) -> Updater:
    """BFME_UPDATE_URL overrides the check URL for tests."""
    return Updater(
        os.environ.get("FLATPAK_ID"),
        on_change,
        latest_url=os.environ.get("BFME_UPDATE_URL", LATEST_URL),
    )
