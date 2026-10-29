"""Which graphics backend suits this computer, from the Vulkan devices the driver reports. No GTK.

Proton's DXVK needs Vulkan 1.3. Without a real graphics card that has it, OpenGL (WineD3D) is the better choice.
Run as `python3 -m bfme_wizard.vulkan` it prints one line, `<vulkan|opengl|unknown> <message>`, for the setup script.
"""
from __future__ import annotations

import ctypes
import struct
import sys
from dataclasses import dataclass

MIN_VERSION = (1, 3)
CPU = 4  # VkPhysicalDeviceType of a software renderer such as llvmpipe
TYPE_RANK = {2: 3, 1: 2, 3: 1}  # discrete, then integrated, then virtual


@dataclass(frozen=True)
class Device:
    name: str
    kind: int
    version: tuple[int, int]


class _InstanceCreateInfo(ctypes.Structure):
    _fields_ = [("sType", ctypes.c_int), ("pNext", ctypes.c_void_p), ("flags", ctypes.c_uint32),
                ("pApplicationInfo", ctypes.c_void_p), ("enabledLayerCount", ctypes.c_uint32),
                ("ppEnabledLayerNames", ctypes.c_void_p), ("enabledExtensionCount", ctypes.c_uint32),
                ("ppEnabledExtensionNames", ctypes.c_void_p)]


def devices() -> list[Device] | None:
    """Every Vulkan device, or None when there is no Vulkan loader. An empty list when Vulkan finds no device."""
    try:
        vk = ctypes.CDLL("libvulkan.so.1")
    except OSError:
        return None
    info = _InstanceCreateInfo(sType=1)  # VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO
    instance = ctypes.c_void_p()
    if vk.vkCreateInstance(ctypes.byref(info), None, ctypes.byref(instance)) != 0:
        return []
    try:
        count = ctypes.c_uint32()
        vk.vkEnumeratePhysicalDevices(instance, ctypes.byref(count), None)
        handles = (ctypes.c_void_p * count.value)()
        vk.vkEnumeratePhysicalDevices(instance, ctypes.byref(count), handles)
        found = []
        for handle in handles:
            # VkPhysicalDeviceProperties starts with apiVersion, driverVersion, vendorID, deviceID, deviceType and a
            # 256-byte name. The whole struct is about 824 bytes.
            props = ctypes.create_string_buffer(1024)
            vk.vkGetPhysicalDeviceProperties(ctypes.c_void_p(handle), props)
            api, _driver, _vendor, _device, kind = struct.unpack_from("5I", props.raw)
            name = props.raw[20:276].split(b"\0", 1)[0].decode(errors="replace")
            found.append(Device(name, kind, (api >> 22, (api >> 12) & 0x3FF)))
        return found
    finally:
        vk.vkDestroyInstance(instance, None)


def choose(found: list[Device] | None) -> tuple[str, str]:
    """("vulkan" or "opengl", why)."""
    if found is None:
        return "opengl", "Vulkan is not available"
    real = [d for d in found if d.kind != CPU]
    if not real:
        return "opengl", "no graphics card with Vulkan was found"
    best = max(real, key=lambda d: (d.version, TYPE_RANK.get(d.kind, 0)))
    version = f"{best.version[0]}.{best.version[1]}"
    if best.version < MIN_VERSION:
        return "opengl", f"Vulkan {version} on {best.name}, but Vulkan 1.3 or newer is needed"
    return "vulkan", f"Vulkan {version} on {best.name}"


def summary() -> str:
    """One line for the diagnostics."""
    try:
        backend, why = choose(devices())
    except Exception as error:  # a broken driver must not stop the report
        return f"could not check ({error})"
    return f"{why} (suits {'Vulkan' if backend == 'vulkan' else 'OpenGL'})"


def main() -> int:
    try:
        backend, why = choose(devices())
    except Exception as error:
        backend, why = "unknown", f"could not check Vulkan ({error})"
    print(backend, why)
    return 0


if __name__ == "__main__":
    sys.exit(main())
