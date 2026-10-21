# -*- coding: utf-8 -*-
"""
Generate docs/preview.png from the real renderer.

The image is produced by the same code path the app uses at runtime, so it can
never drift from what users actually see.

    python tools/make_preview.py
"""

import ctypes
import importlib.util
import os
import struct
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def load_app():
    spec = importlib.util.spec_from_file_location("shake_cursor",
                                                  os.path.join(ROOT, "shake_cursor.pyw"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.dpi_aware()
    return mod


def write_png(path, rows, width, height):
    data = zlib.compress(b"".join(b"\x00" + bytes(r) for r in rows), 9)

    def chunk(tag, payload):
        return (struct.pack(">I", len(payload)) + tag + payload +
                struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) +
                chunk(b"IDAT", data) + chunk(b"IEND", b""))


def blend(dst, fg, a):
    return int(fg + (dst - fg) * (1.0 - a / 255.0))


def main():
    mod = load_app()
    dpi = 2.0                       # render at 2x for a crisp preview
    frames = [(1.0, mod.build_frame(1.0, dpi)), (3.0, mod.build_frame(3.0, dpi))]

    PANEL_W, PANEL_H = 260, 300
    ZOOM = 2
    W, H = PANEL_W * 3, PANEL_H
    BG = (28, 28, 32)               # dark desktop-ish background
    BG2 = (40, 40, 46)
    DIVIDER = (60, 60, 68)

    # canvas: vertical gradient
    canvas = [[(0, 0, 0)] * W for _ in range(H)]
    for y in range(H):
        k = y / max(1, H - 1)
        c = (int(BG[0] + (BG2[0] - BG[0]) * k),
             int(BG[1] + (BG2[1] - BG[1]) * k),
             int(BG[2] + (BG2[2] - BG[2]) * k))
        for x in range(W):
            canvas[y][x] = c

    # panel order: normal -> enlarged -> normal (the actual animation)
    order = [frames[0][1], frames[1][1], frames[0][1]]
    for idx, frame in enumerate(order):
        raw = ctypes.string_at(frame.bits, frame.w * frame.h * 4)
        # put the hotspot (top-left tip of the arrow) at 1/3 of the panel
        ox = idx * PANEL_W + 70 - frame.margin
        oy = 90 - frame.margin
        for y in range(frame.h):
            cy = oy + y
            if not (0 <= cy < H):
                continue
            for x in range(frame.w):
                cx = ox + x
                if not (0 <= cx < W):
                    continue
                i = (y * frame.w + x) * 4
                b, g, r, a = raw[i], raw[i + 1], raw[i + 2], raw[i + 3]
                if a == 0:
                    continue
                dr, dg, db = canvas[cy][cx]
                canvas[cy][cx] = (blend(dr, r, a), blend(dg, g, a), blend(db, b, a))

    for x in (PANEL_W, PANEL_W * 2):
        for y in range(H):
            canvas[y][x] = DIVIDER

    # upscale with nearest neighbour so edges stay sharp
    rows = []
    for y in range(H * ZOOM):
        src = canvas[y // ZOOM]
        row = bytearray()
        for x in range(W * ZOOM):
            r, g, b = src[x // ZOOM]
            row.extend((r, g, b))
        rows.append(row)

    out = os.path.join(ROOT, "docs", "preview.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    write_png(out, rows, W * ZOOM, H * ZOOM)
    print("wrote", out, W * ZOOM, "x", H * ZOOM)


if __name__ == "__main__":
    main()
