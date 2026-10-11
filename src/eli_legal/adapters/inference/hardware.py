"""What this machine has to run a model on: processor threads, memory, and the graphics card.

Read from the machine every time it matters, never from a list of machines. The figure that
decides a fit is the graphics memory that is FREE now: the desktop, a browser or another model
runner hold part of the card before ELI Legal starts, and sizing from the card's total loads a
model that then runs out of memory.

The same probes ELI v2 and v3 use (their ``eli.core.hardware_profile``): NVIDIA through
nvidia-smi on any system; AMD through rocm-smi or the amdgpu driver's own counters; Intel Arc and
shared-memory graphics (Intel, AMD APU, Qualcomm) through the kernel's device list; Windows
through the display-class registry; macOS through system_profiler. Where a card is present but
its free memory cannot be read, the estimate is marked as one (``vram_measured`` False) and the
loader corrects it by what actually loads.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

MIB = 1024 * 1024
GIB = 1024 * MIB

# Graphics memory left unallocated. llama.cpp allocates more at the first generation than at
# load, and a card filled to the last megabyte fails there. The same defaults as ELI; set
# ELI_LEGAL_VRAM_RESERVE_MB to change it for this machine.
DEFAULT_VRAM_RESERVE_MB = 700
# Shared-memory graphics do not have that cliff, and a 700 MB reserve leaves them nothing.
DEFAULT_SHARED_VRAM_RESERVE_MB = 400

_PCI_NVIDIA, _PCI_AMD, _PCI_INTEL, _PCI_QUALCOMM = "0x10de", "0x1002", "0x8086", "0x5143"
_INTEL_ARC_DEVICE_RANGES = ((0x4F80, 0x4F8F), (0x5690, 0x56BF), (0xE200, 0xE21F))
_DISPLAY_CLASS = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"

# Factory memory of cards whose driver cannot be asked (nvidia-smi out of step with the kernel
# module after an update; Intel publishes no free-memory counter). Most specific name first.
# Used only then, and the result is marked as an estimate.
_NVIDIA_VRAM_MB = (
    ("rtx 4090", 24576),
    ("rtx 4080", 16384),
    ("rtx 4070 ti super", 16384),
    ("rtx 4070", 12288),
    ("rtx 4060", 8192),
    ("rtx 3090", 24576),
    ("rtx 3080 ti", 12288),
    ("rtx 3080", 10240),
    ("rtx 3070", 8192),
    ("rtx 3060 ti", 8192),
    ("rtx 3060", 12288),
    ("rtx 3050", 8192),
    ("rtx 2080 ti", 11264),
    ("rtx 2080", 8192),
    ("rtx 2070", 8192),
    ("rtx 2060 super", 8192),
    ("rtx 2060", 6144),
    ("gtx 1660", 6144),
    ("gtx 1650", 4096),
    ("gtx 1080 ti", 11264),
    ("gtx 1080", 8192),
    ("gtx 1070", 8192),
    ("gtx 1060", 3072),
    ("gtx 1050 ti", 4096),
    ("gtx 1050", 2048),
    ("rtx a6000", 49152),
    ("rtx a5000", 24576),
    ("rtx a4000", 16384),
    ("quadro rtx 8000", 49152),
    ("quadro rtx 6000", 24576),
)
_INTEL_ARC_VRAM_MB = (
    ("a770 16", 16384),
    ("a770", 8192),
    ("a750", 8192),
    ("a580", 8192),
    ("a380", 6144),
    ("a310", 4096),
    ("b580", 12288),
    ("b570", 10240),
)


@dataclass(slots=True)
class Hardware:
    cpu_threads: int = 1
    ram_gb: float = 0.0
    available_ram_gb: float = 0.0
    has_gpu: bool = False
    gpu_name: str = ""
    gpu_vendor: str = ""  # nvidia | amd | intel | apple | qualcomm
    gpu_integrated: bool = False  # shares system memory (Intel, AMD APU, Apple, Qualcomm)
    gpu_count: int = 0
    total_vram_mb: int = 0
    free_vram_mb: int = 0  # FREE now, on the card with the most free
    vram_measured: bool = False  # read from the driver, not estimated from the card's size
    vulkan_loader: bool = False
    # A graphics device is present that no probe could read: not the same as no card.
    uncertain: bool = False

    def as_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["ram_gb"] = round(self.ram_gb, 1)
        out["available_ram_gb"] = round(self.available_ram_gb, 1)
        return out

    def describe(self) -> str:
        """One line for a person: what there is to run a model on."""
        memory = f"{self.available_ram_gb:.1f} of {self.ram_gb:.1f} GB memory free"
        base = f"{self.cpu_threads} processor threads, {memory}"
        if not self.has_gpu:
            return base + (
                "; a graphics device is present but could not be read"
                if self.uncertain
                else "; no graphics card"
            )
        free = f"{self.free_vram_mb} of {self.total_vram_mb} MB free"
        if not self.vram_measured:
            free = f"about {self.free_vram_mb} MB usable (estimated)"
        shared = ", shares system memory" if self.gpu_integrated else ""
        return f"{base}; {self.gpu_name}{shared}: {free}"


# ── system programs see the system's libraries, not the bundle's ─────────────


def host_env() -> dict[str, str]:
    """The environment for a system program (nvidia-smi, lspci): the machine's own.

    An installed copy points LD_LIBRARY_PATH at its own libraries, and a system program started
    with that loads them by name and can fail to run. nvidia-smi failing that way reads as "no
    graphics card"."""
    env = dict(os.environ)
    roots = [
        os.path.realpath(str(c))
        for c in (getattr(sys, "_MEIPASS", None), os.environ.get("APPDIR"))
        if c
    ]
    if getattr(sys, "frozen", False):
        roots.append(os.path.realpath(os.path.dirname(sys.executable)))
    if not roots:
        return env
    if "LD_LIBRARY_PATH_ORIG" in env:
        env["LD_LIBRARY_PATH"] = env.pop("LD_LIBRARY_PATH_ORIG")
    for key in ("LD_LIBRARY_PATH", "LD_PRELOAD", "PATH"):
        parts = [p for p in env.get(key, "").split(os.pathsep) if p]
        kept = [
            p
            for p in parts
            if not any(
                os.path.realpath(p) == r or os.path.realpath(p).startswith(r + os.sep)
                for r in roots
            )
        ]
        if kept:
            env[key] = os.pathsep.join(kept)
        else:
            env.pop(key, None)
    return env


def _run(args: list[str], timeout: float) -> str:
    """A probe's output, or "" when the program is missing, fails or takes too long."""
    try:
        proc = subprocess.run(  # noqa: S603 - fixed arguments, no shell
            args, capture_output=True, text=True, timeout=timeout, env=host_env(), check=False
        )
    except (OSError, subprocess.SubprocessError):
        log.debug("probe did not run: %s", args[0], exc_info=True)
        return ""
    return proc.stdout or "" if proc.returncode == 0 else ""


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


# ── memory ───────────────────────────────────────────────────────────────────


def _memory_bytes() -> tuple[int, int]:
    """(installed, available now) in bytes; zeros where the system will not say."""
    if sys.platform.startswith("linux"):
        total = available = 0
        for line in _read(Path("/proc/meminfo")).splitlines():
            if line.startswith("MemTotal:"):
                total = int(line.split()[1]) * 1024
            elif line.startswith("MemAvailable:"):
                available = int(line.split()[1]) * 1024
        return total, available
    if sys.platform == "win32":

        class _Status(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = _Status()
        status.dwLength = ctypes.sizeof(_Status)
        try:
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined,unused-ignore]
                return int(status.ullTotalPhys), int(status.ullAvailPhys)
        except (AttributeError, OSError):
            log.debug("memory status unavailable", exc_info=True)
        return 0, 0
    if sys.platform == "darwin":
        total = 0
        raw = _run(["sysctl", "-n", "hw.memsize"], 5).strip()
        if raw.isdigit():
            total = int(raw)
        pages = 0
        page_size = 4096
        for line in _run(["vm_stat"], 5).splitlines():
            m = re.search(r"page size of (\d+) bytes", line)
            if m:
                page_size = int(m.group(1))
            m = re.match(r"Pages (free|inactive|speculative|purgeable):\s+(\d+)", line)
            if m:
                pages += int(m.group(2))
        return total, pages * page_size
    return 0, 0


# ── graphics cards ───────────────────────────────────────────────────────────


def nvidia_smi_path() -> str | None:
    """nvidia-smi wherever the driver put it. On Windows it is often not on PATH."""
    found = shutil.which("nvidia-smi")
    if found:
        return found
    if os.name == "nt":
        candidates = [
            Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "nvidia-smi.exe",
            Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
            / "NVIDIA Corporation"
            / "NVSMI"
            / "nvidia-smi.exe",
            Path(os.environ.get("ProgramW6432", r"C:\Program Files"))
            / "NVIDIA Corporation"
            / "NVSMI"
            / "nvidia-smi.exe",
        ]
    else:
        candidates = [
            Path("/usr/bin/nvidia-smi"),
            Path("/usr/local/bin/nvidia-smi"),
            Path("/opt/nvidia/bin/nvidia-smi"),
        ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def vulkan_loader_present() -> bool:
    """Whether the system's Vulkan loader is installed (graphics drivers normally bring it)."""
    if sys.platform == "win32":
        root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
        return (root / "System32" / "vulkan-1.dll").is_file()
    import ctypes.util

    return bool(ctypes.util.find_library("vulkan"))


def _lookup_mb(name: str, table: tuple[tuple[str, int], ...]) -> int:
    low = name.lower()
    return next((mb for needle, mb in table if needle in low), 0)


def _is_discrete(name: str) -> bool:
    low = name.lower()
    if any(k in low for k in ("geforce", "quadro", "tesla", "rtx ", "gtx ", "nvidia")):
        return True
    if any(k in low for k in ("radeon pro", "instinct", "firepro")):
        return True
    return ("arc" in low and "intel" in low) or bool(re.search(r"\brx\s*\d", low))


def _is_integrated(name: str, vendor: str) -> bool:
    if _is_discrete(name):
        return False
    low = name.lower()
    if vendor == "apple" or (sys.platform == "darwin" and "apple" in low):
        return True
    if vendor == "intel" or any(k in low for k in ("intel", "iris", "uhd")):
        return "arc" not in low
    if vendor in ("amd", "qualcomm"):
        return True
    return any(k in low for k in ("radeon", "vega", "adreno", "snapdragon"))


def _vendor_of(name: str) -> str:
    low = name.lower()
    if any(k in low for k in ("nvidia", "geforce", "rtx", "gtx", "quadro", "tesla")):
        return "nvidia"
    if any(k in low for k in ("amd", "radeon", "rx ", "ati", "vega")):
        return "amd"
    if any(k in low for k in ("intel", "iris", "uhd")):
        return "intel"
    if any(k in low for k in ("qualcomm", "adreno", "snapdragon")):
        return "qualcomm"
    return "apple" if sys.platform == "darwin" else ""


def _nvidia_cards() -> list[tuple[str, int, int]]:
    """[(name, total_mb, free_mb)] for every NVIDIA card, from the driver."""
    smi = nvidia_smi_path()
    if not smi:
        return []
    cards = []
    out = _run(
        [smi, "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits"], 15
    )
    for line in out.splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) >= 3 and parts[-2].isdigit() and parts[-1].isdigit():
            cards.append((",".join(parts[:-2]), int(parts[-2]), int(parts[-1])))
    return cards


def _nvidia_driver_loaded() -> bool:
    if Path("/proc/driver/nvidia/version").is_file() or Path("/sys/module/nvidia").is_dir():
        return True
    return any(
        _read(v).lower() == _PCI_NVIDIA for v in Path("/sys/bus/pci/devices").glob("*/vendor")
    )


def _nvidia_name_from_proc() -> str:
    for info in Path("/proc/driver/nvidia/gpus").glob("*/information"):
        for line in _read(info).splitlines():
            if line.startswith("Model:"):
                return line.split(":", 1)[1].strip()
    return ""


def _windows_cards() -> list[tuple[str, int]]:
    """[(name, total_mb)] for every adapter on Windows, any maker. The registry's 64-bit size is
    used: WMI's AdapterRAM stops at 4 GB."""
    if os.name != "nt":
        return []
    shell = shutil.which("powershell") or shutil.which("pwsh")
    if not shell:
        return []
    script = (
        "$ErrorActionPreference='SilentlyContinue';"
        "Get-CimInstance Win32_VideoController | ForEach-Object {"
        "  $n=$_.Name; $ram=0;"
        "  $k=Get-ItemProperty -Path ('HKLM:\\" + _DISPLAY_CLASS + "\\*') |"
        "    Where-Object { $_.'HardwareInformation.qwMemorySize' -and $_.DriverDesc -eq $n } |"
        "    Select-Object -First 1;"
        "  if($k){ $ram=[int64]$k.'HardwareInformation.qwMemorySize' }"
        "  elseif($_.AdapterRAM){ $ram=[int64]$_.AdapterRAM }"
        "  '{0}|{1}' -f $n, $ram }"
    )
    cards = []
    for line in _run([shell, "-NoProfile", "-Command", script], 25).splitlines():
        name, _, ram = line.rpartition("|")
        name = name.strip()
        if not name or "microsoft basic display" in name.lower():
            continue
        cards.append((name, int(ram.strip()) // MIB if ram.strip().isdigit() else 0))
    return cards


def _macos_cards() -> list[tuple[str, int]]:
    """[(name, total_mb)] on macOS. Apple's own chips report no size: the memory is the system's."""
    if sys.platform != "darwin":
        return []
    try:
        data = json.loads(_run(["system_profiler", "-json", "SPDisplaysDataType"], 30) or "{}")
    except ValueError:
        return []
    cards = []
    for item in data.get("SPDisplaysDataType") or []:
        name = str(item.get("sppci_model") or item.get("_name") or "").strip()
        if not name:
            continue
        mb = 0
        for key in ("spdisplays_vram_shared", "spdisplays_vram", "sppci_vram"):
            m = re.match(r"\s*([\d.]+)\s*(gb|mb)?", str(item.get(key) or ""), re.I)
            if m:
                mb = int(float(m.group(1)) * (1024 if (m.group(2) or "").lower() == "gb" else 1))
                break
        cards.append((name, mb))
    return cards


def _drm_devices(vendor: str) -> list[Path]:
    seen: dict[str, Path] = {}
    for vendor_file in Path("/sys/class/drm").glob("card[0-9]*/device/vendor"):
        if _read(vendor_file).lower() == vendor:
            seen.setdefault(vendor_file.parents[1].name.split("-")[0], vendor_file.parent)
    return list(seen.values())


def _pci_name(device: Path) -> str:
    if not shutil.which("lspci"):
        return ""
    try:
        address = device.resolve().name
    except OSError:
        return ""
    first = _run(["lspci", "-s", address, "-nn"], 5).strip().splitlines()[:1]
    return first[0].split(":", 2)[-1].strip() if first and ":" in first[0] else ""


def _is_intel_arc(device: Path) -> bool:
    try:
        device_id = int(_read(device / "device"), 16)
    except ValueError:
        return False
    return any(lo <= device_id <= hi for lo, hi in _INTEL_ARC_DEVICE_RANGES)


def _amd_rocm_cards() -> list[tuple[int, int]]:
    """[(total_mb, free_mb)] from rocm-smi. Its field names drift, so they are matched by word."""
    if not shutil.which("rocm-smi"):
        return []
    try:
        data = json.loads(_run(["rocm-smi", "--showmeminfo", "vram", "--json"], 5) or "{}")
    except ValueError:
        return []

    def field(info: dict[str, Any], must: tuple[str, ...], never: tuple[str, ...] = ()) -> int:
        for key, value in info.items():
            low = str(key).lower()
            if all(w in low for w in must) and not any(w in low for w in never):
                try:
                    return int(value)
                except (TypeError, ValueError):
                    continue
        return 0

    cards = []
    for info in data.values() if isinstance(data, dict) else []:
        if not isinstance(info, dict):
            continue
        total = field(info, ("vram", "total", "memory"), never=("used",))
        if total > 0:
            used = field(info, ("vram", "used", "memory"))
            cards.append((total // MIB, max(0, total - used) // MIB))
    return cards


def _amd_sysfs_cards() -> list[tuple[int, int]]:
    """[(total_mb, free_mb)] from the amdgpu driver, for cards with memory of their own."""
    cards = []
    for device in _drm_devices(_PCI_AMD):
        try:
            total = int(_read(device / "mem_info_vram_total"))
            used = int(_read(device / "mem_info_vram_used"))
        except ValueError:
            continue
        if total > 64 * MIB:  # less is an APU's reserved slice: shared memory, handled below
            cards.append((total // MIB, max(0, total - used) // MIB))
    return cards


def _windows_registry_card() -> tuple[str, int] | None:
    """An AMD or Intel Arc card on Windows: (name, total_mb) from the display-class registry."""
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _DISPLAY_CLASS) as cls:
            index = 0
            while True:
                try:
                    sub = winreg.EnumKey(cls, index)
                except OSError:
                    return None
                index += 1
                if not sub.isdigit():
                    continue
                try:
                    with winreg.OpenKey(cls, sub) as key:
                        name = str(winreg.QueryValueEx(key, "DriverDesc")[0])
                        low = name.lower()
                        if not ("amd" in low or "radeon" in low or "arc" in low):
                            continue
                        size = int(winreg.QueryValueEx(key, "HardwareInformation.qwMemorySize")[0])
                except OSError:
                    continue
                if size > 0:
                    return name, size // MIB
    except OSError:
        log.debug("display registry unreadable", exc_info=True)
    return None


# ── budgets ──────────────────────────────────────────────────────────────────


def _env_number(name: str) -> float | None:
    raw = (os.environ.get(name) or "").strip()
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def vram_reserve_mb(*, shared: bool = False) -> int:
    """Graphics memory to leave free. ELI_LEGAL_VRAM_RESERVE_MB sets it for this machine."""
    chosen = _env_number("ELI_LEGAL_VRAM_RESERVE_MB")
    if chosen is not None and chosen > 0:
        return int(chosen)
    return DEFAULT_SHARED_VRAM_RESERVE_MB if shared else DEFAULT_VRAM_RESERVE_MB


def ram_budget_fraction(hw: Hardware) -> float:
    """The share of the memory free now that a model's weights and cache may take.
    ELI_LEGAL_RAM_BUDGET_PERCENT sets it (10 to 75). Otherwise 60 percent, or 70 where the
    processor does the work on a machine of 16 GB or less, which needs it more."""
    chosen = _env_number("ELI_LEGAL_RAM_BUDGET_PERCENT")
    if chosen is None:
        cpu_bound = not hw.has_gpu or hw.gpu_integrated
        chosen = 70.0 if cpu_bound and hw.ram_gb <= 16.0 else 60.0
    elif chosen <= 1.0:
        chosen *= 100.0
    return max(0.10, min(0.75, chosen / 100.0))


def cpu_ram_budget_mb(hw: Hardware) -> int:
    return int(hw.available_ram_gb * 1024.0 * ram_budget_fraction(hw))


def recommend_threads(hw: Hardware, *, cpu_bound: bool) -> int:
    """Threads for inference, leaving the desktop one core where the processor does the work
    (or there are four or fewer), two where a graphics card does."""
    n = max(1, hw.cpu_threads)
    return max(1, n - (1 if n <= 4 or cpu_bound else 2))


def _shared_memory_budget(hw: Hardware) -> tuple[int, int]:
    """(free_mb, total_mb) for graphics that share system memory: the same share of the memory
    free now that a processor-only load may take."""
    free = int(
        max(1.0, hw.available_ram_gb) * 1024.0 * ram_budget_fraction(replace(hw, has_gpu=False))
    )
    return free, max(free, int(hw.ram_gb * 1024.0 * 0.5))


# ── the probe ────────────────────────────────────────────────────────────────

_cache: tuple[float, Hardware] | None = None
_CACHE_SECONDS = 30.0


def detect(*, force: bool = False) -> Hardware:
    """This machine as it is now. Kept for half a minute, so a screen that asks three times
    does not run nvidia-smi three times; ``force`` asks again."""
    global _cache
    now = time.monotonic()
    if not force and _cache is not None and now - _cache[0] < _CACHE_SECONDS:
        return replace(_cache[1])
    hw = _detect()
    _cache = (now, replace(hw))
    return hw


def _set_card(
    hw: Hardware,
    name: str,
    vendor: str,
    total_mb: int,
    free_mb: int,
    *,
    measured: bool,
    count: int = 1,
) -> None:
    hw.has_gpu = True
    hw.gpu_name = name + (f" ×{count}" if count > 1 else "")
    hw.gpu_vendor = vendor
    hw.gpu_count = count
    hw.total_vram_mb = int(total_mb)
    hw.free_vram_mb = int(free_mb)
    hw.vram_measured = measured


def _set_shared(hw: Hardware, name: str, vendor: str) -> None:
    free, total = _shared_memory_budget(hw)
    _set_card(hw, name, vendor, total, free, measured=False)
    hw.gpu_integrated = True


def _detect() -> Hardware:
    hw = Hardware(cpu_threads=os.cpu_count() or 1)
    total, available = _memory_bytes()
    hw.ram_gb = total / GIB
    hw.available_ram_gb = available / GIB
    hw.vulkan_loader = vulkan_loader_present()
    linux = sys.platform.startswith("linux")

    nvidia = _nvidia_cards()
    if nvidia:
        # One card's free memory is the budget: the most free. llama.cpp spreads over every
        # visible card, so a fit for the roomiest one holds.
        name, total_mb, free_mb = max(nvidia, key=lambda c: (c[2], c[1]))
        _set_card(hw, name, "nvidia", total_mb, free_mb, measured=True, count=len(nvidia))
        return hw

    if linux and _nvidia_driver_loaded():
        # The driver is loaded but cannot be asked (nvidia-smi missing, or out of step with
        # the kernel module after an update). The card is still there.
        name = _nvidia_name_from_proc()
        known = _lookup_mb(name, _NVIDIA_VRAM_MB)
        if known:
            _set_card(hw, name, "nvidia", known, int(known * 0.85), measured=False)
        else:
            hw.uncertain = True
            hw.gpu_name = name or "NVIDIA card (driver not answering)"
        return hw

    native = _windows_cards() or _macos_cards()
    if native:
        name, total_mb = max(native, key=lambda c: (_is_discrete(c[0]), c[1]))
        vendor = _vendor_of(name)
        if total_mb > 0 and not _is_integrated(name, vendor):
            # No free-memory reading here; the desktop already holds part of the card.
            _set_card(hw, name, vendor, total_mb, int(total_mb * 0.80), measured=False)
        elif _is_integrated(name, vendor) or sys.platform == "darwin":
            _set_shared(hw, name, vendor or "apple")
        else:
            hw.uncertain = True
            hw.gpu_name = name
        return hw

    amd = _amd_rocm_cards() or (_amd_sysfs_cards() if linux else [])
    if amd:
        total_mb, free_mb = max(amd, key=lambda c: (c[1], c[0]))
        devices = _drm_devices(_PCI_AMD) if linux else []
        name = (_pci_name(devices[0]) if devices else "") or "AMD graphics card"
        _set_card(hw, name, "amd", total_mb, free_mb, measured=True, count=len(amd))
        return hw

    if linux:
        for device in _drm_devices(_PCI_INTEL):
            if not _is_intel_arc(device):
                continue
            name = _pci_name(device) or "Intel Arc"
            known = _lookup_mb(name, _INTEL_ARC_VRAM_MB)
            if known:
                _set_card(hw, name, "intel", known, int(known * 0.85), measured=False)
            else:
                hw.uncertain = True
                hw.gpu_name = name
            return hw

    registry = _windows_registry_card()
    if registry:
        name, total_mb = registry
        _set_card(hw, name, _vendor_of(name), total_mb, int(total_mb * 0.85), measured=False)
        return hw

    if linux:
        for vendor_id, vendor, fallback in (
            (_PCI_INTEL, "intel", "Intel integrated graphics"),
            (_PCI_AMD, "amd", "AMD integrated graphics"),
            (_PCI_QUALCOMM, "qualcomm", "Qualcomm Adreno"),
        ):
            devices = _drm_devices(vendor_id)
            if devices:
                _set_shared(hw, _pci_name(devices[0]) or fallback, vendor)
                return hw
        if any(Path("/sys/class/drm").glob("card[0-9]*/device/vendor")):
            hw.uncertain = True
    return hw


# ── who else is using the card ───────────────────────────────────────────────


def _service_of(pid: int) -> str:
    """The system service a Linux process runs under ("ollama.service"), else ""."""
    for line in _read(Path(f"/proc/{pid}/cgroup")).splitlines():
        parts = line.split(":", 2)[-1].strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "system.slice" and parts[1].endswith(".service"):
            return parts[1]
    return ""


def vram_holders() -> list[dict[str, Any]]:
    """Other programs holding graphics memory, largest first: {pid, name, mb, service}.

    NVIDIA on any system through nvidia-smi; AMD on Linux through the kernel's per-process
    counters. Not covered: Intel and Apple graphics, and AMD on Windows."""
    found: dict[int, dict[str, Any]] = {}
    smi = nvidia_smi_path()
    if smi:
        out = _run(
            [
                smi,
                "--query-compute-apps=pid,process_name,used_memory",
                "--format=csv,noheader,nounits",
            ],
            6,
        )
        for line in out.splitlines():
            parts = [x.strip() for x in line.split(",")]
            if len(parts) < 3 or not parts[0].isdigit():
                continue
            command = ",".join(parts[1:-1]).strip()
            entry = found.setdefault(
                int(parts[0]),
                {
                    "pid": int(parts[0]),
                    "name": Path(command.split(" ")[0]).name or command,
                    "mb": None,
                },
            )
            try:
                entry["mb"] = (entry["mb"] or 0.0) + float(parts[-1])
            except ValueError:
                pass
    kfd = Path("/sys/class/kfd/kfd/proc")
    if kfd.is_dir():
        for pdir in kfd.iterdir():
            if not pdir.name.isdigit():
                continue
            used = sum(
                int(_read(f) or 0) for f in pdir.glob("vram_*") if (_read(f) or "0").isdigit()
            )
            if used > 0:
                pid = int(pdir.name)
                name = _read(Path(f"/proc/{pid}/comm"))
                found.setdefault(pid, {"pid": pid, "name": name, "mb": used / MIB})
    holders = [h for pid, h in found.items() if pid != os.getpid()]
    for holder in holders:
        holder["service"] = _service_of(holder["pid"])
    return sorted(holders, key=lambda h: -(h["mb"] or 0.0))


def describe_vram_holders(holders: list[dict[str, Any]], *, total_mb: int = 0) -> str:
    """ "llama-server (ollama.service, pid 1172557) 5146 MB": holders of at least a hundredth of
    the card, so a file manager's few megabytes are not listed."""
    shown = []
    for holder in holders:
        mb = holder.get("mb")
        if total_mb and mb is not None and mb < total_mb / 100:
            continue
        where = ", ".join(x for x in (holder.get("service") or "", f"pid {holder['pid']}") if x)
        shown.append(f"{holder['name']} ({where})" + (f" {mb:.0f} MB" if mb is not None else ""))
    return ", ".join(shown)
