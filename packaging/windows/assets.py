"""Official BitChat Windows branding asset pipeline and version metadata generator.

Sources official BitChat vector (SVG) and raster (PNG) branding assets from
`D:\\BitChat Logo_SVG` (and mirrors them into `packaging/windows/assets/`) to
produce the multi-resolution Windows application icon (`bitchat.ico`), Inno Setup
wizard bitmaps (`wizard-large.bmp`, `wizard-small.bmp`), and Windows executable
version resource (`version_info.txt`) while preserving exact proportions,
transparency, and brand colors (#071826 dark navy and #22D3EE cyan).
"""

from __future__ import annotations

import math
import re
import shutil
import struct
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

OFFICIAL_ASSET_SOURCE_DIR = Path(r"D:\BitChat Logo_SVG")
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
VERSION_INFO_PATH = Path(__file__).resolve().parent / "version_info.txt"
FRAMED_ICON_SVG_NAME = "Bitchat-Icon-Framed.svg"
ICO_SIZES: tuple[int, ...] = (16, 24, 32, 48, 64, 128, 256)

# Official BitChat brand colors from Bitchat-Icon-Framed.svg / bitchat-icon-32.svg
BRAND_NAVY = (7, 24, 38)  # #071826
BRAND_NAVY_DEEP = (4, 15, 25)  # #040F19
BRAND_CYAN = (34, 211, 238)  # #22D3EE
WHITE = (255, 255, 255)

OFFICIAL_ASSET_FILES = (
    FRAMED_ICON_SVG_NAME,
    "bitchat-icon-16.png",
    "bitchat-icon-32.svg",
    "bitchat-icon-48.svg",
    "bitchat-symbol-dark.png",
    "bitchat-symbol-light.png",
    "bitchat-symbol-black.png",
    "bitchat-symbol-white.png",
    "bitchat-wordmark-dark.png",
    "bitchat-wordmark-light.png",
    "bitchat-wordmark-black.png",
    "bitchat-wordmark-white.png",
)


def sync_official_assets() -> Path:
    """Copy official branding assets from D:\\BitChat Logo_SVG if present."""
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    if OFFICIAL_ASSET_SOURCE_DIR.is_dir():
        for filename in OFFICIAL_ASSET_FILES:
            src = OFFICIAL_ASSET_SOURCE_DIR / filename
            if src.is_file():
                dst = ASSETS_DIR / filename
                if not dst.is_file() or src.read_bytes() != dst.read_bytes():
                    shutil.copy2(src, dst)
    return ASSETS_DIR


def _paeth_predictor(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def decode_png_rgba(png_bytes: bytes) -> tuple[int, int, list[bytearray]]:
    """Decode an 8-bit RGBA (color_type=6) PNG into (width, height, rows)."""
    if png_bytes[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Invalid PNG signature")

    pos = 8
    width = height = 0
    bit_depth = color_type = 0
    idat_chunks: list[bytes] = []

    while pos < len(png_bytes):
        length = struct.unpack(">I", png_bytes[pos : pos + 4])[0]
        chunk_type = png_bytes[pos + 4 : pos + 8]
        chunk_data = png_bytes[pos + 8 : pos + 8 + length]
        pos += 12 + length

        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, _, _, _ = struct.unpack(
                ">IIBBBBB", chunk_data
            )
            if bit_depth != 8 or color_type != 6:
                raise ValueError(
                    f"Unsupported PNG format: depth={bit_depth}, type={color_type}"
                )
        elif chunk_type == b"IDAT":
            idat_chunks.append(chunk_data)
        elif chunk_type == b"IEND":
            break

    raw = zlib.decompress(b"".join(idat_chunks))
    bpp = 4
    stride = width * bpp
    rows: list[bytearray] = []
    offset = 0

    for y in range(height):
        filter_type = raw[offset]
        offset += 1
        scanline = bytearray(raw[offset : offset + stride])
        offset += stride
        prev = rows[y - 1] if y > 0 else bytearray(stride)

        if filter_type == 1:  # Sub
            for i in range(bpp, stride):
                scanline[i] = (scanline[i] + scanline[i - bpp]) & 0xFF
        elif filter_type == 2:  # Up
            for i in range(stride):
                scanline[i] = (scanline[i] + prev[i]) & 0xFF
        elif filter_type == 3:  # Average
            for i in range(stride):
                left = scanline[i - bpp] if i >= bpp else 0
                up = prev[i]
                scanline[i] = (scanline[i] + ((left + up) >> 1)) & 0xFF
        elif filter_type == 4:  # Paeth
            for i in range(stride):
                left = scanline[i - bpp] if i >= bpp else 0
                up = prev[i]
                up_left = prev[i - bpp] if i >= bpp else 0
                scanline[i] = (scanline[i] + _paeth_predictor(left, up, up_left)) & 0xFF

        rows.append(scanline)

    return width, height, rows


def encode_png_rgba(
    width: int, height: int, rgba_rows: Sequence[bytes | bytearray]
) -> bytes:
    """Encode RGBA scanlines into a standard PNG image."""
    raw = b"".join(b"\x00" + bytes(row) for row in rgba_rows)
    compressed = zlib.compress(raw, level=9)

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )


def _resample_rgba_into_canvas(
    src_w: int,
    src_h: int,
    src_rows: list[bytearray],
    canvas_w: int,
    canvas_h: int,
    dest_x: int,
    dest_y: int,
    dest_w: int,
    dest_h: int,
) -> list[bytearray]:
    """Area-averaging resample of an RGBA image into a transparent canvas."""
    canvas = [bytearray(canvas_w * 4) for _ in range(canvas_h)]
    scale_x = src_w / dest_w
    scale_y = src_h / dest_h

    for dy in range(dest_h):
        cy = dest_y + dy
        if not (0 <= cy < canvas_h):
            continue
        sy0 = dy * scale_y
        sy1 = (dy + 1) * scale_y
        iy0 = max(0, int(sy0))
        iy1 = min(src_h - 1, int(sy1))

        for dx in range(dest_w):
            cx = dest_x + dx
            if not (0 <= cx < canvas_w):
                continue
            sx0 = dx * scale_x
            sx1 = (dx + 1) * scale_x
            ix0 = max(0, int(sx0))
            ix1 = min(src_w - 1, int(sx1))

            total_w = 0.0
            sum_r = sum_g = sum_b = sum_a = 0.0

            for sy in range(iy0, iy1 + 1):
                wy = min(sy + 1.0, sy1) - max(float(sy), sy0)
                if wy <= 0.0:
                    continue
                row = src_rows[sy]
                for sx in range(ix0, ix1 + 1):
                    wx = min(sx + 1.0, sx1) - max(float(sx), sx0)
                    if wx <= 0.0:
                        continue
                    w = wx * wy
                    idx = sx * 4
                    r = row[idx]
                    g = row[idx + 1]
                    b = row[idx + 2]
                    a = row[idx + 3] / 255.0
                    # Premultiplied alpha accumulation for clean anti-aliased edges
                    sum_r += r * a * w
                    sum_g += g * a * w
                    sum_b += b * a * w
                    sum_a += a * w
                    total_w += w

            if total_w > 0.0 and sum_a > 0.0:
                out_a = sum_a / total_w
                out_r = int(min(255.0, max(0.0, (sum_r / total_w) / out_a + 0.5)))
                out_g = int(min(255.0, max(0.0, (sum_g / total_w) / out_a + 0.5)))
                out_b = int(min(255.0, max(0.0, (sum_b / total_w) / out_a + 0.5)))
                out_a_byte = int(min(255.0, max(0.0, out_a * 255.0 + 0.5)))
                c_idx = cx * 4
                canvas[cy][c_idx : c_idx + 4] = bytes((out_r, out_g, out_b, out_a_byte))

    return canvas


def _fit_box(src_w: int, src_h: int, max_w: int, max_h: int) -> tuple[int, int]:
    """Compute aspect-ratio-preserving (width, height) inside (max_w, max_h)."""
    scale = min(max_w / src_w, max_h / src_h)
    return max(1, round(src_w * scale)), max(1, round(src_h * scale))


def _parse_svg_color(value: str | None) -> tuple[int, int, int] | None:
    """Parse an SVG fill/stroke color attribute into an (R, G, B) tuple."""
    if not value:
        return None
    v = value.strip().lower()
    if v == "none":
        return None
    if v == "black":
        return (0, 0, 0)
    if v == "white":
        return (255, 255, 255)
    if v.startswith("#"):
        hex_part = v[1:]
        if len(hex_part) == 3:
            return (
                int(hex_part[0] * 2, 16),
                int(hex_part[1] * 2, 16),
                int(hex_part[2] * 2, 16),
            )
        if len(hex_part) == 6:
            return (
                int(hex_part[0:2], 16),
                int(hex_part[2:4], 16),
                int(hex_part[4:6], 16),
            )
    raise ValueError(f"Unsupported SVG color: {value}")


def _parse_svg_path_segments(
    d_attr: str,
) -> list[tuple[float, float, float, float, float, float, float]]:
    """Parse SVG path commands (M, L, H, V, Z) into precomputed line segments."""
    tokens = re.findall(r"[MLHVZmlhvz]|[-+]?\d*\.?\d+", d_attr)
    segments: list[tuple[float, float, float, float, float, float, float]] = []
    idx = 0
    cmd = ""
    cur_x = cur_y = 0.0
    start_x = start_y = 0.0

    def add_seg(x0: float, y0: float, x1: float, y1: float) -> None:
        dx = x1 - x0
        dy = y1 - y0
        len_sq = dx * dx + dy * dy
        if len_sq > 1e-12:
            segments.append((x0, y0, x1, y1, dx, dy, len_sq))

    while idx < len(tokens):
        tok = tokens[idx]
        if tok.isalpha():
            cmd = tok
            idx += 1
            if cmd in ("Z", "z"):
                add_seg(cur_x, cur_y, start_x, start_y)
                cur_x, cur_y = start_x, start_y
            continue

        if cmd == "M":
            cur_x = float(tokens[idx])
            cur_y = float(tokens[idx + 1])
            start_x, start_y = cur_x, cur_y
            idx += 2
            cmd = "L"
        elif cmd == "L":
            nx = float(tokens[idx])
            ny = float(tokens[idx + 1])
            add_seg(cur_x, cur_y, nx, ny)
            cur_x, cur_y = nx, ny
            idx += 2
        elif cmd == "H":
            nx = float(tokens[idx])
            add_seg(cur_x, cur_y, nx, cur_y)
            cur_x = nx
            idx += 1
        elif cmd == "V":
            ny = float(tokens[idx])
            add_seg(cur_x, cur_y, cur_x, ny)
            cur_y = ny
            idx += 1
        else:
            raise ValueError(f"Unsupported SVG path command: {cmd}")

    return segments


def render_framed_svg_rgba(svg_path: Path, size: int = 256) -> list[bytearray]:
    """Rasterize Bitchat-Icon-Framed.svg into a square RGBA canvas of `size x size`.

    Preserves the exact 245x257 icon frame, rx=46 rounded corners, proportions,
    colors (#F3F3F3 frame, #000000 symbol, #22D3EE cyan node), and outer alpha
    transparency using analytical signed-distance anti-aliasing.
    """
    root = ET.fromstring(svg_path.read_text(encoding="utf-8"))
    view_box = root.attrib.get("viewBox", "0 0 245 257").split()
    vb_x, vb_y, vb_w, vb_h = (float(v) for v in view_box[:4])

    # Parse vector primitives in SVG painter's order
    primitives: list[tuple[str, object, tuple[int, int, int]]] = []
    for elem in root:
        tag = elem.tag.split("}")[-1]
        if tag == "rect":
            fill = _parse_svg_color(elem.attrib.get("fill"))
            if fill is None:
                continue
            rx_x = float(elem.attrib.get("x", "0"))
            rx_y = float(elem.attrib.get("y", "0"))
            rx_w = float(elem.attrib["width"])
            rx_h = float(elem.attrib["height"])
            corner_r = float(elem.attrib.get("rx", elem.attrib.get("ry", "0")))
            cx = rx_x + rx_w * 0.5
            cy = rx_y + rx_h * 0.5
            hx = rx_w * 0.5 - corner_r
            hy = rx_h * 0.5 - corner_r
            primitives.append(("rect", (cx, cy, hx, hy, corner_r), fill))
        elif tag == "path":
            stroke = _parse_svg_color(elem.attrib.get("stroke"))
            if stroke is None:
                continue
            stroke_w = float(elem.attrib.get("stroke-width", "1"))
            segs = _parse_svg_path_segments(elem.attrib["d"])
            primitives.append(("path", (segs, stroke_w * 0.5), stroke))
        elif tag == "circle":
            fill = _parse_svg_color(elem.attrib.get("fill"))
            if fill is None:
                continue
            ccx = float(elem.attrib["cx"])
            ccy = float(elem.attrib["cy"])
            cr = float(elem.attrib["r"])
            primitives.append(("circle", (ccx, ccy, cr), fill))

    scale = min(size / vb_w, size / vb_h)
    drawn_w = vb_w * scale
    drawn_h = vb_h * scale
    offset_x = (size - drawn_w) * 0.5
    offset_y = (size - drawn_h) * 0.5
    inv_scale = 1.0 / scale

    rows: list[bytearray] = []
    hypot = math.hypot

    for py in range(size):
        sy = vb_y + (py + 0.5 - offset_y) * inv_scale
        row = bytearray(size * 4)
        for px in range(size):
            sx = vb_x + (px + 0.5 - offset_x) * inv_scale
            pr = pg = pb = pa = 0.0

            for kind, geom, (sr, sg, sb) in primitives:
                if kind == "rect":
                    cx, cy, hx, hy, corner_r = geom  # type: ignore[misc]
                    qx = abs(sx - cx) - hx
                    qy = abs(sy - cy) - hy
                    out_x = qx if qx > 0.0 else 0.0
                    out_y = qy if qy > 0.0 else 0.0
                    in_d = qx if qx > qy else qy
                    if in_d > 0.0:
                        in_d = 0.0
                    dist = hypot(out_x, out_y) + in_d - corner_r
                elif kind == "path":
                    segs, half_w = geom  # type: ignore[misc]
                    min_d = 1e9
                    for x0, y0, _x1, _y1, dx, dy, len_sq in segs:
                        t = ((sx - x0) * dx + (sy - y0) * dy) / len_sq
                        if t < 0.0:
                            t = 0.0
                        elif t > 1.0:
                            t = 1.0
                        d_seg = hypot(sx - (x0 + t * dx), sy - (y0 + t * dy))
                        if d_seg < min_d:
                            min_d = d_seg
                    dist = min_d - half_w
                else:
                    ccx, ccy, cr = geom  # type: ignore[misc]
                    dist = hypot(sx - ccx, sy - ccy) - cr

                cov = 0.5 - dist * scale
                if cov <= 0.0:
                    continue
                if cov > 1.0:
                    cov = 1.0

                inv_cov = 1.0 - cov
                pr = sr * cov + pr * inv_cov
                pg = sg * cov + pg * inv_cov
                pb = sb * cov + pb * inv_cov
                pa = cov + pa * inv_cov

            if pa > 0.0:
                idx = px * 4
                row[idx] = int(min(255.0, max(0.0, pr / pa + 0.5)))
                row[idx + 1] = int(min(255.0, max(0.0, pg / pa + 0.5)))
                row[idx + 2] = int(min(255.0, max(0.0, pb / pa + 0.5)))
                row[idx + 3] = int(min(255.0, max(0.0, pa * 255.0 + 0.5)))
        rows.append(row)

    return rows


def _encode_ico_dib_rgba(
    width: int, height: int, rgba_rows: Sequence[bytes | bytearray]
) -> bytes:
    """Encode an RGBA icon frame as a 32-bit BGRA Win32 DIB (XOR + AND mask)."""
    xor_bytes = bytearray()
    and_row_stride = ((width + 31) // 32) * 4
    and_bytes = bytearray()

    for y in range(height - 1, -1, -1):
        row = rgba_rows[y]
        for x in range(width):
            idx = x * 4
            xor_bytes.extend((row[idx + 2], row[idx + 1], row[idx], row[idx + 3]))

        and_row = bytearray(and_row_stride)
        for x in range(width):
            if row[x * 4 + 3] == 0:
                and_row[x >> 3] |= 0x80 >> (x & 7)
        and_bytes.extend(and_row)

    bmi_header = struct.pack(
        "<IiiHHIIiiII",
        40,
        width,
        height * 2,
        1,
        32,
        0,
        len(xor_bytes) + len(and_bytes),
        0,
        0,
        0,
        0,
    )
    return bmi_header + bytes(xor_bytes) + bytes(and_bytes)


def generate_ico(output_path: Path) -> Path:
    """Build multi-resolution Windows .ico from official `Bitchat-Icon-Framed.svg`.

    Includes all 7 standard Windows icon resolutions:
    16x16, 24x24, 32x32, 48x48, 64x64, 128x128, and 256x256.
    Preserves the exact framed icon design, proportions (245:257 centered),
    colors (#F3F3F3 frame, #000000 symbol, #22D3EE cyan node), and transparency.
    """
    sync_official_assets()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    local_svg = output_path.parent / FRAMED_ICON_SVG_NAME
    framed_svg_path = (
        local_svg if local_svg.is_file() else ASSETS_DIR / FRAMED_ICON_SVG_NAME
    )
    if not framed_svg_path.is_file():
        raise FileNotFoundError(
            f"Official framed icon SVG not found at {framed_svg_path}"
        )

    master_size = 256
    master_rows = render_framed_svg_rgba(framed_svg_path, size=master_size)

    frame_payloads: list[bytes] = []
    for size in ICO_SIZES:
        if size == master_size:
            canvas = master_rows
            # Use PNG compression for the 256x256 high-DPI frame per Windows Vista+ spec
            frame_payloads.append(encode_png_rgba(size, size, canvas))
        else:
            canvas = _resample_rgba_into_canvas(
                master_size,
                master_size,
                master_rows,
                size,
                size,
                0,
                0,
                size,
                size,
            )
            # Use 32-bit BGRA DIB for 16..128 so both Win32 GDI and Shell render cleanly
            frame_payloads.append(_encode_ico_dib_rgba(size, size, canvas))

    header = struct.pack("<HHH", 0, 1, len(ICO_SIZES))
    offset = 6 + 16 * len(ICO_SIZES)
    entries = bytearray()
    for size, payload in zip(ICO_SIZES, frame_payloads, strict=True):
        w_byte = 0 if size == 256 else size
        h_byte = 0 if size == 256 else size
        entries.extend(
            struct.pack(
                "<BBBBHHII",
                w_byte,
                h_byte,
                0,
                0,
                1,
                32,
                len(payload),
                offset,
            )
        )
        offset += len(payload)

    output_path.write_bytes(header + bytes(entries) + b"".join(frame_payloads))
    return output_path


def _write_bmp_from_rgb_rows(
    output_path: Path,
    width: int,
    height: int,
    rgb_rows: list[list[tuple[int, int, int]]],
) -> Path:
    """Write a standard 24-bit Windows BMP file from top-to-bottom RGB rows."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    row_stride = (width * 3 + 3) & ~3
    padding = b"\x00" * (row_stride - width * 3)
    pixel_data = bytearray()

    for y in range(height - 1, -1, -1):
        row_bytes = bytearray()
        for r, g, b in rgb_rows[y]:
            row_bytes.extend((b, g, r))
        row_bytes.extend(padding)
        pixel_data.extend(row_bytes)

    file_size = 14 + 40 + len(pixel_data)
    bmp_header = struct.pack("<2sIHHI", b"BM", file_size, 0, 0, 54)
    dib_header = struct.pack(
        "<IiiHHIIiiII",
        40,
        width,
        height,
        1,
        24,
        0,
        len(pixel_data),
        2835,
        2835,
        0,
        0,
    )
    output_path.write_bytes(bmp_header + dib_header + bytes(pixel_data))
    return output_path


def generate_wizard_small_bmp(output_path: Path) -> Path:
    """Generate 55x55 Inno Setup header bitmap from Bitchat-Icon-Framed.svg."""
    sync_official_assets()
    local_svg = output_path.parent / FRAMED_ICON_SVG_NAME
    framed_svg_path = (
        local_svg if local_svg.is_file() else ASSETS_DIR / FRAMED_ICON_SVG_NAME
    )
    master_rows = render_framed_svg_rgba(framed_svg_path, size=128)

    width, height = 55, 55
    overlay = _resample_rgba_into_canvas(
        128, 128, master_rows, width, height, 3, 3, 49, 49
    )

    rgb_rows: list[list[tuple[int, int, int]]] = []
    for y in range(height):
        row: list[tuple[int, int, int]] = []
        ov_row = overlay[y]
        for x in range(width):
            idx = x * 4
            r, g, b, a = (
                ov_row[idx],
                ov_row[idx + 1],
                ov_row[idx + 2],
                ov_row[idx + 3] / 255.0,
            )
            # Composite over crisp white (#FFFFFF) for Inno Setup modern header
            out_r = int(WHITE[0] * (1.0 - a) + r * a + 0.5)
            out_g = int(WHITE[1] * (1.0 - a) + g * a + 0.5)
            out_b = int(WHITE[2] * (1.0 - a) + b * a + 0.5)
            row.append((out_r, out_g, out_b))
        rgb_rows.append(row)

    return _write_bmp_from_rgb_rows(output_path, width, height, rgb_rows)


def generate_wizard_large_bmp(output_path: Path) -> Path:
    """Generate 164x314 Inno Setup Welcome/Finish banner using dark-mode assets."""
    sync_official_assets()
    symbol_dark_path = ASSETS_DIR / "bitchat-symbol-dark.png"
    wordmark_dark_path = ASSETS_DIR / "bitchat-wordmark-dark.png"

    sym_w, sym_h, sym_rows = decode_png_rgba(symbol_dark_path.read_bytes())
    wm_w, wm_h, wm_rows = decode_png_rgba(wordmark_dark_path.read_bytes())

    width, height = 164, 314

    # 1. Place the official symbol centered in the upper-middle area
    sym_fit_w, sym_fit_h = _fit_box(sym_w, sym_h, 96, 106)
    sym_dx = (width - sym_fit_w) // 2
    sym_dy = 58
    sym_overlay = _resample_rgba_into_canvas(
        sym_w, sym_h, sym_rows, width, height, sym_dx, sym_dy, sym_fit_w, sym_fit_h
    )

    # 2. Place the official wordmark centered below the symbol
    wm_fit_w, wm_fit_h = _fit_box(wm_w, wm_h, 132, 48)
    wm_dx = (width - wm_fit_w) // 2
    wm_dy = sym_dy + sym_fit_h + 22
    wm_overlay = _resample_rgba_into_canvas(
        wm_w, wm_h, wm_rows, width, height, wm_dx, wm_dy, wm_fit_w, wm_fit_h
    )

    rgb_rows: list[list[tuple[int, int, int]]] = []
    for y in range(height):
        t = y / max(1, height - 1)
        bg_r = int(BRAND_NAVY[0] * (1.0 - t) + BRAND_NAVY_DEEP[0] * t)
        bg_g = int(BRAND_NAVY[1] * (1.0 - t) + BRAND_NAVY_DEEP[1] * t)
        bg_b = int(BRAND_NAVY[2] * (1.0 - t) + BRAND_NAVY_DEEP[2] * t)

        row: list[tuple[int, int, int]] = []
        s_row = sym_overlay[y]
        w_row = wm_overlay[y]
        for x in range(width):
            r_out, g_out, b_out = bg_r, bg_g, bg_b

            # Subtle right-edge cyan border accent (#22D3EE blended with #071826)
            if x == width - 1:
                r_out = int(bg_r * 0.65 + BRAND_CYAN[0] * 0.35)
                g_out = int(bg_g * 0.65 + BRAND_CYAN[1] * 0.35)
                b_out = int(bg_b * 0.65 + BRAND_CYAN[2] * 0.35)

            for ov in (s_row, w_row):
                idx = x * 4
                or_, og, ob, oa = (
                    ov[idx],
                    ov[idx + 1],
                    ov[idx + 2],
                    ov[idx + 3] / 255.0,
                )
                if oa > 0.0:
                    r_out = int(r_out * (1.0 - oa) + or_ * oa + 0.5)
                    g_out = int(g_out * (1.0 - oa) + og * oa + 0.5)
                    b_out = int(b_out * (1.0 - oa) + ob * oa + 0.5)

            row.append((r_out, g_out, b_out))
        rgb_rows.append(row)

    return _write_bmp_from_rgb_rows(output_path, width, height, rgb_rows)


def generate_version_info(version: str, output_path: Path | None = None) -> Path:
    """Generate PyInstaller VSVersionInfo file for bitchat.exe."""
    target = output_path or VERSION_INFO_PATH
    parts = [int(p) if p.isdigit() else 0 for p in version.split(".")[:4]]
    while len(parts) < 4:
        parts.append(0)
    ver_tuple = tuple(parts[:4])
    desc = "BitChat — Peer-to-Peer Encrypted Terminal Messenger"
    copy_str = "Copyright (c) 2026 BitChat Contributors (MIT License)"

    content = f"""# UTF-8
# Auto-generated Windows Version Resource for BitChat
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={ver_tuple},
    prodvers={ver_tuple},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
      StringTable(
        '040904B0',
        [StringStruct('CompanyName', 'Java-Mx'),
        StringStruct('FileDescription', '{desc}'),
        StringStruct('FileVersion', '{version}.0'),
        StringStruct('InternalName', 'bitchat'),
        StringStruct('LegalCopyright', '{copy_str}'),
        StringStruct('OriginalFilename', 'bitchat.exe'),
        StringStruct('ProductName', 'BitChat'),
        StringStruct('ProductVersion', '{version}')])
      ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    target.write_text(content, encoding="utf-8")
    return target


def ensure_windows_assets(version: str = "0.2.1") -> dict[str, Path]:
    """Sync official BitChat assets and generate Windows installer icons/bitmaps."""
    sync_official_assets()
    ico_path = generate_ico(ASSETS_DIR / "bitchat.ico")
    large_bmp = generate_wizard_large_bmp(ASSETS_DIR / "wizard-large.bmp")
    small_bmp = generate_wizard_small_bmp(ASSETS_DIR / "wizard-small.bmp")
    ver_info = generate_version_info(version, VERSION_INFO_PATH)
    return {
        "ico": ico_path,
        "wizard_large": large_bmp,
        "wizard_small": small_bmp,
        "version_info": ver_info,
    }


if __name__ == "__main__":
    paths = ensure_windows_assets()
    for name, p in paths.items():
        print(f"[+] Prepared {name}: {p} ({p.stat().st_size} bytes)")
