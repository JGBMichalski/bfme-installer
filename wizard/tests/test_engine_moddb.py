"""engine.moddb: reading the Age of the Ring download from ModDB's pages."""

import pytest

from bfme_wizard.engine import moddb
from bfme_wizard.engine.moddb import ModdbUnavailable, find_aotr


def test_the_file_is_found_with_its_size_md5_and_mirror(moddb):
    moddb.publish(b"x" * 5000)

    found = find_aotr()

    assert found.name == "AotR_Standalone_10.0.0_Installer.zip"
    assert found.size == 5000
    assert found.md5 == "a6bb7bde3251ca2d810d32dadd9e8ae7"
    assert found.url == moddb.server.url("/downloads/mirror/290690/130/f93911bb939f81ae6ebd42fade8bc944")


def test_every_page_is_asked_for_as_the_app(moddb):
    moddb.publish(b"x")

    find_aotr()

    assert moddb.server.agents == ["bfme-installer", "bfme-installer"]


def test_the_real_pages_markup_is_read(moddb):
    # Copied from the live page on Oct 30 2026: the numbers and the hash as ModDB writes them.
    page = (
        '<h5>Filename</h5>\n\t\t\t\t\t\t<span class="summary">\n\t\t\t\t\t\t\tAotR_Standalone_10.0.0_Installer.zip'
        '\t\t\t\t\t\t</span>\n<h5>Size</h5>\n\t\t\t\t\t\t<span class="summary">\n\t\t\t\t\t\t\t17.57gb '
        '(18,861,338,263 bytes)\t\t\t\t\t\t</span>\n<h5>MD5 Hash</h5>\n\t\t\t\t\t\t<span class="summary">\n'
        '\t\t\t\t\t\t\tc50672558753866eea39eca3ef3bd0da\t\t\t\t\t\t</span>\n<a href="/downloads/start/290690">'
    )
    moddb.publish(b"x")
    moddb.server.files["/mods/aotr/downloads/age-of-the-ring"] = page.encode()

    found = find_aotr()

    assert (found.name, found.size, found.md5) == (
        "AotR_Standalone_10.0.0_Installer.zip",
        18861338263,
        "c50672558753866eea39eca3ef3bd0da",
    )


@pytest.mark.parametrize(
    "change, reason",
    [
        (lambda page: page.replace("<h5>Filename</h5>", "<h5>File</h5>"), "its Filename is missing"),
        (
            lambda page: page.replace("AotR_Standalone_10.0.0_Installer.zip", "AotR_Patch_10.0.1.zip"),
            "the file is now AotR_Patch_10.0.1.zip",
        ),
        (lambda page: page.replace(" bytes)", ")"), "its size or MD5 cannot be read"),
        (lambda page: page.replace("/downloads/start/290690", "/elsewhere"), "its download link is missing"),
    ],
)
def test_a_changed_file_page_says_what_changed(moddb, change, reason):
    moddb.publish(b"x")
    key = "/mods/aotr/downloads/age-of-the-ring"
    moddb.server.files[key] = change(moddb.server.files[key].decode()).encode()

    with pytest.raises(ModdbUnavailable, match=reason):
        find_aotr()


def test_a_human_check_instead_of_the_download_page_means_a_browser(moddb):
    moddb.publish(b"x")
    moddb.server.files["/downloads/start/290690"] = b"<html>Please verify you are human</html>"

    with pytest.raises(ModdbUnavailable, match="It may want a browser"):
        find_aotr()


def test_no_connection_means_a_browser(monkeypatch):
    monkeypatch.setattr(moddb, "AOTR_PAGE_URL", "http://127.0.0.1:1/page")

    with pytest.raises(ModdbUnavailable, match="ModDB could not be reached"):
        find_aotr()
