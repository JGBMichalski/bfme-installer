"""Finding the Age of the Ring download on ModDB, so the app can fetch it itself.

ModDB has no API for this, so the app reads the same pages a browser does: the file's page for its name, size and MD5,
then the download page for the mirror link, which redirects to the file. When a page is not as expected (changed markup,
a bot check, no connection), the player downloads the file in a browser instead and chooses it.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urljoin

from .download import USER_AGENT

AOTR_PAGE_URL = (
    "https://www.moddb.com/mods/the-horse-lords-a-total-modification-for-bfme/downloads/age-of-the-ring-version-90"
)
TIMEOUT_SEC = 30


class ModdbUnavailable(Exception):
    """The app cannot download the file itself. The message says why, for the player."""


@dataclass(frozen=True)
class RemoteFile:
    name: str
    size: int  # bytes
    md5: str
    url: str  # the mirror link; it redirects to the file


def _get(url: str) -> str:
    """Fetch the page at the given URL and return its content as a string. Raises ModdbUnavailable if the page cannot be reached."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SEC) as response:
            return response.read().decode(errors="replace")
    except (urllib.error.URLError, OSError) as error:
        raise ModdbUnavailable(f"ModDB could not be reached ({error}).") from error


def _field(page: str, label: str) -> str:
    """The value of one row of the file's details, like "Filename" or "MD5 Hash"."""
    match = re.search(rf"<h5>{re.escape(label)}</h5>\s*<span[^>]*>\s*(.*?)\s*</span>", page, re.S)

    if match is None:
        raise ModdbUnavailable(f"The ModDB page has changed: its {label} is missing.")

    return match.group(1)


def find_aotr(page_url: str | None = None) -> RemoteFile:
    """The Age of the Ring download: its name, size, MD5 and mirror link, read from ModDB's pages."""
    page_url = page_url or AOTR_PAGE_URL
    page = _get(page_url)

    name = _field(page, "Filename")

    if not re.fullmatch(r"AotR_Standalone_.*_Installer\.zip", name):
        raise ModdbUnavailable(f"The ModDB page has changed: the file is now {name}.")

    size = re.search(r"\(([\d,]+) bytes\)", _field(page, "Size"))
    md5 = _field(page, "MD5 Hash")

    if size is None or not re.fullmatch(r"[0-9a-f]{32}", md5):
        raise ModdbUnavailable("The ModDB page has changed: its size or MD5 cannot be read.")

    start = re.search(r'href="([^"]*/downloads/start/\d+)"', page)

    if start is None:
        raise ModdbUnavailable("The ModDB page has changed: its download link is missing.")

    # The download page also asks for a human check when ModDB wants one; then it has no mirror link.
    start_url = urljoin(page_url, start.group(1))
    mirror = re.search(r'href="([^"]*/downloads/mirror/\d+/\d+/[0-9a-f]+)"', _get(start_url))

    if mirror is None:
        raise ModdbUnavailable("ModDB did not offer a download link. It may want a browser.")

    return RemoteFile(
        name=name,
        size=int(size.group(1).replace(",", "")),
        md5=md5,
        url=urljoin(start_url, mirror.group(1)),
    )
