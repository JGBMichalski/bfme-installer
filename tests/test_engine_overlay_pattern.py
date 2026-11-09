"""engine.overlay_pattern: giving the d3d9.dll of DXVK or Wine what the Arena's in-game overlay looks for."""

import pytest

from bfme_wizard.engine.games import GAMES
from bfme_wizard.engine.overlay_pattern import OverlayPattern, Pe32
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
    fake_wine_d3d9,
    load,
    method,
    overlay_hooks,
)

# Where the DLL may be loaded: its preferred base, and others the loader picks when that one is taken.
BASES = (IMAGE_BASE, 0x20000000, 0x7B2C0000)
WHOSE = {"DXVK": fake_dxvk, "Wine": fake_wine_d3d9}


@pytest.mark.parametrize("whose", WHOSE)
@pytest.mark.parametrize("base", BASES)
def test_the_overlay_finds_nothing_in_the_dll_as_it_comes(whose, base):
    assert overlay_hooks(load(WHOSE[whose](), base), base) is None


@pytest.mark.parametrize("whose", WHOSE)
@pytest.mark.parametrize("base", BASES)
def test_with_the_pattern_the_overlay_hooks_the_dlls_own_reset_and_present(whose, base):
    dll = OverlayPattern.with_pattern(WHOSE[whose]())

    assert overlay_hooks(load(dll, base), base) == (base + method(RESET), base + method(PRESENT))


@pytest.mark.parametrize("whose", WHOSE)
def test_only_the_headers_and_the_base_relocations_change(whose):
    before = WHOSE[whose]()
    after = OverlayPattern.with_pattern(before)
    changed = []

    for at, (old, new) in enumerate(zip(before, after, strict=True)):
        if old != new:
            changed.append(at)

    assert changed
    assert all(
        at < HEADERS or RELOC_AT <= at < RELOC_AT + 0x200 for at in changed
    )  # the code and the data are as they were
    assert after[RDATA_AT:RELOC_AT] == before[RDATA_AT:RELOC_AT]
    assert int.from_bytes(after[0x98 + 64 : 0x98 + 68], "little") == checksum(after)


def test_wines_copy_loses_wines_builtin_mark_and_dxvks_header_keeps_its_bytes():
    assert Pe32(fake_wine_d3d9()).wine_builtin
    assert not Pe32(OverlayPattern.with_pattern(fake_wine_d3d9())).wine_builtin
    assert OverlayPattern.with_pattern(fake_dxvk())[0x40:0x50] == fake_dxvk()[0x40:0x50]


@pytest.mark.parametrize("whose", WHOSE)
def test_a_dll_that_has_it_is_left_as_it_is(whose):
    assert OverlayPattern.with_pattern(OverlayPattern.with_pattern(WHOSE[whose]())) is None


def damaged_relocations(block_size):
    data = bytearray(fake_dxvk())
    data[RELOC_AT + 4 : RELOC_AT + 8] = block_size.to_bytes(4, "little")
    return bytes(data)


@pytest.mark.parametrize(
    "dll, reason",
    [
        (fake_dxvk(name=b"N4dxvk10D3D9VolumeE\0"), "it is neither DXVK's nor Wine's"),
        (fake_wine_d3d9(symbol=False), "it is neither DXVK's nor Wine's"),
        (fake_wine_d3d9()[:-40], "it is neither DXVK's nor Wine's"),
        (fake_dxvk(method_outside_code=True), "its device vtable was not found"),
        (fake_wine_d3d9(method_outside_code=True), "its device vtable was not found"),
        (fake_dxvk(machine=0x8664), "it is not a 32-bit DLL"),
        (b"#!/bin/sh\n", "it is not a Windows DLL"),
        (fake_dxvk()[:0x40], "it is not a Windows DLL"),
        (fake_dxvk()[:0x100], "it is cut short"),
        (fake_dxvk()[:0x1500], "its device vtable was not found"),
        (fake_dxvk()[:0x2410], "it has no room for another base relocation"),
        (fake_dxvk(header_free=False), "it has no free room in its headers"),
        (fake_dxvk(relocation_room=False), "it has no room for another base relocation"),
        (damaged_relocations(0x13), "the overlay would still not find the device"),
        (damaged_relocations(0xFFFFFFF0), "the overlay would still not find the device"),
    ],
    ids=lambda value: value if isinstance(value, str) else "dll",
)
def test_what_cannot_be_given_the_pattern_says_why(dll, reason):
    with pytest.raises(ValueError, match=reason):
        OverlayPattern.with_pattern(dll)


# For a bug report


@pytest.fixture
def paths(tmp_path):
    return Paths(tmp_path / "data")


def put_dll(paths, data):
    dll = OverlayPattern(paths).dll
    dll.parent.mkdir(parents=True, exist_ok=True)
    dll.write_bytes(data)
    return dll


@pytest.mark.parametrize(
    "data, expected",
    [
        (OverlayPattern.with_pattern(fake_dxvk()), "ready (DXVK's d3d9.dll)"),
        (OverlayPattern.with_pattern(fake_wine_d3d9()), "ready (Wine's d3d9.dll)"),
        (fake_dxvk(), "not added yet (DXVK's d3d9.dll)"),
        (fake_wine_d3d9(), "not added yet (Wine's d3d9.dll)"),
        (fake_dxvk(name=b"N4dxvk10D3D9VolumeE\0"), "cannot be added to d3d9.dll: it is neither DXVK's nor Wine's"),
        (None, "no d3d9.dll in the game environment"),
    ],
    ids=lambda value: value if isinstance(value, str) else "dll",
)
def test_the_state_says_whether_the_overlay_will_find_the_device(paths, data, expected):
    if data is not None:
        put_dll(paths, data)

    assert OverlayPattern(paths).state() == expected


def test_the_state_names_a_game_that_loads_its_own_d3d9(paths):
    put_dll(paths, OverlayPattern.with_pattern(fake_dxvk()))
    rotwk = next(game for game in GAMES if game.key == "rotwk")
    rotwk.game_dir(paths).mkdir(parents=True)
    (rotwk.game_dir(paths) / "d3d9.dll").write_bytes(b"MZ")

    assert OverlayPattern(paths).state() == "ready (DXVK's d3d9.dll); Rise of the Witch-king has its own d3d9.dll"
