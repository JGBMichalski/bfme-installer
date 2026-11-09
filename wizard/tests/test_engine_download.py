"""engine.download: what the setup script's download and verify_sha256 did."""

import hashlib
import threading

import pytest

from bfme_wizard.engine import download as download_module
from bfme_wizard.engine.download import Download
from bfme_wizard.engine.errors import JobCancelled, SetupError

DATA = bytes(range(256)) * 4096  # 1 MiB: several chunks


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    monkeypatch.setattr(Download, "RETRY_DELAY_SEC", 0)


def test_the_file_arrives_whole_with_progress_up_to_100(file_server, tmp_path):
    file_server.files["/f.bin"] = DATA
    seen = []
    dest = tmp_path / "sub" / "f.bin"

    Download(file_server.url("/f.bin"), dest, seen.append).run()

    assert dest.read_bytes() == DATA
    assert not (tmp_path / "sub" / "f.bin.part").exists()
    assert seen == sorted(set(seen))
    assert seen[-1] == 100


def test_without_a_size_there_is_no_progress(file_server, tmp_path):
    file_server.files["/f.bin"] = DATA
    file_server.no_length = True
    seen = []

    Download(file_server.url("/f.bin"), tmp_path / "f.bin", seen.append).run()

    assert (tmp_path / "f.bin").read_bytes() == DATA
    assert seen == []


def test_a_part_file_is_carried_on_from(file_server, tmp_path):
    file_server.files["/f.bin"] = DATA
    (tmp_path / "f.bin.part").write_bytes(DATA[:1000])

    Download(file_server.url("/f.bin"), tmp_path / "f.bin").run()

    assert (tmp_path / "f.bin").read_bytes() == DATA
    assert file_server.requests == [("/f.bin", "bytes=1000-")]


def test_a_server_that_ignores_the_range_still_gives_the_right_file(file_server, tmp_path):
    file_server.files["/f.bin"] = DATA
    file_server.ignore_range = True
    (tmp_path / "f.bin.part").write_bytes(b"stale")

    Download(file_server.url("/f.bin"), tmp_path / "f.bin").run()

    assert (tmp_path / "f.bin").read_bytes() == DATA


def test_a_whole_part_file_that_the_server_refuses_to_resume_is_fetched_again(file_server, tmp_path):
    file_server.files["/f.bin"] = DATA
    (tmp_path / "f.bin.part").write_bytes(DATA + b"extra")

    Download(file_server.url("/f.bin"), tmp_path / "f.bin").run()

    assert (tmp_path / "f.bin").read_bytes() == DATA


def test_a_server_error_is_retried(file_server, tmp_path):
    file_server.files["/f.bin"] = DATA
    file_server.failures = [500, 503]

    Download(file_server.url("/f.bin"), tmp_path / "f.bin").run()

    assert (tmp_path / "f.bin").read_bytes() == DATA
    assert len(file_server.requests) == 3


def test_it_gives_up_after_three_retries(file_server, tmp_path):
    file_server.files["/f.bin"] = DATA
    file_server.failures = [500] * 10

    with pytest.raises(SetupError, match="Could not download f.bin"):
        Download(file_server.url("/f.bin"), tmp_path / "f.bin").run()

    assert len(file_server.requests) == 4
    assert not (tmp_path / "f.bin").exists()


def test_a_missing_file_is_not_asked_for_again(file_server, tmp_path):
    with pytest.raises(SetupError, match="Could not download f.bin"):
        Download(file_server.url("/f.bin"), tmp_path / "f.bin").run()

    assert len(file_server.requests) == 1


def test_no_server_is_an_error(tmp_path):
    with pytest.raises(SetupError, match="Could not download f.bin"):
        Download("http://127.0.0.1:1/f.bin", tmp_path / "f.bin").run()


def test_cancel_stops_it_and_leaves_no_file(file_server, tmp_path):
    file_server.files["/f.bin"] = DATA
    cancel = threading.Event()
    cancel.set()

    with pytest.raises(JobCancelled):
        Download(file_server.url("/f.bin"), tmp_path / "f.bin", cancel=cancel).run()

    assert not (tmp_path / "f.bin").exists()


def test_a_matching_checksum_keeps_the_file(tmp_path):
    path = tmp_path / "f.bin"
    path.write_bytes(DATA)

    Download.verify_sha256(path, hashlib.sha256(DATA).hexdigest())

    assert path.exists()


def test_a_wrong_checksum_deletes_the_file(tmp_path):
    path = tmp_path / "f.bin"
    path.write_bytes(DATA)

    with pytest.raises(SetupError, match="Checksum mismatch for f.bin"):
        Download.verify_sha256(path, "0" * 64)

    assert not path.exists()


def test_every_request_names_the_app_not_python(file_server, tmp_path):
    # The AIO Launcher's server answers Python's own User-Agent with 403 Forbidden.
    file_server.files["/f.bin"] = DATA
    (tmp_path / "f.bin.part").write_bytes(DATA[:1000])

    Download(file_server.url("/f.bin"), tmp_path / "f.bin").run()

    assert file_server.agents == ["bfme-installer"]


class Clock:
    """A clock that moves one second each time it is read, so a measured speed is the bytes of one look."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 1.0
        return self.now


def test_the_speed_is_reported_about_once_a_second(file_server, tmp_path, monkeypatch):
    file_server.files["/f.bin"] = DATA
    monkeypatch.setattr(download_module.time, "monotonic", Clock())
    speeds = []

    Download(file_server.url("/f.bin"), tmp_path / "f.bin", on_speed=speeds.append).run()

    # One chunk arrives between two readings of the clock, one second apart.
    assert speeds
    assert set(speeds) <= {Download.CHUNK}


def test_the_speed_counts_only_what_arrives_now(file_server, tmp_path, monkeypatch):
    file_server.files["/f.bin"] = DATA
    (tmp_path / "f.bin.part").write_bytes(DATA[:500_000])
    monkeypatch.setattr(download_module.time, "monotonic", Clock())
    speeds = []

    Download(file_server.url("/f.bin"), tmp_path / "f.bin", on_speed=speeds.append).run()

    assert max(speeds) <= Download.CHUNK  # not the 500 000 bytes already there


def test_no_speed_is_measured_without_a_listener(file_server, tmp_path):
    file_server.files["/f.bin"] = DATA

    Download(file_server.url("/f.bin"), tmp_path / "f.bin").run()

    assert (tmp_path / "f.bin").read_bytes() == DATA
