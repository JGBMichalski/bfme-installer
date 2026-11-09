import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


@pytest.fixture
def gtk():
    """The Gtk module, or skip: the CI job has only the GLib bindings and no display."""
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Gtk
    except (ValueError, ImportError):
        pytest.skip("GTK is not installed")
    if not Gtk.init_check():
        pytest.skip("no display")
    return Gtk


class FileServer:
    """A local web server for download tests.

    files: {path: bytes} to serve. failures: status codes to answer with first, one per request.
    requests: (path, Range header or None) of every request. ignore_range: answer every request with the whole file.
    no_length: leave out Content-Length.
    """

    def __init__(self):
        self.files = {}
        self.failures = []
        self.requests = []
        self.agents = []  # the User-Agent of every request
        self.ignore_range = False
        self.no_length = False
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()

    def url(self, path):
        return f"http://127.0.0.1:{self.server.server_port}{path}"

    def _handler(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                owner.requests.append((self.path, self.headers.get("Range")))
                owner.agents.append(self.headers.get("User-Agent"))

                if owner.failures:
                    self.send_error(owner.failures.pop(0))
                    return

                if self.path not in owner.files:
                    self.send_error(404)
                    return

                data = owner.files[self.path]
                start = 0
                status = 200
                byte_range = self.headers.get("Range")

                if byte_range and not owner.ignore_range:
                    start = int(byte_range.removeprefix("bytes=").removesuffix("-"))

                    if start >= len(data):
                        self.send_error(416)
                        return

                    status = 206

                body = data[start:]
                self.send_response(status)

                if not owner.no_length:
                    self.send_header("Content-Length", str(len(body)))

                self.end_headers()
                self.wfile.write(body)

        return Handler


@pytest.fixture
def file_server():
    server = FileServer()
    yield server
    server.server.shutdown()
    server.server.server_close()


# ModDB's pages for a file, cut down to what the app reads. Their markup is copied from the real pages.
MODDB_FILE_PAGE = """<div class="row clear">
<h5>Filename</h5>
<span class="summary">
\t\t{name}\t\t</span>
</div>
<div class="row clear">
<h5>Size</h5>
<span class="summary">
\t\t{size_gb:.2f}gb ({size:,} bytes)\t\t</span>
</div>
<div class="row clear">
<h5>MD5 Hash</h5>
<span class="summary">
\t\t{md5}\t\t</span>
</div>
<a href="/downloads/start/290690" class="buttondownload">Download Now</a>
"""
MODDB_START_PAGE = """<p>Wait for the download to begin, if it doesn't click the link to
<a href="/downloads/mirror/290690/130/f93911bb939f81ae6ebd42fade8bc944">download {name}</a> or try another
<a href="/downloads/start/290690/all">mirror</a>.</p>
"""


class Moddb:
    """The Age of the Ring file on a local stand-in for ModDB. `publish` puts a zip there; the pages can be broken after."""

    def __init__(self, server, monkeypatch):
        from bfme_wizard.engine.programs.aotr import ModDB

        self.server = server
        self.page_url = server.url("/mods/aotr/downloads/age-of-the-ring")
        monkeypatch.setattr(ModDB, "PAGE_URL", self.page_url)

    def publish(self, data, name="AotR_Standalone_10.0.0_Installer.zip", md5=None):
        import hashlib

        md5 = md5 or hashlib.md5(data).hexdigest()
        files = self.server.files
        files["/mods/aotr/downloads/age-of-the-ring"] = MODDB_FILE_PAGE.format(
            name=name, size=len(data), size_gb=len(data) / 2**30, md5=md5
        ).encode()
        files["/downloads/start/290690"] = MODDB_START_PAGE.format(name=name).encode()
        files["/downloads/mirror/290690/130/f93911bb939f81ae6ebd42fade8bc944"] = data
        return name


@pytest.fixture
def moddb(file_server, monkeypatch):
    return Moddb(file_server, monkeypatch)
