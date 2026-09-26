"""ホロカラーのアイコン(src/app.ico)を作る。絵を変えたいときだけ流す(ビルドには要らない。できた app.ico をコミットする)。
    python holo-colors/make_icon.py
4色の角丸の四角を 2x2 に並べた絵。16〜64 は BMP、256 は PNG で1つの .ico に入れる(Windows の決まり)。"""
import os
import struct
import zlib

COLORS = [(0xFF, 0x6B, 0x9D), (0x4F, 0xB8, 0xF7), (0xFF, 0xC8, 0x3D), (0x9C, 0x7C, 0xF4)]
SIZES = (16, 20, 24, 32, 40, 48, 64, 256)
SS = 4   # 1ピクセルを 4x4 に分けて、縁をなめらかにする


def coverage(px, py, size):
    """(px, py) のピクセルが、どの色の四角にどれだけかかっているか -> [(色, 割合)]"""
    gap = max(1.0, size * 0.07)
    margin = size * 0.04
    cell = (size - 2 * margin - gap) / 2
    radius = cell * 0.28
    hits = [0] * 4
    for sy in range(SS):
        for sx in range(SS):
            x = px + (sx + 0.5) / SS
            y = py + (sy + 0.5) / SS
            for i in range(4):
                x0 = margin + (i % 2) * (cell + gap)
                y0 = margin + (i // 2) * (cell + gap)
                if inside_round_rect(x, y, x0, y0, cell, cell, radius):
                    hits[i] += 1
                    break
    return [(COLORS[i], hits[i] / (SS * SS)) for i in range(4) if hits[i]]


def inside_round_rect(x, y, x0, y0, w, h, r):
    if x < x0 or y < y0 or x > x0 + w or y > y0 + h:
        return False
    cx = min(max(x, x0 + r), x0 + w - r)
    cy = min(max(y, y0 + r), y0 + h - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def pixels(size):
    """上から下への RGBA の行"""
    rows = []
    for y in range(size):
        row = []
        for x in range(size):
            cov = coverage(x, y, size)
            a = sum(c for _, c in cov)
            if a == 0:
                row.append((0, 0, 0, 0))
                continue
            r = sum(col[0] * c for col, c in cov) / a
            g = sum(col[1] * c for col, c in cov) / a
            b = sum(col[2] * c for col, c in cov) / a
            row.append((round(r), round(g), round(b), round(min(1.0, a) * 255)))
        rows.append(row)
    return rows


def bmp_entry(size):
    rows = pixels(size)
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    xor = b"".join(bytes((b, g, r, a)) for row in reversed(rows) for (r, g, b, a) in row)
    mask_row = ((size + 31) // 32) * 4
    and_mask = b"\x00" * (mask_row * size)   # 透明さは 32bit のアルファで表す
    return header + xor + and_mask


def png_entry(size):
    rows = pixels(size)
    raw = b"".join(b"\x00" + b"".join(bytes(p) for p in row) for row in rows)

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def build_ico():
    images = [(s, png_entry(s) if s >= 256 else bmp_entry(s)) for s in SIZES]
    out = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    for s, data in images:
        dim = 0 if s >= 256 else s
        out += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    return out + b"".join(d for _, d in images)


if __name__ == "__main__":
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src", "app.ico")
    with open(path, "wb") as f:
        f.write(build_ico())
    print(path, os.path.getsize(path), "bytes")
