"""Pure-Python icon extraction for PE (.exe), Android (.apk/.aab), and macOS (.app/.icns)."""

from __future__ import annotations

import io
import plistlib
import struct
import zipfile
from pathlib import PurePosixPath

from .abstractions import LocalPrefixFilesystem, PrefixFilesystem
from .models import IconExtractionResult, Platform

THEME_FALLBACK_ICONS = {
    Platform.WIN: "kitebridge-win",
    Platform.ANDROID: "kitebridge-android",
    Platform.MACOS: "kitebridge-macos",
    Platform.UNKNOWN: "application-x-executable",
}

_PNG_SIG = b"\x89PNG\r\n\x1a\n"
_ICNS_PNG_TYPES = (b"ic10", b"ic09", b"ic08", b"ic07", b"icp6", b"icp5", b"icp4")


def extract_pe_ico_bytes(pe_data: bytes) -> bytes | None:
    """Extract the primary RT_GROUP_ICON / RT_ICON set from a PE binary as .ico bytes."""
    if len(pe_data) < 0x40 or pe_data[:2] != b"MZ":
        return None
    e_lfanew = struct.unpack_from("<I", pe_data, 0x3C)[0]
    if e_lfanew + 24 > len(pe_data) or pe_data[e_lfanew:e_lfanew + 4] != b"PE\x00\x00":
        return None

    num_sections = struct.unpack_from("<H", pe_data, e_lfanew + 6)[0]
    opt_size = struct.unpack_from("<H", pe_data, e_lfanew + 20)[0]
    opt_off = e_lfanew + 24
    if opt_off + opt_size > len(pe_data) or opt_size < 2:
        return None

    magic = struct.unpack_from("<H", pe_data, opt_off)[0]
    if magic == 0x10B:  # PE32
        dd_off = opt_off + 96
    elif magic == 0x20B:  # PE32+
        dd_off = opt_off + 112
    else:
        return None

    # Resource DataDirectory is index 2 (offset + 16)
    if dd_off + 24 > opt_off + opt_size:
        return None
    rsrc_rva, _rsrc_size = struct.unpack_from("<II", pe_data, dd_off + 16)

    sec_table_off = opt_off + opt_size
    sections: list[tuple[int, int, int, int]] = []
    rsrc_file_base: int | None = None
    for i in range(num_sections):
        off = sec_table_off + i * 40
        if off + 40 > len(pe_data):
            break
        name = pe_data[off:off + 8].rstrip(b"\x00")
        vsize, va, raw_size, raw_ptr = struct.unpack_from("<IIII", pe_data, off + 8)
        sections.append((va, max(vsize, raw_size), raw_ptr, raw_size))
        if name == b".rsrc" and rsrc_file_base is None:
            rsrc_file_base = raw_ptr
            if rsrc_rva == 0:
                rsrc_rva = va

    if rsrc_rva == 0:
        return None

    def rva_to_off(rva: int) -> int | None:
        for va, span, raw_ptr, _raw_size in sections:
            if va <= rva < va + span:
                return raw_ptr + (rva - va)
        return None

    rsrc_base = rva_to_off(rsrc_rva) or rsrc_file_base
    if rsrc_base is None or rsrc_base + 16 > len(pe_data):
        return None

    def read_dir(dir_off: int) -> list[tuple[int, int, bool]]:
        if dir_off + 16 > len(pe_data):
            return []
        num_named, num_id = struct.unpack_from("<HH", pe_data, dir_off + 12)
        total = num_named + num_id
        entries: list[tuple[int, int, bool]] = []
        pos = dir_off + 16
        for _ in range(total):
            if pos + 8 > len(pe_data):
                break
            ident, val = struct.unpack_from("<II", pe_data, pos)
            is_sub = bool(val & 0x80000000)
            target = val & 0x7FFFFFFF
            entries.append((ident, target, is_sub))
            pos += 8
        return entries

    def read_data_entry(entry_off: int) -> bytes | None:
        abs_off = rsrc_base + entry_off
        if abs_off + 16 > len(pe_data):
            return None
        data_rva, size, _cp, _res = struct.unpack_from("<IIII", pe_data, abs_off)
        file_off = rva_to_off(data_rva)
        if file_off is None:
            # Fallback for simplified synthetic RVA == offset relative to rsrc_base
            file_off = data_rva
        if file_off < 0 or file_off + size > len(pe_data):
            return None
        return pe_data[file_off:file_off + size]

    rt_icons: dict[int, bytes] = {}
    group_bytes: bytes | None = None

    for type_id, type_off, is_sub in read_dir(rsrc_base):
        if not is_sub:
            continue
        if type_id == 3:  # RT_ICON
            for icon_id, name_off, sub2 in read_dir(rsrc_base + type_off):
                if not sub2:
                    continue
                for _lang_id, data_off, sub3 in read_dir(rsrc_base + name_off):
                    if not sub3:
                        blob = read_data_entry(data_off)
                        if blob:
                            rt_icons[icon_id] = blob
                            break
        elif type_id == 14:  # RT_GROUP_ICON
            for _grp_id, name_off, sub2 in read_dir(rsrc_base + type_off):
                if not sub2:
                    continue
                for _lang_id, data_off, sub3 in read_dir(rsrc_base + name_off):
                    if not sub3:
                        blob = read_data_entry(data_off)
                        if blob:
                            group_bytes = blob
                            break
                if group_bytes:
                    break

    if not group_bytes or len(group_bytes) < 6:
        if rt_icons:
            first_blob = next(iter(rt_icons.values()))
            header = struct.pack("<HHH", 0, 1, 1)
            entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(first_blob), 22)
            return header + entry + first_blob
        return None

    _res, ico_type, count = struct.unpack_from("<HHH", group_bytes, 0)
    if ico_type != 1 or count == 0:
        return None

    entries_out: list[tuple[bytes, bytes]] = []
    pos = 6
    for _ in range(count):
        if pos + 14 > len(group_bytes):
            break
        w, h, colors, reserved, planes, bpp, bytes_in_res, n_id = struct.unpack_from(
            "<BBBBHHIH", group_bytes, pos
        )
        pos += 14
        img_blob = rt_icons.get(n_id)
        if not img_blob:
            continue
        entries_out.append(
            (
                struct.pack("<BBBBHHII", w, h, colors, reserved, planes, bpp, len(img_blob), 0),
                img_blob,
            )
        )

    if not entries_out:
        return None

    ico_header = struct.pack("<HHH", 0, 1, len(entries_out))
    data_offset = 6 + 16 * len(entries_out)
    dir_chunks: list[bytes] = []
    blob_chunks: list[bytes] = []
    for raw_entry, blob in entries_out:
        w, h, colors, reserved, planes, bpp, size, _ = struct.unpack("<BBBBHHII", raw_entry)
        dir_chunks.append(struct.pack("<BBBBHHII", w, h, colors, reserved, planes, bpp, size, data_offset))
        blob_chunks.append(blob)
        data_offset += len(blob)
    return ico_header + b"".join(dir_chunks) + b"".join(blob_chunks)


def extract_icns_png_bytes(icns_data: bytes) -> bytes | None:
    """Extract the highest-resolution PNG payload from an Apple .icns file."""
    if len(icns_data) < 8 or icns_data[:4] != b"icns":
        return None
    total_len = struct.unpack_from(">I", icns_data, 4)[0]
    limit = min(total_len, len(icns_data))
    pos = 8
    found: dict[bytes, bytes] = {}
    while pos + 8 <= limit:
        chunk_type = icns_data[pos:pos + 4]
        chunk_size = struct.unpack_from(">I", icns_data, pos + 4)[0]
        if chunk_size < 8 or pos + chunk_size > limit:
            break
        payload = icns_data[pos + 8:pos + chunk_size]
        if payload.startswith(_PNG_SIG):
            found[chunk_type] = payload
        pos += chunk_size

    for preferred in _ICNS_PNG_TYPES:
        if preferred in found:
            return found[preferred]
    if found:
        return next(iter(found.values()))
    return None


def extract_apk_icon_bytes(archive_bytes: bytes) -> bytes | None:
    """Extract highest-DPI ic_launcher PNG from an .apk or .aab ZIP archive."""
    dpi_priority = ("xxxhdpi", "xxhdpi", "xhdpi", "hdpi", "mdpi", "anydpi")
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as zf:
            png_names = [n for n in zf.namelist() if n.lower().endswith(".png")]
            launchers = [n for n in png_names if "ic_launcher" in n.lower()]
            candidates = launchers or [n for n in png_names if "/res/" in f"/{n}" or n.startswith("res/")]
            if not candidates:
                return None

            def score(name: str) -> tuple[int, int]:
                low = name.lower()
                dpi_score = len(dpi_priority)
                for idx, tag in enumerate(dpi_priority):
                    if tag in low:
                        dpi_score = idx
                        break
                round_penalty = 1 if "round" in low else 0
                return (dpi_score, round_penalty)

            candidates.sort(key=score)
            return zf.read(candidates[0])
    except zipfile.BadZipFile:
        return None


def extract_icon(
    source_path: str,
    platform: Platform,
    out_dir: str,
    slug: str,
    *,
    fs: PrefixFilesystem | None = None,
) -> IconExtractionResult:
    """Extract platform icon or fall back to theme icon name."""
    filesystem = fs or LocalPrefixFilesystem()
    norm_out = out_dir.replace("\\", "/").rstrip("/")
    filesystem.mkdir(norm_out, parents=True)

    if platform == Platform.WIN and filesystem.exists(source_path):
        raw = filesystem.read_bytes(source_path)
        ico = extract_pe_ico_bytes(raw)
        if ico:
            dest = f"{norm_out}/{slug}.ico"
            filesystem.write_bytes(dest, ico)
            return IconExtractionResult(icon_value=dest, extracted=True, format="ico", source_path=source_path)

    if platform == Platform.ANDROID and filesystem.exists(source_path):
        raw = filesystem.read_bytes(source_path)
        png = extract_apk_icon_bytes(raw)
        if png:
            dest = f"{norm_out}/{slug}.png"
            filesystem.write_bytes(dest, png)
            return IconExtractionResult(icon_value=dest, extracted=True, format="png", source_path=source_path)

    if platform == Platform.MACOS:
        norm = source_path.replace("\\", "/").rstrip("/")
        icns_candidate: str | None = None
        if norm.lower().endswith(".icns") and filesystem.exists(norm):
            icns_candidate = norm
        elif norm.lower().endswith(".app") and filesystem.exists(f"{norm}/Contents/Info.plist"):
            try:
                plist = plistlib.loads(filesystem.read_bytes(f"{norm}/Contents/Info.plist"))
                icon_file = plist.get("CFBundleIconFile") or plist.get("CFBundleIconName")
                if isinstance(icon_file, str) and icon_file.strip():
                    fname = icon_file.strip()
                    if not fname.lower().endswith(".icns"):
                        fname = f"{fname}.icns"
                    cand = f"{norm}/Contents/Resources/{fname}"
                    if filesystem.exists(cand):
                        icns_candidate = cand
            except Exception:
                icns_candidate = None
        if icns_candidate:
            raw_icns = filesystem.read_bytes(icns_candidate)
            png = extract_icns_png_bytes(raw_icns)
            if png:
                dest = f"{norm_out}/{slug}.png"
                filesystem.write_bytes(dest, png)
                return IconExtractionResult(icon_value=dest, extracted=True, format="png", source_path=icns_candidate)
            dest = f"{norm_out}/{slug}.icns"
            filesystem.write_bytes(dest, raw_icns)
            return IconExtractionResult(icon_value=dest, extracted=True, format="icns", source_path=icns_candidate)

    return IconExtractionResult(
        icon_value=THEME_FALLBACK_ICONS.get(platform, "application-x-executable"),
        extracted=False,
        format="theme",
        source_path=source_path,
    )
