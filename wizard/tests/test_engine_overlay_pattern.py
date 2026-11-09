"""engine.overlay_pattern: giving DXVK's d3d9.dll what the Arena's in-game overlay looks for."""

import stat

import pytest

from bfme_wizard.engine.config import Config
from bfme_wizard.engine.events import Log, Warn
from bfme_wizard.engine.overlay_pattern import CONSEQUENCE, OPENGL, OverlayPattern
from bfme_wizard.engine.paths import Paths
from tests.fake_dll import (
    HEADERS,
    IMAGE_BASE,
    PRESENT,
    RDATA_AT,
    RELOC_AT,
    RESET,
    checksum,
    fake_dxvk,
    load,
    method,
    overlay_hooks,
)
from tests.helpers import context

# Where the DLL may be loaded: its preferred base, and others the loader picks when that one is taken.
BASES = (IMAGE_BASE, 0x20000000, 0x7B2C0000)


@pytest.mark.parametrize("base", BASES)
def test_the_overlay_finds_nothing_in_dxvk_as_it_comes(base):
    assert overlay_hooks(load(fake_dxvk(), base), base) is None


@pytest.mark.parametrize("base", BASES)
def test_with_the_pattern_the_overlay_hooks_dxvks_own_reset_and_present(base):
    dll = OverlayPattern.with_pattern(fake_dxvk())

    assert overlay_hooks(load(dll, base), base) == (base + method(RESET), base + method(PRESENT))


def test_only_the_headers_and_the_base_relocations_change():
    before = fake_dxvk()
    after = OverlayPattern.with_pattern(before)
    changed = []

    for at, (old, new) in enumerate(zip(before, after, strict=True)):
        if old != new:
            changed.append(at)

    assert changed
    assert all(at < HEADERS or at >= RELOC_AT for at in changed)  # the code and the data are as they were
    assert after[RDATA_AT:RELOC_AT] == before[RDATA_AT:RELOC_AT]
    assert int.from_bytes(after[0x98 + 64 : 0x98 + 68], "little") == checksum(after)


def test_a_dll_that_has_it_is_left_as_it_is():
    assert OverlayPattern.with_pattern(OverlayPattern.with_pattern(fake_dxvk())) is None


@pytest.mark.parametrize(
    "dll, reason",
    [
        (fake_dxvk(name=b"N4dxvk10D3D9VolumeE\0"), "it is not DXVK's"),
        (fake_dxvk(method_outside_code=True), "its device vtable was not found"),
        (fake_dxvk(machine=0x8664), "it is not a 32-bit DLL"),
        (b"#!/bin/sh\n", "it is not a Windows DLL"),
        (fake_dxvk()[:0x100], "it is cut short"),
        (fake_dxvk(header_free=False), "it has no free room in its headers"),
        (fake_dxvk(relocation_room=False), "it has no room for another base relocation"),
    ],
)
def test_what_cannot_be_given_the_pattern_says_why(dll, reason):
    with pytest.raises(ValueError, match=reason):
        OverlayPattern.with_pattern(dll)


# In the game environment


@pytest.fixture
def paths(tmp_path):
    return Paths(tmp_path / "data")


def put_dll(paths, data):
    dll = OverlayPattern(paths).dll
    dll.parent.mkdir(parents=True, exist_ok=True)
    dll.write_bytes(data)
    dll.chmod(0o775)
    return dll


def test_dxvks_d3d9_gets_the_pattern_once(paths):
    dll = put_dll(paths, fake_dxvk())
    events = []

    OverlayPattern(paths).add(context(paths, events.append))

    assert overlay_hooks(load(dll.read_bytes(), IMAGE_BASE), IMAGE_BASE) is not None
    assert stat.S_IMODE(dll.stat().st_mode) == 0o775
    assert events == [Log(f"Added what the Arena's in-game overlay looks for to {dll}.")]
    assert sorted(p.name for p in dll.parent.iterdir()) == ["d3d9.dll"]

    patched = dll.read_bytes()
    events.clear()
    OverlayPattern(paths).add(context(paths, events.append))

    assert events == []
    assert dll.read_bytes() == patched


def test_with_opengl_the_dll_is_left_alone_and_the_player_is_told(paths):
    dll = put_dll(paths, fake_dxvk())
    events = []

    OverlayPattern(paths).add(context(paths, events.append, config=Config(graphics="opengl")))

    assert events == [Warn(OPENGL)]
    assert dll.read_bytes() == fake_dxvk()


@pytest.mark.parametrize(
    "data, reason",
    [
        (fake_dxvk(name=b"N4dxvk10D3D9VolumeE\0"), "it is not DXVK's"),
        (None, "No such file"),
    ],
)
def test_a_dll_that_cannot_be_prepared_is_a_warning_and_is_left_as_it_is(paths, data, reason):
    dll = OverlayPattern(paths).dll

    if data is not None:
        put_dll(paths, data)

    events = []

    OverlayPattern(paths).add(context(paths, events.append))

    assert len(events) == 1 and isinstance(events[0], Warn)
    assert events[0].message.startswith(f"Could not prepare {dll} for the Arena's in-game overlay: ")
    assert reason in events[0].message
    assert events[0].message.endswith(CONSEQUENCE)

    if data is None:
        assert not dll.exists()
    else:
        assert dll.read_bytes() == data
        assert sorted(p.name for p in dll.parent.iterdir()) == ["d3d9.dll"]


def damaged_relocations(block_size):
    data = bytearray(fake_dxvk())
    data[RELOC_AT + 4 : RELOC_AT + 8] = block_size.to_bytes(4, "little")
    return bytes(data)


@pytest.mark.parametrize(
    "data",
    [
        *(fake_dxvk()[:length] for length in (0x40, 0x100, 0x1F0, 0x500, 0x1500, 0x1600, 0x2410)),
        damaged_relocations(0x13),
        damaged_relocations(0xFFFFFFF0),
    ],
)
def test_a_damaged_dll_is_a_warning_and_never_stops_the_arena(paths, data):
    dll = put_dll(paths, data)
    events = []

    OverlayPattern(paths).add(context(paths, events.append))

    assert [type(event) for event in events] == [Warn]
    assert dll.read_bytes() == data
