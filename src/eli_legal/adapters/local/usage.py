"""How busy the machine is, and how much of it ELI Legal itself is using: processor, memory and
every graphics processor, on any operating system and any hardware. Nothing is installed for it:
each system is asked the way its own tools ask it, and a reading a system will not give is left
out, never guessed.

Graphics, by system (the readers follow ELI v3's, eli/core/hardware_profile.py):

- Windows, any maker (NVIDIA, AMD, Intel, Qualcomm, …): DXGI, which every Windows graphics driver
  implements, names each adapter and gives its own and shared memory; Windows' performance counters
  (as Task Manager reads them, asked by their English names, so any language of Windows answers)
  give how busy each one is and the memory in use.
- macOS: the IOAccelerator registry: Apple silicon (unified memory) and the Intel and AMD graphics
  of Intel Macs.
- Linux: nvidia-smi for NVIDIA; the kernel drivers' own files for the rest: AMD (its own memory and,
  on an APU, the system memory it is using), Intel (integrated or Arc, and its clock), Qualcomm
  Adreno and Apple (Asahi) on laptops, Arm Mali and others on boards (busy, from the kernel's
  frequency governor), NVIDIA Jetson (unified memory).

Graphics that share the system's memory (integrated, unified) are marked so: their memory is the
machine's, shown as such, never as a card's own.

Each ``read()`` compares with the one before, so processor use is the share over the time between
two readings (the first reading has none yet).
"""

from __future__ import annotations

import ctypes
import functools
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eli_legal.adapters.inference.hardware import _memory_bytes, host_env, nvidia_smi_path

MIB = 1024 * 1024
# The kernel's own folders on Linux; a test points them at a made-up machine.
_SYS = Path("/sys")
_PROC = Path("/proc")
_PCI_VENDORS = {
    0x10DE: "nvidia",
    0x1002: "amd",
    0x8086: "intel",
    0x5143: "qualcomm",
    0x106B: "apple",
}
# Graphics that are not PCI devices, by their kernel driver.
_SOC_DRIVERS = {
    "msm": "qualcomm",
    "asahi": "apple",
    "panfrost": "arm",
    "panthor": "arm",
    "lima": "arm",
    "mali": "arm",
    "v3d": "broadcom",
    "etnaviv": "vivante",
    "powervr": "imagination",
    "tegra": "nvidia",
    "nouveau": "nvidia",
}
# An AMD APU's own "VRAM" is the firmware's carve-out from system memory, if any.
_AMD_APU_CARVEOUT_MAX = 64 * MIB


@dataclass(frozen=True, slots=True)
class CardUse:
    name: str
    vendor: str = "unknown"
    # Shares the system's memory (integrated graphics, Apple silicon's unified memory): its
    # memory figures are a share of the machine's, not a card's own.
    shared: bool = False
    total_mb: int | None = None  # its own memory; for shared graphics, what it may use, if said
    used_mb: int | None = None
    busy_percent: int | None = None
    temp_c: int | None = None
    note: str = ""  # anything else it says of itself, e.g. its clock


@dataclass(frozen=True, slots=True)
class Usage:
    cpu_percent: float | None  # the whole machine
    app_cpu_percent: float | None  # ELI Legal, as a share of the whole machine
    ram_total: int
    ram_used: int
    app_ram: int  # ELI Legal's resident memory, bytes (0: not known)
    app_ram_is_peak: bool = False  # where only the peak is available
    cards: list[CardUse] = field(default_factory=list)
    cpus: int = 1
    unified: bool = False  # the processor and graphics share one memory (Apple silicon)


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _int(path: Path) -> int | None:
    try:
        return int(_text(path).split()[0])
    except (IndexError, ValueError):
        return None


def _quiet_run(args: list[str], timeout: float = 4) -> bytes:
    """A system program's output, run with the machine's own environment (never an installed
    copy's libraries), without a console window on Windows. Empty if it fails."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        done = subprocess.run(
            args,
            capture_output=True,
            timeout=timeout,
            check=False,
            creationflags=flags,
            env=host_env(),
        )
    except (OSError, subprocess.SubprocessError):
        return b""
    return done.stdout if done.returncode == 0 else b""


# ── processor ─────────────────────────────────────────────────────────────────


def _proc_stat() -> tuple[int, int] | None:
    """(busy, total) processor ticks since boot, Linux."""
    try:
        first = _text(Path("/proc/stat")).splitlines()[0].split()
        ticks = [int(x) for x in first[1:9]]
    except (IndexError, ValueError):
        return None
    idle = ticks[3] + (ticks[4] if len(ticks) > 4 else 0)  # idle and waiting on the disk
    return sum(ticks) - idle, sum(ticks)


def _windows_times() -> tuple[int, int] | None:
    """(busy, total) from GetSystemTimes, Windows. Kernel time includes idle time."""

    class _FileTime(ctypes.Structure):
        _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]

    idle, kernel, user = _FileTime(), _FileTime(), _FileTime()
    try:
        ok = ctypes.windll.kernel32.GetSystemTimes(  # type: ignore[attr-defined,unused-ignore]
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
        )
    except (AttributeError, OSError):
        return None
    if not ok:
        return None

    def value(t: _FileTime) -> int:
        return int((t.high << 32) | t.low)

    total = value(kernel) + value(user)
    return total - value(idle), total


@functools.lru_cache(maxsize=1)
def _libsystem() -> Any:
    return ctypes.CDLL("/usr/lib/libSystem.dylib")


def _macos_ticks() -> tuple[int, int] | None:
    """(busy, total) from the Mach kernel's processor load (HOST_CPU_LOAD_INFO), macOS."""
    try:
        lib = _libsystem()
        lib.mach_host_self.restype = ctypes.c_uint
        info = (ctypes.c_uint * 4)()  # user, system, idle, nice
        count = ctypes.c_uint(4)
        if lib.host_statistics(lib.mach_host_self(), 3, ctypes.byref(info), ctypes.byref(count)):
            return None
    except (AttributeError, OSError):
        return None
    user, system, idle, nice = (int(x) for x in info)
    return user + system + nice, user + system + idle + nice


def _system_ticks() -> tuple[int, int] | None:
    if sys.platform.startswith("linux"):
        return _proc_stat()
    if sys.platform == "win32":
        return _windows_times()
    if sys.platform == "darwin":
        return _macos_ticks()
    return None


# ── ELI Legal's own memory ───────────────────────────────────────────────────


def _app_ram() -> tuple[int, bool]:
    """ELI Legal's resident memory in bytes, and whether it is only the peak."""
    if sys.platform.startswith("linux"):
        for line in _text(Path("/proc/self/status")).splitlines():
            if line.startswith("VmRSS:"):
                try:
                    return int(line.split()[1]) * 1024, False
                except (IndexError, ValueError):
                    break
        return 0, False
    if sys.platform == "win32":

        class _Counters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_uint32),
                ("PageFaultCount", ctypes.c_uint32),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = _Counters()
        counters.cb = ctypes.sizeof(_Counters)
        try:
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined,unused-ignore]
            kernel32.GetCurrentProcess.restype = ctypes.c_void_p
            psapi = ctypes.windll.psapi  # type: ignore[attr-defined,unused-ignore]
            psapi.GetProcessMemoryInfo.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(_Counters),
                ctypes.c_uint32,
            ]
            if psapi.GetProcessMemoryInfo(
                kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
            ):
                return int(counters.WorkingSetSize), False
        except (AttributeError, OSError):
            pass
        return 0, False
    if sys.platform == "darwin":

        class _Time(ctypes.Structure):
            _fields_ = [("seconds", ctypes.c_int), ("microseconds", ctypes.c_int)]

        class _TaskInfo(ctypes.Structure):  # mach_task_basic_info
            _fields_ = [
                ("virtual_size", ctypes.c_uint64),
                ("resident_size", ctypes.c_uint64),
                ("resident_size_max", ctypes.c_uint64),
                ("user_time", _Time),
                ("system_time", _Time),
                ("policy", ctypes.c_int),
                ("suspend_count", ctypes.c_int),
            ]

        try:
            lib = _libsystem()
            task = ctypes.c_uint.in_dll(lib, "mach_task_self_")
            info = _TaskInfo()
            count = ctypes.c_uint(ctypes.sizeof(_TaskInfo) // 4)
            if not lib.task_info(task, 20, ctypes.byref(info), ctypes.byref(count)):
                return int(info.resident_size), False
        except (AttributeError, OSError, ValueError):
            pass
    try:  # anywhere else: the peak, from the C library
        import resource

        peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return (peak if sys.platform == "darwin" else peak * 1024), True
    except (ImportError, OSError, ValueError):
        return 0, False


# ── graphics: NVIDIA's own tool (Linux, and Windows as a fallback) ───────────


def _nvidia() -> list[CardUse]:
    smi = nvidia_smi_path()
    if not smi:
        return []
    return _nvidia_from(
        _quiet_run(
            [
                smi,
                "--query-gpu=name,memory.total,memory.used,utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits",
            ]
        ).decode("utf-8", "replace")
    )


def _nvidia_from(out: str) -> list[CardUse]:
    def num(value: str) -> int | None:
        try:
            return int(float(value))
        except ValueError:
            return None  # "[N/A]", "Not Supported"

    cards = []
    for line in out.splitlines():
        row = [c.strip() for c in line.rsplit(",", 4)]
        if len(row) != 5 or not row[0]:
            continue  # a message, not a card
        total, used = num(row[1]), num(row[2])
        cards.append(
            CardUse(
                row[0],
                "nvidia",
                # memory not reported: one memory shared with the processor (Jetson, Grace, GB10)
                shared=total is None,
                total_mb=total,
                used_mb=used,
                busy_percent=num(row[3]),
                temp_c=num(row[4]),
            )
        )
    return cards


# ── graphics: Linux, the kernel drivers' own files ───────────────────────────


@functools.lru_cache(maxsize=64)
def _pci_name(address: str) -> str:
    if not address or not shutil.which("lspci"):
        return ""
    first = _quiet_run(["lspci", "-s", address, "-nn"], 5).decode("utf-8", "replace")
    line = first.strip().splitlines()[:1]
    return line[0].split(":", 2)[-1].strip() if line and ":" in line[0] else ""


def _linux_devices() -> list[tuple[str, str, Path, Path]]:
    """(vendor, driver, device folder, card folder) for each graphics device the kernel has,
    once each."""
    found: list[tuple[str, str, Path, Path]] = []
    seen: set[Path] = set()
    for card in sorted((_SYS / "class/drm").glob("card[0-9]*")):
        if not re.fullmatch(r"card\d+", card.name):
            continue  # a connector (card0-DP-1), not a device
        device = card / "device"
        try:
            real = device.resolve()
            driver = (device / "driver").resolve().name
        except OSError:
            continue
        if real in seen or driver in ("simple-framebuffer", "simpledrm", "vkms", "vgem"):
            continue
        seen.add(real)
        try:
            vendor = _PCI_VENDORS.get(int(_text(device / "vendor"), 16), "")
        except ValueError:
            vendor = ""
        found.append((vendor or _SOC_DRIVERS.get(driver, "unknown"), driver, device, card))
    return found


def _device_name(device: Path, vendor: str, driver: str) -> str:
    name = _pci_name(device.resolve().name) if (device / "vendor").exists() else ""
    if name:
        return name
    compatible = _text(device / "of_node" / "compatible").split("\0")[0]
    if compatible:  # the device tree's name, e.g. "arm,mali-bifrost"
        return compatible
    return f"{vendor.capitalize() if vendor != 'unknown' else 'Graphics'} ({driver})"


def _devfreq_busy(device: Path) -> int | None:
    """How busy a system-on-chip graphics processor is, from the kernel's frequency governor
    ("45@800000000Hz"), where it says."""
    for load in device.glob("devfreq/*/load"):
        m = re.match(r"\s*(\d+)", _text(load))
        if m:
            return min(100, int(m.group(1)))
    return None


def _linux_cards(nvidia_done: bool) -> list[CardUse]:
    cards: list[CardUse] = []
    for vendor, driver, device, card in _linux_devices():
        if driver == "nvidia":
            if not nvidia_done:  # the driver is there, its tool is not: name only
                cards.append(CardUse(_device_name(device, vendor, driver), "nvidia"))
            continue
        name = _device_name(device, vendor, driver)
        if driver == "amdgpu":
            total = _int(device / "mem_info_vram_total")
            used = _int(device / "mem_info_vram_used")
            busy = _int(device / "gpu_busy_percent")
            temp = None
            for hwmon in sorted(device.glob("hwmon/hwmon*")):
                raw = _int(hwmon / "temp1_input")
                temp = raw // 1000 if raw is not None else None
            if total is not None and total <= _AMD_APU_CARVEOUT_MAX:
                # an APU: it works from system memory (GTT); how much it may use and is using
                gtt_total = _int(device / "mem_info_gtt_total")
                gtt_used = _int(device / "mem_info_gtt_used")
                cards.append(
                    CardUse(
                        name,
                        "amd",
                        shared=True,
                        total_mb=None if gtt_total is None else gtt_total // MIB,
                        used_mb=None if gtt_used is None else gtt_used // MIB,
                        busy_percent=busy,
                        temp_c=temp,
                    )
                )
            else:
                cards.append(
                    CardUse(
                        name,
                        "amd",
                        total_mb=None if total is None else total // MIB,
                        used_mb=None if used is None else used // MIB,
                        busy_percent=busy,
                        temp_c=temp,
                    )
                )
            continue
        if driver in ("i915", "xe"):
            act = _int(card / "gt_act_freq_mhz") or _int(device / "tile0/gt0/freq0/act_freq")
            top = _int(card / "gt_max_freq_mhz") or _int(device / "tile0/gt0/freq0/max_freq")
            discrete = (device / "mem_info_vram_total").exists() or "arc" in name.lower()
            cards.append(
                CardUse(
                    name,
                    "intel",
                    shared=not discrete,
                    note=f"running at {act} of {top} MHz" if act is not None and top else "",
                )
            )
            continue
        cards.append(
            CardUse(
                name,
                vendor,
                shared=not (device / "vendor").exists(),  # a system-on-chip shares the memory
                busy_percent=_devfreq_busy(device),
            )
        )
    # NVIDIA Jetson: an integrated GPU with its load in tenths of a percent.
    if not nvidia_done and not any(c.vendor == "nvidia" for c in cards):
        for load in (_SYS / "devices/gpu.0/load", _SYS / "devices/platform/gpu.0/load"):
            value = _int(load)
            if value is not None:
                model = _text(_PROC / "device-tree/model").strip("\0") or "NVIDIA Jetson"
                cards.append(
                    CardUse(f"{model} GPU", "nvidia", shared=True, busy_percent=value // 10)
                )
                break
    # Qualcomm Adreno through the kgsl driver (some Snapdragon Linux builds).
    kgsl = _text(_SYS / "class/kgsl/kgsl-3d0/gpu_busy_percentage")
    if kgsl and not any(c.vendor == "qualcomm" for c in cards):
        m = re.match(r"\s*(\d+)", kgsl)
        name = _text(_SYS / "class/kgsl/kgsl-3d0/gpu_model") or "Qualcomm Adreno"
        cards.append(
            CardUse(name, "qualcomm", shared=True, busy_percent=int(m.group(1)) if m else None)
        )
    return cards


# ── graphics: macOS ──────────────────────────────────────────────────────────


def _macos_cards() -> list[CardUse]:
    """Every graphics processor in the IOAccelerator registry (no administrator rights needed)."""
    raw = _quiet_run(
        [shutil.which("ioreg") or "/usr/sbin/ioreg", "-r", "-d", "1", "-c", "IOAccelerator", "-a"],
        10,
    )
    try:
        entries = plistlib.loads(raw) if raw else []
    except Exception:  # noqa: BLE001 - an unreadable answer is no answer
        return []
    return _macos_cards_from(entries)


def _stat(stats: dict[str, Any], *names: str) -> float | None:
    for key, value in stats.items():
        if any(n.lower() in str(key).lower() for n in names) and isinstance(value, (int, float)):
            return float(value)
    return None


def _macos_cards_from(entries: Any) -> list[CardUse]:
    cards: list[CardUse] = []
    for item in entries if isinstance(entries, list) else [entries]:
        if not isinstance(item, dict):
            continue
        stats = item.get("PerformanceStatistics") or {}
        free_b = _stat(stats, "vramFreeBytes")
        used_b = _stat(stats, "vramUsedBytes", "In use system memory")
        raw_name = item.get("model") or item.get("IOGLBundleName") or item.get("IOClass") or "GPU"
        name = (
            raw_name.decode("utf-8", "replace") if isinstance(raw_name, bytes) else str(raw_name)
        ).strip("\x00 ")
        io_class = str(item.get("IOClass") or "")
        apple = "apple" in name.lower() or "AGX" in io_class
        busy = _stat(stats, "Device Utilization %", "GPU Activity")
        temp = _stat(stats, "Temperature")
        cards.append(
            CardUse(
                name,
                "apple" if apple else ("amd" if "amd" in io_class.lower() else "intel"
                                       if "intel" in io_class.lower() else "unknown"),
                shared=apple or "intel" in io_class.lower(),
                total_mb=None if free_b is None or used_b is None else int(free_b + used_b) // MIB,
                used_mb=None if used_b is None else int(used_b) // MIB,
                busy_percent=None if busy is None else int(busy),
                temp_c=None if temp is None else int(temp),
            )
        )  # fmt: skip
    return cards


# ── graphics: Windows ────────────────────────────────────────────────────────


def _windows_adapters() -> list[dict[str, Any]]:
    """Every graphics adapter, any maker, from DXGI: name, maker, own and shared memory and its
    LUID (to match it with the performance counters). The software renderer is left out."""
    from ctypes import wintypes

    class _LUID(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    class _DESC1(ctypes.Structure):
        _fields_ = [
            ("Description", wintypes.WCHAR * 128),
            ("VendorId", wintypes.UINT),
            ("DeviceId", wintypes.UINT),
            ("SubSysId", wintypes.UINT),
            ("Revision", wintypes.UINT),
            ("DedicatedVideoMemory", ctypes.c_size_t),
            ("DedicatedSystemMemory", ctypes.c_size_t),
            ("SharedSystemMemory", ctypes.c_size_t),
            ("AdapterLuid", _LUID),
            ("Flags", wintypes.UINT),
        ]

    class _GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    def call(obj: Any, index: int, restype: Any, *types: Any) -> Any:
        vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *types)(vtable[index])  # type: ignore[attr-defined,unused-ignore]

    h = "770aae78f26f4dbaa829253c83d1b387"  # IDXGIFactory1
    iid = _GUID(
        int(h[0:8], 16),
        int(h[8:12], 16),
        int(h[12:16], 16),
        (ctypes.c_ubyte * 8)(*bytes.fromhex(h[16:])),
    )
    try:
        dxgi = ctypes.WinDLL("dxgi")  # type: ignore[attr-defined,unused-ignore]
        factory = ctypes.c_void_p()
        if dxgi.CreateDXGIFactory1(ctypes.byref(iid), ctypes.byref(factory)) != 0 or not factory:
            return []
    except Exception:  # noqa: BLE001 - no DXGI: no adapters to name
        return []
    adapters: list[dict[str, Any]] = []
    try:
        for index in range(64):
            adapter = ctypes.c_void_p()
            # IDXGIFactory1::EnumAdapters1 (vtable 12); DXGI_ERROR_NOT_FOUND ends the list
            enum = call(factory, 12, ctypes.c_long, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p))
            if enum(factory, index, ctypes.byref(adapter)) != 0 or not adapter:
                break
            try:
                desc = _DESC1()
                # IDXGIAdapter1::GetDesc1 (vtable 10); flag 2 is the software renderer
                get = call(adapter, 10, ctypes.c_long, ctypes.POINTER(_DESC1))
                if get(adapter, ctypes.byref(desc)) != 0 or desc.Flags & 2:
                    continue
                own = int(desc.DedicatedVideoMemory) // MIB
                shared = int(desc.SharedSystemMemory) // MIB
                adapters.append(
                    {
                        "name": desc.Description.strip("\x00 ") or "Graphics adapter",
                        "vendor": _PCI_VENDORS.get(int(desc.VendorId), "unknown"),
                        # integrated: a small carve-out, or none; it works from shared memory
                        "shared": own < 512 and shared > own,
                        "own_mb": own,
                        "shared_mb": shared,
                        "luid": f"luid_0x{desc.AdapterLuid.HighPart & 0xFFFFFFFF:08x}"
                        f"_0x{desc.AdapterLuid.LowPart:08x}",
                    }
                )
            finally:
                call(adapter, 2, ctypes.c_ulong)(adapter)  # Release
    except Exception:  # noqa: BLE001 - what was read so far stands
        pass
    finally:
        call(factory, 2, ctypes.c_ulong)(factory)
    return adapters


class _WindowsCounters:
    """Windows' graphics performance counters, kept open between readings (how busy is a rate:
    it needs two). Asked by their English names, so a Windows in any language answers."""

    _PATHS = {
        "busy": "\\GPU Engine(*)\\Utilization Percentage",
        "own": "\\GPU Adapter Memory(*)\\Dedicated Usage",
        "shared": "\\GPU Adapter Memory(*)\\Shared Usage",
    }

    def __init__(self) -> None:
        from ctypes import wintypes

        class _Union(ctypes.Union):
            _fields_ = [
                ("long", ctypes.c_long),
                ("double", ctypes.c_double),
                ("large", ctypes.c_longlong),
                ("text", ctypes.c_void_p),
            ]

        class _Value(ctypes.Structure):
            _fields_ = [("status", wintypes.DWORD), ("u", _Union)]

        class _Item(ctypes.Structure):
            _fields_ = [("name", ctypes.c_wchar_p), ("value", _Value)]

        self._Item = _Item
        pdh = ctypes.WinDLL("pdh")  # type: ignore[attr-defined,unused-ignore]
        pdh.PdhOpenQueryW.argtypes = [
            wintypes.LPCWSTR,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        pdh.PdhAddEnglishCounterW.argtypes = [
            ctypes.c_void_p,
            wintypes.LPCWSTR,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        pdh.PdhCollectQueryData.argtypes = [ctypes.c_void_p]
        pdh.PdhGetFormattedCounterArrayW.argtypes = [
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD),
            ctypes.c_void_p,
        ]
        for fn in (
            "PdhOpenQueryW",
            "PdhAddEnglishCounterW",
            "PdhCollectQueryData",
            "PdhGetFormattedCounterArrayW",
        ):
            getattr(pdh, fn).restype = wintypes.DWORD
        self.pdh = pdh
        self.query = ctypes.c_void_p()
        if pdh.PdhOpenQueryW(None, 0, ctypes.byref(self.query)) != 0:
            raise OSError("performance counters unavailable")
        self.counters: dict[str, ctypes.c_void_p] = {}
        for key, path in self._PATHS.items():
            handle = ctypes.c_void_p()
            if pdh.PdhAddEnglishCounterW(self.query, path, 0, ctypes.byref(handle)) == 0:
                self.counters[key] = handle
        pdh.PdhCollectQueryData(self.query)  # fmt: skip

    def _values(self, handle: ctypes.c_void_p) -> dict[str, float]:
        from ctypes import wintypes

        size, count = wintypes.DWORD(0), wintypes.DWORD(0)
        fmt_double = 0x00000200
        status = self.pdh.PdhGetFormattedCounterArrayW(
            handle, fmt_double, ctypes.byref(size), ctypes.byref(count), None
        )
        if status != 0x800007D2 or not size.value:  # PDH_MORE_DATA: the size it needs
            return {}
        buffer = (ctypes.c_byte * size.value)()
        status = self.pdh.PdhGetFormattedCounterArrayW(
            handle, fmt_double, ctypes.byref(size), ctypes.byref(count), buffer
        )
        if status != 0:
            return {}
        items = ctypes.cast(buffer, ctypes.POINTER(self._Item))
        return {
            str(items[i].name or ""): float(items[i].value.u.double)
            for i in range(count.value)
            if items[i].value.status in (0, 1)  # valid data, new data
        }

    def read(self) -> dict[str, dict[str, float]]:
        """{luid: {"busy": %, "own": bytes, "shared": bytes}} for each adapter."""
        if self.pdh.PdhCollectQueryData(self.query) != 0:
            return {}
        return _by_adapter({key: self._values(h) for key, h in self.counters.items()})


def _by_adapter(raw: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    """Windows' counter instances, by adapter. An engine's use is summed over the processes
    using it; an adapter is as busy as its busiest engine; memory is summed per adapter."""
    out: dict[str, dict[str, float]] = {}
    engines: dict[str, float] = {}
    for key, values in raw.items():
        for name, value in values.items():
            m = re.search(r"(luid_0x[0-9a-f]+_0x[0-9a-f]+)(?:_phys_\d+)?(_eng_\d+)?", name, re.I)
            if not m:
                continue
            luid = m.group(1).lower()
            if key == "busy":  # each engine summed over the processes using it
                engine = luid + (m.group(2) or "")
                engines[engine] = engines.get(engine, 0.0) + value
            else:
                out.setdefault(luid, {})[key] = out.get(luid, {}).get(key, 0.0) + value
    for engine, value in engines.items():  # an adapter is as busy as its busiest engine
        luid = engine.split("_eng_")[0]
        slot = out.setdefault(luid, {})
        slot["busy"] = min(100.0, max(slot.get("busy", 0.0), value))
    return out


def _windows_cards(counters: _WindowsCounters | None) -> list[CardUse]:
    readings = counters.read() if counters is not None else {}
    cards = []
    for a in _windows_adapters():
        live = readings.get(a["luid"], {})
        if a["shared"]:
            used = live.get("shared")
            total = a["shared_mb"] or None
        else:
            used = live.get("own")
            total = a["own_mb"] or None
        busy = live.get("busy")
        cards.append(
            CardUse(
                a["name"],
                a["vendor"],
                shared=a["shared"],
                total_mb=total,
                used_mb=None if used is None else int(used) // MIB,
                busy_percent=None if busy is None else round(busy),
            )
        )
    return cards


# ── the meter ────────────────────────────────────────────────────────────────


class UsageMeter:
    """Readings over time. Call ``read()`` every few seconds, off the interface thread: asking
    a graphics driver can take a fraction of a second."""

    def __init__(self) -> None:
        self._last_system = _system_ticks()
        self._last_app = (time.monotonic(), time.process_time())
        self._cpus = os.cpu_count() or 1
        self._counters: _WindowsCounters | None = None
        if sys.platform == "win32":
            try:
                self._counters = _WindowsCounters()
            except Exception:  # noqa: BLE001 - no counters: names and memory only
                self._counters = None
        self._unified = sys.platform == "darwin" and platform.machine() == "arm64"

    def cards(self) -> list[CardUse]:
        if sys.platform == "win32":
            return _windows_cards(self._counters) or _nvidia()
        if sys.platform == "darwin":
            return _macos_cards()
        if sys.platform.startswith("linux"):
            nvidia = _nvidia()
            return nvidia + _linux_cards(nvidia_done=bool(nvidia))
        return _nvidia()

    def read(self) -> Usage:
        system = _system_ticks()
        cpu: float | None = None
        if system is not None and self._last_system is not None:
            busy = system[0] - self._last_system[0]
            total = system[1] - self._last_system[1]
            cpu = max(0.0, min(100.0, 100.0 * busy / total)) if total > 0 else None
        self._last_system = system
        now = (time.monotonic(), time.process_time())
        wall = now[0] - self._last_app[0]
        app_cpu = (
            max(0.0, min(100.0, 100.0 * (now[1] - self._last_app[1]) / (wall * self._cpus)))
            if wall > 0.2
            else None
        )
        self._last_app = now
        total, available = _memory_bytes()
        app_ram, peak = _app_ram()
        try:
            cards = self.cards()
        except Exception:  # noqa: BLE001 - graphics unreadable this time: the rest still stands
            cards = []
        return Usage(
            cpu_percent=cpu,
            app_cpu_percent=app_cpu,
            ram_total=total,
            ram_used=max(0, total - available) if total else 0,
            app_ram=app_ram,
            app_ram_is_peak=peak,
            cards=cards,
            cpus=self._cpus,
            unified=self._unified,
        )


# ── in words ─────────────────────────────────────────────────────────────────


def _gb(n: int) -> str:
    return f"{n / 1024**3:.1f}"


def _size(n: int) -> str:
    return f"{_gb(n)} GB" if n >= 1024**3 else f"{n / MIB:.0f} MB"


def _card_memory(card: CardUse) -> str:
    if card.used_mb is None:
        return "shares the system memory" if card.shared else ""
    used = f"{card.used_mb / 1024:.1f}"
    if card.total_mb:
        of = f"{used} of {card.total_mb / 1024:.1f} GB"
    else:
        of = f"{used} GB"
    return f"{of} shared" if card.shared else of


def summary(u: Usage) -> str:
    """One line for the status bar."""
    parts = []
    if u.cpu_percent is not None:
        own = f" (ELI Legal {u.app_cpu_percent:.0f}%)" if u.app_cpu_percent is not None else ""
        parts.append(f"CPU {u.cpu_percent:.0f}%{own}")
    if u.ram_total:
        own = f" (ELI Legal {_size(u.app_ram)})" if u.app_ram else ""
        what = "Unified memory" if u.unified else "RAM"
        parts.append(f"{what} {_gb(u.ram_used)} of {_gb(u.ram_total)} GB{own}")
    for n, card in enumerate(u.cards, start=1):
        label = f"GPU {n}" if len(u.cards) > 1 else "GPU"
        bits = [f"{card.busy_percent}%"] if card.busy_percent is not None else []
        memory = _card_memory(card)
        if memory:
            bits.append(memory)
        parts.append(f"{label} {', '.join(bits)}" if bits else label)
    return "  ·  ".join(parts)


def details(u: Usage) -> str:
    """Several lines, for the tooltip."""
    lines = [f"Processor: {u.cpus} logical cores"]
    if u.cpu_percent is not None:
        lines.append(f"  in use: {u.cpu_percent:.0f}% of the whole machine")
    if u.app_cpu_percent is not None:
        lines.append(f"  by ELI Legal (with its own model, if loaded): {u.app_cpu_percent:.0f}%")
    if u.ram_total:
        kind = "Unified memory (processor and graphics share it)" if u.unified else "Memory"
        lines.append(f"{kind}: {_gb(u.ram_used)} of {_gb(u.ram_total)} GB in use")
        if u.app_ram:
            peak = " at most (the peak so far)" if u.app_ram_is_peak else ""
            lines.append(f"  by ELI Legal: {_size(u.app_ram)}{peak}")
    if not u.cards:
        lines.append("Graphics: none reports its use (or none is fitted)")
    for n, card in enumerate(u.cards, start=1):
        bits = []
        if card.busy_percent is not None:
            bits.append(f"{card.busy_percent}% busy")
        if card.used_mb is not None:
            of = f" of {card.total_mb}" if card.total_mb else ""
            bits.append(f"{card.used_mb}{of} MB in use")
        if card.shared:
            bits.append("shares the system memory")
        elif card.total_mb and card.used_mb is None:
            bits.append(f"{card.total_mb} MB of its own")
        if card.temp_c is not None:
            bits.append(f"{card.temp_c} °C")
        if card.note:
            bits.append(card.note)
        lines.append(f"Graphics {n}: {card.name}" + (f": {', '.join(bits)}" if bits else ""))
    return "\n".join(lines)
