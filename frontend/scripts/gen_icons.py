"""Generate simple PNG app icons (pure Python, no deps) for the vendor PWA.

Draws an emerald (#065f46) rounded tile with a white plate circle and a
centered emerald "D" glyph. Outputs icon-192.png and icon-512.png into
shopkeeper/public/mobile/.
"""
import struct
import zlib
from pathlib import Path

EMERALD = (6, 95, 70)
WHITE = (255, 255, 255)
# Outputs into frontend/shopkeeper/public/mobile/ (relative to this script)
OUT = Path(__file__).resolve().parents[1] / "shopkeeper/public/mobile"

# 5x7 bitmap font glyph for "D"
GLYPH_D = [
    "11110",
    "10001",
    "10001",
    "10001",
    "10001",
    "10001",
    "11110",
]


def draw_glyph(size: int, bg: tuple[int, int, int], fg: tuple[int, int, int]) -> bytes:
    rows = []
    block = max(2, size // 13)  # glyph block size
    glyph_w = 5 * block
    glyph_h = 7 * block
    offset_x = (size - glyph_w) // 2
    offset_y = (size - glyph_h) // 2
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            color = bg
            cx, cy = (x + 0.5 - size / 2) / size, (y + 0.5 - size / 2) / size
            if cx * cx + cy * cy <= 0.34:
                color = WHITE
            gx = (x - offset_x) // block
            gy = (y - offset_y) // block
            if 0 <= gx < 5 and 0 <= gy < 7 and GLYPH_D[gy][gx] == "1":
                # glyph is emerald on the white plate
                color = EMERALD if color == WHITE else bg
            row.extend(color)
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        png = draw_glyph(size, EMERALD, WHITE)
        path = OUT / f"icon-{size}.png"
        path.write_bytes(png)
        print(f"wrote {path} ({len(png)} bytes)")
    # Remove the placeholder .txt files
    for txt in OUT.glob("icon-*.txt"):
        txt.unlink()
        print(f"removed {txt}")


if __name__ == "__main__":
    main()
