"""The mark — generated, not shipped as a binary.

Smelt needs an app icon for the phone (PWA install) and the browser extension.
Rather than commit binary assets, we draw it: a molten ingot on near-black, in
the same metallic monochrome the notes are read in. Pure stdlib (zlib + struct),
no image library, ~40 lines.
"""

from __future__ import annotations

import struct
import zlib

_GROUND = (10, 10, 13)  # the page's own background
_TOP = (236, 233, 225)  # cooled metal
_BOTTOM = (110, 108, 118)  # shadow side


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b, strict=True))  # type: ignore[return-value]


def icon_png(size: int = 512) -> bytes:
    """A centered ingot (a soft diamond) with a vertical metal gradient."""
    cx = cy = (size - 1) / 2
    radius = size * 0.34
    rows = bytearray()
    for y in range(size):
        rows.append(0)  # PNG filter byte: none
        for x in range(size):
            # Superellipse-ish diamond: |dx| + |dy| <= r, softened at the edge.
            d = (abs(x - cx) + abs(y - cy)) / radius
            if d <= 1.0:
                metal = _mix(_TOP, _BOTTOM, y / size)
                edge = min(1.0, (1.0 - d) * size / 8)  # 8px feather, antialiased
                r, g, b = _mix(_GROUND, metal, edge)
            else:
                r, g, b = _GROUND
            rows += bytes((r, g, b, 255))
    return _wrap(size, bytes(rows))


def _wrap(size: int, raw: bytes) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8-bit RGBA
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
