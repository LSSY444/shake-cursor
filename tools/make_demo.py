# -*- coding: utf-8 -*-
"""
Generate docs/demo.gif - an animated preview of the shake-to-find-cursor effect.

Frames come from the very same renderer the app uses at runtime, so the demo can
never drift from reality. Everything here is pure standard library: the GIF is
written by hand and the LZW stream is verified by decoding it back.

    python tools/make_demo.py
"""

import ctypes
import importlib.util
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

W, H = 480, 300
DPI = 1.8
HOTSPOT = (110, 80)          # where the arrow tip sits on the canvas
BG_TOP, BG_BOTTOM = 98, 142  # subtle vertical gradient, all grayscale

# (scale, delay in 1/100 s) - grow, hold, shrink, rest
TIMELINE = [
    (1.0, 70), (1.0, 40),
    (1.6, 5), (2.2, 5), (2.8, 5),
    (3.0, 70), (3.0, 60),
    (2.6, 5), (1.9, 5), (1.2, 5),
    (1.0, 110),
]


def load_app():
    spec = importlib.util.spec_from_file_location("shake_cursor",
                                                  os.path.join(ROOT, "shake_cursor.pyw"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.dpi_aware()
    return mod


# --------------------------------------------------------------------------- GIF
class BitWriter:
    def __init__(self):
        self.buf = bytearray()
        self.cur = 0
        self.n = 0

    def write(self, code, size):
        self.cur |= (code << self.n)
        self.n += size
        while self.n >= 8:
            self.buf.append(self.cur & 0xFF)
            self.cur >>= 8
            self.n -= 8

    def flush(self):
        if self.n:
            self.buf.append(self.cur & 0xFF)
            self.cur = 0
            self.n = 0
        return bytes(self.buf)


def lzw_encode(indices, min_code_size=8):
    clear = 1 << min_code_size
    end = clear + 1
    code_size = min_code_size + 1
    table = {bytes([i]): i for i in range(clear)}
    next_code = end + 1
    bw = BitWriter()
    bw.write(clear, code_size)
    w = b""
    for c in indices:
        wc = w + bytes([c])
        if wc in table:
            w = wc
            continue
        bw.write(table[w], code_size)
        if next_code < 4096:
            table[wc] = next_code
            next_code += 1
            if next_code > (1 << code_size) and code_size < 12:
                code_size += 1
        else:
            bw.write(clear, code_size)
            table = {bytes([i]): i for i in range(clear)}
            next_code = end + 1
            code_size = min_code_size + 1
        w = bytes([c])
    if w:
        bw.write(table[w], code_size)
    bw.write(end, code_size)
    return bw.flush()


class BitReader:
    def __init__(self, data):
        self.data = data
        self.pos = 0
        self.cur = 0
        self.n = 0

    def read(self, size):
        while self.n < size:
            if self.pos >= len(self.data):
                return None
            self.cur |= self.data[self.pos] << self.n
            self.pos += 1
            self.n += 8
        v = self.cur & ((1 << size) - 1)
        self.cur >>= size
        self.n -= size
        return v


def lzw_decode(data, min_code_size=8):
    """Only used to verify the encoder - decoder is the simple textbook one.

    The table has to reserve index `clear` and `end`, so the first free code is
    clear+2 (258 for 8-bit data) exactly like on the encoder side.
    """
    clear = 1 << min_code_size
    end = clear + 1

    def fresh():
        return [bytes([i]) for i in range(clear)] + [b"", b""]

    code_size = min_code_size + 1
    table = fresh()
    out = bytearray()
    prev = None
    br = BitReader(data)
    while True:
        code = br.read(code_size)
        if code is None or code == end:
            break
        if code == clear:
            table = fresh()
            code_size = min_code_size + 1
            prev = None
            continue
        if code < len(table):
            entry = table[code]
        elif code == len(table) and prev is not None:
            entry = prev + prev[:1]
        else:
            raise ValueError("bad LZW code %d (table %d)" % (code, len(table)))
        out += entry
        if prev is not None:
            table.append(prev + entry[:1])
            if len(table) == (1 << code_size) and code_size < 12:
                code_size += 1
        prev = entry
    return bytes(out)


def blocks(data, size=255):
    out = bytearray()
    for i in range(0, len(data), size):
        chunk = data[i:i + size]
        out.append(len(chunk))
        out += chunk
    out.append(0)
    return bytes(out)


def write_gif(path, frames):
    """frames: list of (bytes indices, delay_cs)"""
    out = bytearray(b"GIF89a")
    out += struct.pack("<HH", W, H)
    out += bytes([0xF7, 0, 0])          # GCT present, 256 entries, color res 7
    for i in range(256):                # grayscale palette
        out += bytes([i, i, i])
    out += b"\x21\xFF\x0BNETSCAPE2.0\x03\x01\x00\x00\x00"   # loop forever

    for indices, delay in frames:
        out += b"\x21\xF9\x04" + bytes([0x04]) + struct.pack("<H", delay) + b"\x00\x00"
        out += b"\x2C" + struct.pack("<HHHH", 0, 0, W, H) + bytes([0])
        out += bytes([8])
        out += blocks(lzw_encode(indices))
    out += b"\x3B"
    with open(path, "wb") as f:
        f.write(out)
    return len(out)


# ------------------------------------------------------------------------ frames
def render_frame(mod, scale):
    frame = mod.build_frame(scale, DPI)
    raw = ctypes.string_at(frame.bits, frame.w * frame.h * 4)

    # grayscale background gradient
    px = bytearray(W * H)
    for y in range(H):
        v = int(BG_TOP + (BG_BOTTOM - BG_TOP) * (y / (H - 1)))
        px[y * W:(y + 1) * W] = bytes([v]) * W

    ox = HOTSPOT[0] - frame.margin
    oy = HOTSPOT[1] - frame.margin
    for y in range(frame.h):
        cy = oy + y
        if not (0 <= cy < H):
            continue
        for x in range(frame.w):
            cx = ox + x
            if not (0 <= cx < W):
                continue
            i = (y * frame.w + x) * 4
            a = raw[i + 3]
            if a == 0:
                continue
            premul = raw[i]                      # r == g == b for this artwork
            bg = px[cy * W + cx]
            v = premul + bg * (255 - a) // 255   # premultiplied "over"
            px[cy * W + cx] = 255 if v > 255 else v
    return bytes(px)


def main():
    mod = load_app()
    frames = []
    for scale, delay in TIMELINE:
        indices = render_frame(mod, scale)
        back = lzw_decode(lzw_encode(indices))
        assert back == indices, "LZW round-trip failed at scale %.1f" % scale
        frames.append((indices, delay))
        print("frame scale=%.1f delay=%dcs" % (scale, delay))

    out = os.path.join(ROOT, "docs", "demo.gif")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    size = write_gif(out, frames)
    print("wrote %s  %dx%d  %d frames  %.1f KB" % (out, W, H, len(frames), size / 1024.0))


if __name__ == "__main__":
    main()
