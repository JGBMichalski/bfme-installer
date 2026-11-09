"""The byte pattern the Arena's in-game overlay finds the game's graphics device by, and giving it to DXVK's d3d9.dll.

The Arena puts an add-on in the game's folder (its dinput8.dll). Before the Arena creates or joins the in-game room, or
starts a replay, it waits for the add-on's overlay to draw over a frame of the game. The overlay finds the game's Direct3D 9
device by looking in d3d9.dll for the machine code that sets one up in Microsoft's d3d9.dll, `C7 06 <vtable> 89 86 ?? ?? ??
?? 89 86`, and hooks entries 16 and 17 of that vtable (Reset and Present). DXVK's d3d9.dll has no such code, and neither has
Wine's, so the overlay never starts and the Arena gives up with "A task was canceled".
"""

from __future__ import annotations

import re
import shutil
import struct
import sys
from array import array
from dataclasses import dataclass
from pathlib import Path

from .context import Context
from .events import Log, Warn
from .paths import Paths

# The overlay looks this far into d3d9.dll and takes the first match.
SCAN_SIZE = 0x128000
# mov dword ptr [esi], <vtable>; mov [esi + <offset>], eax; mov [esi + <offset>], eax
OVERLAY_PATTERN = re.compile(rb"\xc7\x06.{4}\x89\x86.{4}\x89\x86", re.DOTALL)
CONSEQUENCE = "The Arena may not be able to start games or replays."
OPENGL = (
    f"The Arena's in-game overlay does not work with OpenGL graphics. {CONSEQUENCE} Switch to Vulkan in Troubleshoot if "
    "your graphics card supports it."
)


def align_up(value: int, alignment: int) -> int:
    """Align `value` up to the nearest multiple of `alignment`.

    Args:
        value: The value to align.
        alignment: The alignment boundary.

    Returns:
        The aligned value.
    """
    return (value + alignment - 1) // alignment * alignment


@dataclass(frozen=True)
class Section:
    header_at: int  # where its entry in the section table is, in the file
    address: int  # its RVA
    virtual_size: int
    raw_at: int  # where its data is, in the file
    raw_size: int
    executable: bool


class Pe32:
    """Just enough of a 32-bit Windows DLL to read it as Windows maps it, and to add a few bytes and a base relocation to
    it. Raises ValueError for anything else."""

    MACHINE_I386 = 0x14C
    MAGIC_PE32 = 0x10B
    BASE_RELOCATIONS = 5  # the base relocation table's place among the data directories
    HIGHLOW = 3  # a base relocation of a 32-bit address
    EXECUTABLE = 0x20000000

    def __init__(self, data: bytes) -> None:
        self.data = bytearray(data)

        try:
            self._read_headers()
        except struct.error as error:
            raise ValueError("it is cut short") from error

    def _read_headers(self) -> None:
        data = self.data

        if data[:2] != b"MZ":
            raise ValueError("it is not a Windows DLL")

        pe = struct.unpack_from("<I", data, 0x3C)[0]

        if data[pe : pe + 4] != b"PE\0\0":
            raise ValueError("it is not a Windows DLL")

        machine, count = struct.unpack_from("<HH", data, pe + 4)
        optional_size = struct.unpack_from("<H", data, pe + 20)[0]
        optional = pe + 24

        if machine != self.MACHINE_I386 or struct.unpack_from("<H", data, optional)[0] != self.MAGIC_PE32:
            raise ValueError("it is not a 32-bit DLL")

        self.image_base, self.section_alignment = struct.unpack_from("<II", data, optional + 28)
        self.size_of_image, self.size_of_headers = struct.unpack_from("<II", data, optional + 56)
        self.checksum_at = optional + 64

        if struct.unpack_from("<I", data, optional + 92)[0] <= self.BASE_RELOCATIONS:
            raise ValueError("it has no base relocations")

        self.relocations_at = optional + 96 + 8 * self.BASE_RELOCATIONS
        table = optional + optional_size
        self.sections = []

        for i in range(count):
            at = table + 40 * i
            virtual_size, address, raw_size, raw_at = struct.unpack_from("<IIII", data, at + 8)
            characteristics = struct.unpack_from("<I", data, at + 36)[0]
            executable = bool(characteristics & self.EXECUTABLE)
            self.sections.append(Section(at, address, virtual_size, raw_at, raw_size, executable))

        self.headers_end = table + 40 * count

    def image(self, size: int | None = None) -> bytearray:
        """The first `size` bytes of the DLL as Windows maps it at its preferred base: the headers, then each section at its
        address. All of it by default."""
        size = self.size_of_image if size is None else size
        image = bytearray(size)
        headers = self.data[: min(self.size_of_headers, size)]
        image[: len(headers)] = headers

        for section in self.sections:
            length = min(section.raw_size, section.virtual_size, size - section.address)

            if length > 0:
                data = self.data[section.raw_at : section.raw_at + length]
                image[section.address : section.address + len(data)] = data

        return image

    def in_code(self, address: int) -> bool:
        """Whether an address, at the preferred base, is in a section of code."""
        rva = address - self.image_base

        for section in self.sections:
            if section.executable and section.address <= rva < section.address + section.virtual_size:
                return True

        return False

    def _relocations(self) -> tuple[int, int, Section]:
        """The base relocation table: (RVA, size, the section it is in)."""
        rva, size = struct.unpack_from("<II", self.data, self.relocations_at)

        for section in self.sections:
            if section.address <= rva < section.address + max(section.virtual_size, section.raw_size):
                return rva, size, section

        raise ValueError("its base relocations are not in a section")

    def relocates(self, rva: int) -> bool:
        """Whether the loader adjusts the 32-bit address at `rva` when the DLL is not at its preferred base."""
        table_rva, size, section = self._relocations()
        table = self.data[section.raw_at + table_rva - section.address :][:size]
        at = 0

        while at + 8 <= len(table):
            page, block = struct.unpack_from("<II", table, at)

            if block < 8:
                break

            if page == rva & ~0xFFF:
                for entry_at in range(at + 8, min(at + block, len(table)) - 1, 2):
                    entry = struct.unpack_from("<H", table, entry_at)[0]

                    if entry >> 12 == self.HIGHLOW and page + (entry & 0xFFF) == rva:
                        return True

            at += block

        return False

    def free_header_room(self, size: int) -> int:
        """Where `size` bytes are free after the section table, in the part of the headers Windows maps."""
        at = align_up(self.headers_end, 16)
        first_data = self.size_of_headers

        for section in self.sections:
            if section.raw_size:
                first_data = min(first_data, section.raw_at)

        if at + size > first_data or any(self.data[at : at + size]):
            raise ValueError("it has no free room in its headers")

        return at

    def add_relocation(self, rva: int) -> None:
        """Have the loader adjust the 32-bit address at `rva` too: one more block at the end of the base relocation table,
        in the room its section has to spare."""
        table_rva, size, section = self._relocations()
        block = struct.pack("<IIHH", rva & ~0xFFF, 12, (self.HIGHLOW << 12) | (rva & 0xFFF), 0)
        used = table_rva + size - section.address
        room = min(section.raw_size, align_up(section.virtual_size, self.section_alignment))
        at = section.raw_at + used

        if used + len(block) > room or at + len(block) > len(self.data) or any(self.data[at : at + len(block)]):
            raise ValueError("it has no room for another base relocation")

        self.data[at : at + len(block)] = block
        struct.pack_into("<I", self.data, self.relocations_at + 4, size + len(block))

        if section.virtual_size < used + len(block):
            struct.pack_into("<I", self.data, section.header_at + 8, used + len(block))

    def update_checksum(self) -> None:
        """The checksum in the headers, worked out again for the changed file as Windows does."""
        struct.pack_into("<I", self.data, self.checksum_at, 0)
        words = array("H", bytes(self.data) + b"\0" * (len(self.data) % 2))

        if sys.byteorder == "big":
            words.byteswap()

        total = sum(words)

        while total > 0xFFFF:
            total = (total & 0xFFFF) + (total >> 16)

        struct.pack_into("<I", self.data, self.checksum_at, total + len(self.data))


class OverlayPattern:
    """The pattern the Arena's overlay looks for, in the 32-bit d3d9.dll of the game environment.

    `add` writes those 14 bytes into unused room at the end of the headers of DXVK's d3d9.dll, with the address of DXVK's
    own device vtable in them, and one base relocation so the address is right wherever the DLL is loaded. No code changes:
    the overlay then hooks DXVK's Present and Reset as it does Microsoft's. Proton copies DXVK into the game environment
    again when its own settings change, so this is checked each time the Arena opens.
    """

    # DXVK's device class, as its run-time type information names it.
    DEVICE_TYPE = b"N4dxvk12D3D9DeviceExE\0"
    DEVICE_METHODS = 134  # IDirect3DDevice9Ex: IUnknown's 3, IDirect3DDevice9's 116 and its own 15

    def __init__(self, paths: Paths) -> None:
        self.paths = paths

    @property
    def dll(self) -> Path:
        """The d3d9.dll the games load. They are 32-bit, so it is the one in syswow64."""
        return self.paths.drive_c / "windows/syswow64/d3d9.dll"

    def add(self, ctx: Context) -> None:
        """Give DXVK's d3d9.dll the pattern if it does not have it. Says so when it cannot; the Arena opens either way."""
        if ctx.config.graphics == "opengl":
            ctx.emit(Warn(OPENGL))
            return

        dll = self.dll
        tmp = dll.with_name(dll.name + ".bfme-new")

        try:
            changed = self.with_pattern(dll.read_bytes())

            if changed is None:
                return

            tmp.write_bytes(changed)
            shutil.copymode(dll, tmp)
            tmp.replace(dll)
        except (OSError, ValueError, struct.error) as error:
            tmp.unlink(missing_ok=True)
            ctx.emit(Warn(f"Could not prepare {dll} for the Arena's in-game overlay: {error}. {CONSEQUENCE}"))
            return

        ctx.emit(Log(f"Added what the Arena's in-game overlay looks for to {dll}."))

    @classmethod
    def with_pattern(cls, data: bytes) -> bytes | None:
        """DXVK's d3d9.dll with the pattern added, or None when the overlay already finds DXVK's device in it. Raises
        ValueError when it is not DXVK's, or has no room."""
        dll = Pe32(data)
        vtable = cls.device_vtable(dll)

        if cls.overlay_finds(dll) == vtable:
            return None

        at = dll.free_header_room(14)
        dll.data[at : at + 14] = b"\xc7\x06" + struct.pack("<I", dll.image_base + vtable) + b"\x89\x86\0\0\0\0\x89\x86"
        dll.add_relocation(at + 2)
        dll.update_checksum()

        if cls.overlay_finds(Pe32(dll.data)) != vtable:
            raise ValueError("the overlay would still not find the device")

        return bytes(dll.data)

    @classmethod
    def device_vtable(cls, dll: Pe32) -> int:
        """The RVA a DXVK device's first word points to: its class's vtable. Found from the name of the class, to the
        class's type information, to the one vtable for an object at offset 0 that points to it."""
        image = dll.image()
        name = image.find(cls.DEVICE_TYPE)

        if name < 0:
            raise ValueError("it is not DXVK's")

        found = []

        # The type information is {its own vtable, the name, ...}; a vtable is {offset to the object, the type information,
        # the methods...}.
        for name_at in cls._words(image, dll.image_base + name):
            for type_at in cls._words(image, dll.image_base + name_at - 4):
                if type_at >= 4 and struct.unpack_from("<i", image, type_at - 4)[0] == 0:
                    found.append(type_at + 4)

        if len(found) != 1 or found[0] + 4 * cls.DEVICE_METHODS > len(image):
            raise ValueError("its device vtable was not found")

        vtable = found[0]

        for method in struct.unpack_from(f"<{cls.DEVICE_METHODS}I", image, vtable):
            if not dll.in_code(method):
                raise ValueError("its device vtable was not found")

        return vtable

    @staticmethod
    def overlay_finds(dll: Pe32) -> int | None:
        """The RVA of the vtable the overlay takes from this DLL wherever it is loaded, as it searches it. None when it
        finds no pattern, or one whose address the loader would not adjust."""
        image = dll.image(SCAN_SIZE + 13)
        match = OVERLAY_PATTERN.search(image)

        if match is None or not dll.relocates(match.start() + 2):
            return None

        return struct.unpack_from("<I", image, match.start() + 2)[0] - dll.image_base

    @staticmethod
    def _words(image: bytes, value: int) -> list[int]:
        """Where a 32-bit value is stored, at 4-byte boundaries."""
        needle = struct.pack("<I", value)
        found = []
        at = image.find(needle)

        while at >= 0:
            if at % 4 == 0:
                found.append(at)

            at = image.find(needle, at + 1)

        return found
