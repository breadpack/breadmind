#!/usr/bin/env python3
"""Generate placeholder PWA icons for BreadMind.

Creates minimal valid PNG icons using only the struct and zlib modules
(no Pillow dependency required).
"""
import struct
import zlib
from pathlib import Path


BRAND_COLOR = (0x63, 0x66, 0xF1)  # #6366f1
DARK_BG = (0x0F, 0x17, 0x2A)      # #0f172a
WHITE = (0xF8, 0xFA, 0xFC)        # #f8fafc


def create_png(width: int, height: int, pixels: bytes) -> bytes:
    """Create a minimal valid PNG from raw RGBA pixel data."""
    # PNG signature
    signature = b'\x89PNG\r\n\x1a\n'

    # IHDR chunk
    ihdr_data = struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)  # 8-bit RGBA
    ihdr = _make_chunk(b'IHDR', ihdr_data)

    # IDAT chunk - raw pixels with filter byte (0 = None) per row
    raw_data = b''
    stride = width * 4  # RGBA
    for y in range(height):
        raw_data += b'\x00'  # filter byte
        raw_data += pixels[y * stride:(y + 1) * stride]
    compressed = zlib.compress(raw_data, 9)
    idat = _make_chunk(b'IDAT', compressed)

    # IEND chunk
    iend = _make_chunk(b'IEND', b'')

    return signature + ihdr + idat + iend


def _make_chunk(chunk_type: bytes, data: bytes) -> bytes:
    chunk = chunk_type + data
    return struct.pack('>I', len(data)) + chunk + struct.pack('>I', zlib.crc32(chunk) & 0xFFFFFFFF)


def draw_icon(size: int, maskable: bool = False) -> bytes:
    """Draw a BreadMind icon with brand color background and 'B' letter."""
    pixels = bytearray(size * size * 4)

    # Safe zone for maskable icons is the inner 80%
    padding = int(size * 0.1) if maskable else int(size * 0.05)
    corner_radius = int(size * 0.15) if not maskable else 0

    bg = BRAND_COLOR
    fg = WHITE

    # Fill background
    for y in range(size):
        for x in range(size):
            idx = (y * size + x) * 4
            # Round corners for non-maskable
            if not maskable and _is_corner(x, y, size, corner_radius):
                pixels[idx:idx + 4] = bytes([0, 0, 0, 0])
            else:
                pixels[idx:idx + 4] = bytes([bg[0], bg[1], bg[2], 255])

    # Draw a simple "B" letter
    _draw_letter_b(pixels, size, padding, fg)

    return create_png(size, size, bytes(pixels))


def _is_corner(x: int, y: int, size: int, radius: int) -> bool:
    """Check if pixel is outside rounded corners."""
    if radius <= 0:
        return False
    corners = [
        (radius, radius),
        (size - radius - 1, radius),
        (radius, size - radius - 1),
        (size - radius - 1, size - radius - 1),
    ]
    for cx, cy in corners:
        dx = abs(x - cx)
        dy = abs(y - cy)
        if x < radius and y < radius and dx * dx + dy * dy > radius * radius:
            return True
        if x >= size - radius and y < radius and dx * dx + dy * dy > radius * radius:
            return True
        if x < radius and y >= size - radius and dx * dx + dy * dy > radius * radius:
            return True
        if x >= size - radius and y >= size - radius and dx * dx + dy * dy > radius * radius:
            return True
    return False


def _draw_letter_b(pixels: bytearray, size: int, padding: int, color: tuple):
    """Draw a bold 'B' letter centered in the icon."""
    # Calculate letter bounds
    left = int(size * 0.3)
    right = int(size * 0.72)
    top = int(size * 0.2) + padding
    bottom = int(size * 0.8) - padding
    mid_y = (top + bottom) // 2
    thickness = max(int(size * 0.08), 2)

    def _set_pixel(x, y):
        if 0 <= x < size and 0 <= y < size:
            idx = (y * size + x) * 4
            pixels[idx:idx + 4] = bytes([color[0], color[1], color[2], 255])

    def _fill_rect(x1, y1, x2, y2):
        for yy in range(max(0, y1), min(size, y2)):
            for xx in range(max(0, x1), min(size, x2)):
                _set_pixel(xx, yy)

    # Vertical stroke (left side)
    _fill_rect(left, top, left + thickness, bottom)

    # Top horizontal
    _fill_rect(left, top, right - thickness, top + thickness)

    # Middle horizontal
    _fill_rect(left, mid_y - thickness // 2, right - thickness, mid_y + thickness // 2 + thickness % 2)

    # Bottom horizontal
    _fill_rect(left, bottom - thickness, right - thickness, bottom)

    # Top-right curve (simplified as vertical + corner)
    curve_x = right - thickness
    _fill_rect(curve_x, top, right, mid_y)

    # Bottom-right curve
    _fill_rect(curve_x, mid_y, right, bottom)


def draw_apple_touch_icon(size: int) -> bytes:
    """Draw an apple touch icon (no transparency, full square)."""
    pixels = bytearray(size * size * 4)
    bg = BRAND_COLOR
    fg = WHITE

    for y in range(size):
        for x in range(size):
            idx = (y * size + x) * 4
            pixels[idx:idx + 4] = bytes([bg[0], bg[1], bg[2], 255])

    _draw_letter_b(pixels, size, int(size * 0.1), fg)
    return create_png(size, size, bytes(pixels))


def main():
    icons_dir = Path(__file__).parent.parent / "src" / "breadmind" / "web" / "static" / "icons"
    icons_dir.mkdir(parents=True, exist_ok=True)

    icons = {
        "icon-192.png": (192, False),
        "icon-512.png": (512, False),
        "icon-maskable-192.png": (192, True),
        "icon-maskable-512.png": (512, True),
    }

    for filename, (size, maskable) in icons.items():
        path = icons_dir / filename
        data = draw_icon(size, maskable)
        path.write_bytes(data)
        print(f"Generated {path} ({len(data)} bytes)")

    # Apple touch icon (180x180)
    apple_path = icons_dir / "apple-touch-icon.png"
    data = draw_apple_touch_icon(180)
    apple_path.write_bytes(data)
    print(f"Generated {apple_path} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
