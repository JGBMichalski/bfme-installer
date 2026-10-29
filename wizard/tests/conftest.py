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
