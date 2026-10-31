"""Downloads with progress, resume and retries, and checksum checks."""
from __future__ import annotations

import hashlib
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from .errors import JobCancelled, SetupError

RETRIES = 3
RETRY_DELAY_SEC = 2
TIMEOUT_SEC = 30
CHUNK = 64 * 1024
USER_AGENT = "bfme-installer"

Progress = Callable[[int], None]


def download(url: str, dest: Path, on_progress: Progress | None = None, cancel: threading.Event | None = None) -> None:
    """Fetch url to dest. The data goes to dest.part first, so an interrupted download is never taken for the file."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")

    for attempt in range(RETRIES + 1):
        try:
            _fetch(url, part, on_progress, cancel)
            part.replace(dest)
            return

        except urllib.error.HTTPError as error:
            # The part file is already whole, or the file changed on the server: start over.
            if error.code == 416:
                part.unlink(missing_ok=True)
            # A missing file does not come back by asking again.
            elif 400 <= error.code < 500:
                raise SetupError(f"Could not download {dest.name}: {error}") from error

            failure = error

        except (urllib.error.URLError, OSError) as error:
            failure = error

        if attempt == RETRIES:
            raise SetupError(f"Could not download {dest.name}: {failure}") from failure

        time.sleep(RETRY_DELAY_SEC)


def _fetch(url: str, part: Path, on_progress: Progress | None, cancel: threading.Event | None) -> None:
    """One try. Carries on from what an earlier try left in the part file."""
    start = part.stat().st_size if part.exists() else 0
    headers = {"User-Agent": USER_AGENT}

    if start:
        headers["Range"] = f"bytes={start}-"

    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=TIMEOUT_SEC) as response:
        # A server that ignores the range, sends the whole file again.
        if start and response.status != 206:
            start = 0

        length = response.headers.get("Content-Length")
        total = start + int(length) if length else None
        mode = "ab" if start else "wb"

        with open(part, mode) as out:
            done = start
            last = -1

            while True:
                if cancel is not None and cancel.is_set():
                    raise JobCancelled()

                chunk = response.read(CHUNK)

                if not chunk:
                    break

                out.write(chunk)
                done += len(chunk)

                # Without a size from the server there is no progress, so the wizard shows "working".
                if total and on_progress is not None:
                    percent = min(100, done * 100 // total)

                    if percent != last:
                        on_progress(percent)
                        last = percent


def verify_sha256(path: Path, expected: str) -> None:
    """Delete the file and fail when its checksum is not the expected one."""
    digest = hashlib.sha256()

    with open(path, "rb") as f:
        while True:
            block = f.read(1024 * 1024)

            if not block:
                break

            digest.update(block)

    got = digest.hexdigest()

    if got != expected:
        path.unlink()
        raise SetupError(f"Checksum mismatch for {path.name} (expected {expected}, got {got}).")
