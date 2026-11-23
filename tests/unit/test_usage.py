"""Processor, memory and graphics use: read on whatever this machine is (Linux, Windows or macOS;
the CI runs all three), and read correctly from the answers every other kind of machine gives:
NVIDIA, AMD, Intel, Apple, Qualcomm, Arm boards; own memory, shared and unified memory; any name."""

from __future__ import annotations

import os
import plistlib
import sys
import time
from pathlib import Path

import pytest

from eli_legal.adapters.local import usage
from eli_legal.adapters.local.usage import CardUse, Usage, UsageMeter

GB = 1024**3


# ── this machine, whatever it is ─────────────────────────────────────────────


def test_this_machine_is_read_without_error_and_what_it_cannot_say_is_left_out():
    meter = UsageMeter()
    time.sleep(0.5)
    reading = meter.read()
    assert reading.cpus >= 1
    if sys.platform.startswith(("linux", "win32", "darwin")):
        assert reading.ram_total > 0 and 0 <= reading.ram_used <= reading.ram_total
        assert reading.cpu_percent is not None and 0 <= reading.cpu_percent <= 100
        assert reading.app_ram > 0, "ELI Legal's own memory is known on all three"
    for card in reading.cards:
        assert card.name.strip()
        assert card.busy_percent is None or 0 <= card.busy_percent <= 100
        if card.used_mb is not None and card.total_mb:
            assert card.used_mb <= card.total_mb * 1.05
    line, lines = usage.summary(reading), usage.details(reading)
    assert line and "None" not in line and "None" not in lines


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS's own kernel calls")
def test_on_a_mac_the_kernel_gives_processor_ticks_and_this_process_memory_exactly():
    ticks = usage._macos_ticks()
    assert ticks is not None and 0 < ticks[0] <= ticks[1]
    ram, peak = usage._app_ram()
    assert ram > 10 * 1024 * 1024 and not peak, "resident now, not only the peak"
    assert isinstance(usage._macos_cards(), list)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows' own graphics interfaces")
def test_on_windows_dxgi_and_the_performance_counters_answer_without_error():
    adapters = usage._windows_adapters()  # a runner without a graphics card has none but software
    assert all(a["name"] and a["luid"].startswith("luid_0x") for a in adapters)
    counters = usage._WindowsCounters()
    time.sleep(0.3)
    assert isinstance(counters.read(), dict)
    assert isinstance(usage._windows_cards(counters), list)
    assert usage._windows_times() is not None


# ── NVIDIA's tool, on any system ─────────────────────────────────────────────


def test_nvidia_cards_with_their_own_memory_and_with_one_memory_shared_with_the_processor():
    out = (
        "NVIDIA GeForce RTX 2060 SUPER, 8192, 1141, 2, 32\n"
        "NVIDIA RTX A6000, Ada, 49140, 20000, 97, 71\n"  # a comma in the name
        "NVIDIA GB10, [N/A], [N/A], 5, 40\n"  # DGX Spark: unified memory
        "NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver.\n"
    )
    first, second, unified = usage._nvidia_from(out)
    assert first == CardUse("NVIDIA GeForce RTX 2060 SUPER", "nvidia", False, 8192, 1141, 2, 32)
    assert second.name == "NVIDIA RTX A6000, Ada" and second.busy_percent == 97
    assert unified.shared and unified.total_mb is None and unified.busy_percent == 5


# ── Linux: the kernel drivers' own files ─────────────────────────────────────


def _device(root: Path, card: str, address: str, driver: str, files: dict[str, str]) -> Path:
    device = root / "sys/devices" / address
    device.mkdir(parents=True)
    drivers = root / "sys/bus/drivers" / driver
    drivers.mkdir(parents=True, exist_ok=True)
    (device / "driver").symlink_to(drivers)
    for name, text in files.items():
        path = device / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    folder = root / "sys/class/drm" / card
    folder.mkdir(parents=True)
    (folder / "device").symlink_to(device)
    return folder


@pytest.fixture
def machine(tmp_path, monkeypatch):
    monkeypatch.setattr(usage, "_SYS", tmp_path / "sys")
    monkeypatch.setattr(usage, "_PROC", tmp_path / "proc")
    monkeypatch.setattr(usage, "_pci_name", lambda address: "")
    return tmp_path


@pytest.mark.skipif(os.name == "nt", reason="made-up Linux device folders use symbolic links")
def test_linux_amd_apu_and_card_intel_integrated_arm_board_and_a_driver_without_its_tool(machine):
    _device(machine, "card0", "0000:c5:00.0", "amdgpu", {
        "vendor": "0x1002", "mem_info_vram_total": str(32 * 1024**2),  # APU: a small carve-out
        "mem_info_vram_used": str(20 * 1024**2), "mem_info_gtt_total": str(16 * GB),
        "mem_info_gtt_used": str(3 * GB), "gpu_busy_percent": "37",
    })  # fmt: skip
    _device(machine, "card1", "0000:03:00.0", "amdgpu", {
        "vendor": "0x1002", "mem_info_vram_total": str(16 * GB),
        "mem_info_vram_used": str(4 * GB), "gpu_busy_percent": "90",
        "hwmon/hwmon3/temp1_input": "61000",
    })  # fmt: skip
    intel = _device(machine, "card2", "0000:00:02.0", "i915", {"vendor": "0x8086"})
    (intel / "gt_act_freq_mhz").write_text("450")
    (intel / "gt_max_freq_mhz").write_text("1300")
    _device(machine, "card3", "fb000000.gpu", "panfrost", {
        "of_node/compatible": "rockchip,rk3588-mali\0arm,mali-valhall-csf\0",
        "devfreq/fb000000.gpu/load": "45@800000000Hz",
    })  # fmt: skip
    _device(machine, "card4", "0000:01:00.0", "nvidia", {"vendor": "0x10de"})
    (machine / "sys/class/drm/card0-DP-1").mkdir()  # a connector, not a device

    apu, card, igpu, board, nvidia = usage._linux_cards(nvidia_done=False)
    assert apu.vendor == "amd" and apu.shared and apu.used_mb == 3072 and apu.total_mb == 16384
    assert apu.busy_percent == 37
    assert not card.shared and (card.used_mb, card.total_mb, card.temp_c) == (4096, 16384, 61)
    assert igpu.vendor == "intel" and igpu.shared and igpu.note == "running at 450 of 1300 MHz"
    assert board.vendor == "arm" and board.shared and board.busy_percent == 45
    assert board.name == "rockchip,rk3588-mali"
    assert nvidia.vendor == "nvidia" and nvidia.used_mb is None, "named; nothing invented"
    assert all(c.vendor != "nvidia" for c in usage._linux_cards(nvidia_done=True))


@pytest.mark.skipif(os.name == "nt", reason="made-up Linux device folders")
def test_a_jetson_and_a_snapdragon_say_how_busy_they_are_and_share_the_memory(machine):
    (machine / "sys/devices/gpu.0").mkdir(parents=True)
    (machine / "sys/devices/gpu.0/load").write_text("523\n")
    (machine / "proc/device-tree").mkdir(parents=True)
    (machine / "proc/device-tree/model").write_text("NVIDIA Jetson Orin Nano Developer Kit\0")
    kgsl = machine / "sys/class/kgsl/kgsl-3d0"
    kgsl.mkdir(parents=True)
    (kgsl / "gpu_busy_percentage").write_text("12 %")
    (kgsl / "gpu_model").write_text("Adreno740v2")
    jetson, adreno = usage._linux_cards(nvidia_done=False)
    assert jetson.name == "NVIDIA Jetson Orin Nano Developer Kit GPU"
    assert jetson.shared and jetson.busy_percent == 52
    assert adreno == CardUse("Adreno740v2", "qualcomm", shared=True, busy_percent=12)


# ── macOS: the IOAccelerator registry ────────────────────────────────────────


def test_macs_apple_silicon_unified_memory_intel_graphics_and_an_amd_card():
    answer = plistlib.dumps([
        {"IOClass": "AGXAcceleratorG15X", "model": "Apple M3 Max",
         "PerformanceStatistics": {"Device Utilization %": 23, "In use system memory": 3 * GB,
                                   "Alloc system memory": 5 * GB}},
        {"IOClass": "AMDRadeonX6000_AMDNavi14GraphicsAccelerator",
         "model": b"AMD Radeon Pro 5500M\x00",
         "PerformanceStatistics": {"vramFreeBytes": 6 * GB, "vramUsedBytes": 2 * GB,
                                   "GPU Activity(%)": 5, "Temperature(C)": 48}},
        {"IOClass": "IntelAccelerator", "model": "Intel UHD Graphics 630",
         "PerformanceStatistics": {"Device Utilization %": 1}},
    ])  # fmt: skip
    apple, amd, intel = usage._macos_cards_from(plistlib.loads(answer))
    assert apple == CardUse("Apple M3 Max", "apple", shared=True, used_mb=3072, busy_percent=23)
    assert amd.name == "AMD Radeon Pro 5500M" and amd.vendor == "amd" and not amd.shared
    assert (amd.used_mb, amd.total_mb, amd.busy_percent, amd.temp_c) == (2048, 8192, 5, 48)
    assert intel.vendor == "intel" and intel.shared and intel.used_mb is None


# ── Windows: its performance counters, by adapter ────────────────────────────


def test_windows_counters_are_gathered_by_adapter_whatever_the_processes_or_engines():
    a, b = "luid_0x00000000_0x0000c5e5", "luid_0x00000000_0x0001a2b3"
    raw = {
        "busy": {
            "pid_1200_luid_0x00000000_0x0000C5E5_phys_0_eng_0_engtype_3D": 30.0,
            "pid_88_luid_0x00000000_0x0000C5E5_phys_0_eng_0_engtype_3D": 25.0,
            "pid_88_luid_0x00000000_0x0000C5E5_phys_0_eng_3_engtype_VideoDecode": 70.0,
            "pid_7_luid_0x00000000_0x0001A2B3_phys_0_eng_0_engtype_3D": 4.0,
            "pid_9_luid_0x00000000_0x0001A2B3_phys_0_eng_0_engtype_3D": 99.0,
            "pid_2_luid_0x00000000_0x0001A2B3_phys_0_eng_0_engtype_3D": 50.0,
        },
        "own": {"luid_0x00000000_0x0000C5E5_phys_0": 2.0 * GB},
        "shared": {"luid_0x00000000_0x0001A2B3_phys_0": 1.5 * GB},
    }
    out = usage._by_adapter(raw)
    assert out[a] == {"own": 2.0 * GB, "busy": 70.0}, "the busiest engine, summed over processes"
    assert out[b] == {"shared": 1.5 * GB, "busy": 100.0}, "never past 100%"


# ── in words ─────────────────────────────────────────────────────────────────


def test_shared_and_unified_memory_are_named_as_such_and_unknowns_are_not_shown():
    reading = Usage(
        cpu_percent=12.0, app_cpu_percent=3.0, ram_total=64 * GB, ram_used=20 * GB,
        app_ram=900 * 1024**2, unified=True,
        cards=[
            CardUse("Apple M3 Max", "apple", shared=True, used_mb=3072, busy_percent=23),
            CardUse("Intel Iris Xe", "intel", shared=True),
            CardUse("NVIDIA RTX 4090", "nvidia", total_mb=24564, used_mb=1024),
        ],
    )  # fmt: skip
    line = usage.summary(reading)
    assert line.startswith("CPU 12% (ELI Legal 3%)  ·  Unified memory 20.0 of 64.0 GB")
    assert "(ELI Legal 900 MB)" in line
    assert "GPU 1 23%, 3.0 GB shared" in line and "GPU 2 shares the system memory" in line
    assert "GPU 3 1.0 of 24.0 GB" in line
    text = usage.details(reading)
    assert "Unified memory (processor and graphics share it)" in text
    assert "Graphics 3: NVIDIA RTX 4090: 1024 of 24564 MB in use" in text
