"""A small 32-bit Windows DLL laid out like DXVK's d3d9.dll where the Arena overlay's pattern goes: code, the run-time type
information and vtable of DXVK's device class, and base relocations with room to spare. Made with the standard library,
so the tests need no DXVK.

Also what the DLL looks like to the game: `load` maps it as Windows does, and `overlay_hooks` searches it as the overlay
does. Both are written apart from the code they test.
"""

import struct

IMAGE_BASE = 0x62440000
TEXT, RDATA, RELOC = 0x1000, 0x2000, 0x3000  # the sections' addresses
TEXT_AT, RDATA_AT, RELOC_AT = 0x400, 0x1400, 0x2400  # and where their data is in the file
HEADERS = 0x400
TYPE_INFO = RDATA + 0x20
VTABLE = RDATA + 0x48  # where a device's first word points: after the offset to the object and the type information
METHODS = 134
RESET, PRESENT = 16, 17
SCAN_SIZE = 0x128000


def method(k):
    """The address of the device's method k, at the preferred base."""
    return TEXT + 0x10 * k


def fake_dxvk(
    *,
    name=b"N4dxvk12D3D9DeviceExE\0",
    machine=0x14C,
    header_free=True,
    relocation_room=True,
    method_outside_code=False,
):
    """DXVK's d3d9.dll as far as the overlay pattern goes. The keywords break one thing each."""
    rdata = bytearray(0x1000)
    pointers = []  # the RVAs in .rdata of the addresses the loader adjusts

    def pointer(at, rva):
        struct.pack_into("<I", rdata, at - RDATA, IMAGE_BASE + rva)
        pointers.append(at)

    rdata[: len(name)] = name

    # The type information: {its own vtable, the name, the base class's}.
    pointer(TYPE_INFO, RDATA + 0x800)
    pointer(TYPE_INFO + 4, RDATA)
    pointer(TYPE_INFO + 8, RDATA + 0x810)

    # The vtable: {offset to the object, the type information, the methods}.
    struct.pack_into("<i", rdata, VTABLE - 8 - RDATA, 0)
    pointer(VTABLE - 4, TYPE_INFO)

    for k in range(METHODS):
        pointer(VTABLE + 4 * k, method(k))

    if method_outside_code:
        pointer(VTABLE + 4 * 100, RDATA + 0x900)

    # A second vtable for the same class, for an object at another offset. It is not the device's.
    struct.pack_into("<i", rdata, 0x600 - 8, -8)
    pointer(RDATA + 0x600 - 4, TYPE_INFO)
    pointer(RDATA + 0x600, method(0))

    entries = sorted(set(pointers))
    table = struct.pack("<II", RDATA, 8 + 2 * len(entries) + 2 * (len(entries) % 2))

    for at in entries:
        table += struct.pack("<H", (3 << 12) | (at - RDATA))

    table += b"\0\0" * (len(entries) % 2)
    reloc_raw = 0x200 if relocation_room else len(table)

    sections = [
        (b".text", 0x1000, TEXT, 0x1000, TEXT_AT, 0x60000020),
        (b".rdata", 0x1000, RDATA, 0x1000, RDATA_AT, 0x40000040),
        (b".reloc", len(table), RELOC, reloc_raw, RELOC_AT, 0x42000040),
    ]
    data = bytearray(RELOC_AT + reloc_raw)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", data, 0x84, machine, len(sections), 0, 0, 0, 224, 0x2102)
    optional = 0x98
    struct.pack_into("<H", data, optional, 0x10B)
    struct.pack_into("<IIII", data, optional + 28, IMAGE_BASE, 0x1000, 0x200, 0)
    struct.pack_into("<II", data, optional + 56, 0x4000, HEADERS)
    struct.pack_into("<I", data, optional + 92, 16)
    struct.pack_into("<II", data, optional + 96 + 8 * 5, RELOC, len(table))

    for i, (section_name, virtual_size, address, raw_size, raw_at, flags) in enumerate(sections):
        at = optional + 224 + 40 * i
        data[at : at + 8] = section_name.ljust(8, b"\0")
        struct.pack_into("<IIII", data, at + 8, virtual_size, address, raw_size, raw_at)
        struct.pack_into("<I", data, at + 36, flags)

    if not header_free:
        table_end = optional + 224 + 40 * len(sections)
        data[table_end:HEADERS] = b"\x01" * (HEADERS - table_end)

    data[TEXT_AT : TEXT_AT + 0x1000] = b"\xcc" * 0x1000
    data[RDATA_AT : RDATA_AT + 0x1000] = rdata
    data[RELOC_AT : RELOC_AT + len(table)] = table
    return bytes(data)


def _headers(data):
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    count = struct.unpack_from("<H", data, pe + 6)[0]
    optional = pe + 24
    base, size, headers = (struct.unpack_from("<I", data, optional + at)[0] for at in (28, 56, 60))
    relocations = struct.unpack_from("<II", data, optional + 96 + 8 * 5)
    sections = [struct.unpack_from("<IIII", data, optional + 224 + 40 * i + 8) for i in range(count)]
    return base, size, headers, relocations, sections


def load(data, base):
    """The DLL as Windows maps it at `base`: the headers, the sections at their addresses, the base relocations applied."""
    preferred, size, headers, (table_rva, table_size), sections = _headers(data)
    image = bytearray(size)
    image[:headers] = data[:headers]

    for virtual_size, address, raw_size, raw_at in sections:
        length = min(virtual_size, raw_size)
        image[address : address + length] = data[raw_at : raw_at + length]

    at = table_rva

    while at < table_rva + table_size:
        page, block = struct.unpack_from("<II", image, at)

        for (entry,) in struct.iter_unpack("<H", image[at + 8 : at + block]):
            if entry >> 12 == 3:
                where = page + (entry & 0xFFF)
                value = struct.unpack_from("<I", image, where)[0]
                struct.pack_into("<I", image, where, (value - preferred + base) & 0xFFFFFFFF)

        at += block

    return image


def overlay_hooks(image, base):
    """What the overlay hooks in a d3d9.dll loaded at `base`: (Reset, Present) from the vtable after the first match of its
    pattern in the first 0x128000 bytes, as it searches. None when it finds no match."""
    for i in range(min(len(image), SCAN_SIZE) - 13):
        if (image[i], image[i + 1], image[i + 6], image[i + 7], image[i + 12], image[i + 13]) == (
            0xC7,
            0x06,
            0x89,
            0x86,
            0x89,
            0x86,
        ):
            vtable = struct.unpack_from("<I", image, i + 2)[0] - base
            return struct.unpack_from("<II", image, vtable + 4 * RESET)

    return None


def checksum(data):
    """The checksum Windows works out for a PE file, summed 32 bits at a time with the checksum field left out."""
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    field = pe + 24 + 64
    padded = data + b"\0" * (-len(data) % 4)
    total = 0

    for i, (dword,) in enumerate(struct.iter_unpack("<I", padded)):
        if i * 4 != field:
            total += dword
            total = (total & 0xFFFFFFFF) + (total >> 32)

    total = (total & 0xFFFF) + (total >> 16)
    total = (total + (total >> 16)) & 0xFFFF
    return total + len(data)
