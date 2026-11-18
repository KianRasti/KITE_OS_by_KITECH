"""Pytest bootstrap and shared synthetic hardware/binary fixtures for KiteBridge."""

from __future__ import annotations

import io
import json
import plistlib
import struct
import sys
import zipfile
from pathlib import Path

import pytest

KITE_BRIDGE_ROOT = Path(__file__).resolve().parents[1]
if str(KITE_BRIDGE_ROOT) not in sys.path:
    sys.path.insert(0, str(KITE_BRIDGE_ROOT))


def make_hw_profile_json(tier: str = "8G", power: str = "AC") -> str:
    if tier == "4G":
        data = {
            "schema_version": 1,
            "ram_mb": 4096,
            "memory": {
                "tier": "4G",
                "zram_percent": 150,
                "zram_size_mb": 6144,
                "zram_algo": "lz4",
                "idle_budget_mb": 220,
                "sysctl": {"vm.swappiness": 180, "vm.page-cluster": 0, "vm.watermark_boost_factor": 0},
            },
            "power": {"source": power, "epp": "balance_power", "snd_hda_intel_power_save": 1, "iwlwifi_power_save": True},
            "blur": {"tier": "static", "enabled": False, "size": 0, "passes": 0, "xray": False},
            "storage": [{"device": "sda", "rotational": 0, "scheduler": "kyber"}],
            "subsystems": {
                "wine": {"dxvk_version": "1.10.3", "ntsync": True, "prewarm": False},
                "waydroid": {"idle_policy": "freeze_then_teardown", "teardown_after_sec": 300, "prewarm": False},
                "osx_kvm": {"hugepages_on_demand": False},
            },
        }
    elif tier == "16G":
        data = {
            "schema_version": 1,
            "ram_mb": 16384,
            "memory": {
                "tier": "16G",
                "zram_percent": 50,
                "zram_size_mb": 8192,
                "zram_algo": "zstd",
                "idle_budget_mb": 600,
                "sysctl": {"vm.swappiness": 100, "vm.page-cluster": 0, "vm.dirty_ratio": 10},
            },
            "power": {"source": power, "epp": "balance_performance", "snd_hda_intel_power_save": 0, "iwlwifi_power_save": False},
            "blur": {"tier": "kawase_full", "enabled": True, "size": 6, "passes": 2, "xray": True},
            "storage": [{"device": "sda", "rotational": 0, "scheduler": "kyber"}],
            "subsystems": {
                "wine": {"dxvk_version": "1.10.3", "ntsync": True, "prewarm": True},
                "waydroid": {"idle_policy": "prewarmed", "teardown_after_sec": None, "prewarm": True},
                "osx_kvm": {"hugepages_on_demand": True},
            },
        }
    else:
        data = {
            "schema_version": 1,
            "ram_mb": 8192,
            "memory": {
                "tier": "8G",
                "zram_percent": 100,
                "zram_size_mb": 8192,
                "zram_algo": "zstd",
                "idle_budget_mb": 350,
                "sysctl": {"vm.swappiness": 150, "vm.page-cluster": 0, "vm.vfs_cache_pressure": 75},
            },
            "power": {"source": power, "epp": "balance_performance", "snd_hda_intel_power_save": 0, "iwlwifi_power_save": False},
            "blur": {"tier": "kawase_2pass", "enabled": True, "size": 6, "passes": 2, "xray": True},
            "storage": [{"device": "sda", "rotational": 0, "scheduler": "kyber"}],
            "subsystems": {
                "wine": {"dxvk_version": "1.10.3", "ntsync": True, "prewarm": False},
                "waydroid": {"idle_policy": "cgroup_freeze", "teardown_after_sec": None, "prewarm": False},
                "osx_kvm": {"hugepages_on_demand": False},
            },
        }
    return json.dumps(data, indent=2)


def build_synthetic_pe_with_icon() -> bytes:
    """Construct a minimal valid PE32 executable containing a .rsrc RT_GROUP_ICON + RT_ICON PNG."""
    png_payload = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00" * 17 + b"IEND\xaeB`\x82"
    grp_payload = struct.pack("<HHH", 0, 1, 1) + struct.pack(
        "<BBBBHHIH", 16, 16, 0, 0, 1, 32, len(png_payload), 1
    )

    # Layout:
    # 0x00..0x80: DOS header (e_lfanew = 0x80)
    # 0x80..0x178: PE sig (4) + COFF (20) + OptionalHeader32 (224) = 248 bytes (0x80..0x178)
    # 0x178..0x1A0: 1 section header (.rsrc, VA=0x2000, RawPtr=0x200)
    # 0x200..: .rsrc section
    rsrc_va = 0x2000
    rsrc_raw = 0x200

    # Inside .rsrc (relative offsets):
    # 0x000: Root dir (16 + 2*8 = 32 bytes) -> type 3 (RT_ICON) -> off 0x20, type 14 (RT_GROUP_ICON) -> off 0x50
    # 0x020: Type 3 dir (16 + 8 = 24 bytes) -> id 1 -> off 0x38
    # 0x038: Name 1 dir (16 + 8 = 24 bytes) -> lang 1033 -> data entry off 0x80
    # 0x050: Type 14 dir (16 + 8 = 24 bytes) -> id 1 -> off 0x68
    # 0x068: Name 1 dir (16 + 8 = 24 bytes) -> lang 1033 -> data entry off 0x90
    # 0x080: RT_ICON data entry (16 bytes) -> data at rsrc_rel 0xA0
    # 0x090: RT_GROUP_ICON data entry (16 bytes) -> data at rsrc_rel 0xA0 + len(png_payload)
    def dir_hdr(num_id: int) -> bytes:
        return struct.pack("<IIHHHH", 0, 0, 0, 0, 0, num_id)

    def dir_entry(ident: int, off: int, is_sub: bool) -> bytes:
        return struct.pack("<II", ident, off | (0x80000000 if is_sub else 0))

    rsrc = bytearray()
    rsrc.extend(dir_hdr(2))
    rsrc.extend(dir_entry(3, 0x20, True))
    rsrc.extend(dir_entry(14, 0x50, True))

    rsrc.extend(dir_hdr(1))
    rsrc.extend(dir_entry(1, 0x38, True))

    rsrc.extend(dir_hdr(1))
    rsrc.extend(dir_entry(1033, 0x80, False))

    rsrc.extend(dir_hdr(1))
    rsrc.extend(dir_entry(1, 0x68, True))

    rsrc.extend(dir_hdr(1))
    rsrc.extend(dir_entry(1033, 0x90, False))

    png_rel = 0xA0
    grp_rel = png_rel + len(png_payload)
    rsrc.extend(struct.pack("<IIII", rsrc_va + png_rel, len(png_payload), 0, 0))
    rsrc.extend(struct.pack("<IIII", rsrc_va + grp_rel, len(grp_payload), 0, 0))
    rsrc.extend(png_payload)
    rsrc.extend(grp_payload)

    buf = bytearray(rsrc_raw + len(rsrc))
    buf[0:2] = b"MZ"
    struct.pack_into("<I", buf, 0x3C, 0x80)
    buf[0x80:0x84] = b"PE\x00\x00"
    # COFF: Machine=0x14c, NumSections=1, SizeOfOptionalHeader=224
    struct.pack_into("<HHIIIHH", buf, 0x84, 0x14C, 1, 0, 0, 0, 224, 0x0102)
    # OptionalHeader32 magic=0x10B, DataDirectory[2] at opt_off + 96 + 16
    opt_off = 0x84 + 20
    struct.pack_into("<H", buf, opt_off, 0x10B)
    struct.pack_into("<II", buf, opt_off + 96 + 16, rsrc_va, len(rsrc))
    # Section header
    sec_off = opt_off + 224
    buf[sec_off:sec_off + 8] = b".rsrc\x00\x00\x00"
    struct.pack_into("<IIII", buf, sec_off + 8, len(rsrc), rsrc_va, len(rsrc), rsrc_raw)
    buf[rsrc_raw:] = rsrc
    return bytes(buf)


def build_synthetic_axml(package_name: str) -> bytes:
    """Build a minimal valid Android binary XML (AXML) header + UTF-8 string pool."""
    strings = ["manifest", "package", package_name]
    pool_data = bytearray()
    offsets: list[int] = []
    for s in strings:
        offsets.append(len(pool_data))
        encoded = s.encode("utf-8")
        pool_data.append(len(s))
        pool_data.append(len(encoded))
        pool_data.extend(encoded)
        pool_data.append(0)
    while len(pool_data) % 4 != 0:
        pool_data.append(0)

    header_size = 28
    strings_start = header_size + 4 * len(strings)
    chunk_size = strings_start + len(pool_data)
    sp_header = struct.pack(
        "<HHIIIIII",
        0x0001,
        header_size,
        chunk_size,
        len(strings),
        0,
        1 << 8,  # UTF8_FLAG
        strings_start,
        0,
    )
    offset_bytes = b"".join(struct.pack("<I", off) for off in offsets)
    total_size = 8 + chunk_size
    xml_header = struct.pack("<HHI", 0x0003, 8, total_size)
    return xml_header + sp_header + offset_bytes + bytes(pool_data)


def build_synthetic_apk(package_name: str = "org.kiteos.demo") -> bytes:
    buf = io.BytesIO()
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("AndroidManifest.xml", build_synthetic_axml(package_name))
        zf.writestr("lib/arm64-v8a/libdemo.so", b"\x7fELF")
        zf.writestr("res/mipmap-xxhdpi/ic_launcher.png", png)
        zf.writestr("res/mipmap-hdpi/ic_launcher.png", png[:12])
    return buf.getvalue()


def build_synthetic_aab(package_name: str = "org.kiteos.bundle") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("BundleConfig.pb", b"\x08\x01")
        zf.writestr("base/manifest/AndroidManifest.xml", build_synthetic_axml(package_name))
        zf.writestr("base/lib/armeabi-v7a/libapp.so", b"\x7fELF")
    return buf.getvalue()


def build_synthetic_icns() -> bytes:
    png = b"\x89PNG\r\n\x1a\n" + b"ICNS_PNG_DATA"
    chunk = b"ic08" + struct.pack(">I", 8 + len(png)) + png
    return b"icns" + struct.pack(">I", 8 + len(chunk)) + chunk


def build_synthetic_lnk(target_win: str = r"C:\Program Files\Demo\demo.exe", args: str = "--safe", workdir: str = r"C:\Program Files\Demo") -> bytes:
    """Build a valid MS-SHLLINK (.lnk) payload with LinkInfo + Unicode StringData."""
    clsid = bytes.fromhex("0114020000000000c000000000000046")
    # Flags: HasLinkInfo (0x02) | HasWorkingDir (0x10) | HasArguments (0x20) | IsUnicode (0x80)
    flags = 0x02 | 0x10 | 0x20 | 0x80
    header = bytearray(76)
    struct.pack_into("<I", header, 0, 0x4C)
    header[4:20] = clsid
    struct.pack_into("<I", header, 20, flags)

    target_bytes = target_win.encode("cp1252") + b"\x00"
    common_bytes = b"\x00"
    # LinkInfo header (28 bytes)
    local_base_off = 28
    common_off = local_base_off + len(target_bytes)
    info_size = common_off + len(common_bytes)
    link_info = struct.pack("<IIIIIII", info_size, 28, 0x01, 0, local_base_off, 0, common_off) + target_bytes + common_bytes

    def str_data(text: str) -> bytes:
        return struct.pack("<H", len(text)) + text.encode("utf-16le")

    return bytes(header) + link_info + str_data(workdir) + str_data(args)


@pytest.fixture
def hw_profile_8g_json() -> str:
    return make_hw_profile_json("8G", "AC")
