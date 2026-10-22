"""Redraw the kanji/kana menu graphics in English (spec: graphics/menus.json).

Each screen's text lives in uncompressed 2bpp tiles inside a 4 KB tileset in
ROM. This module rebuilds the screen's pixels for the listed cells, clears the
text rectangle, draws English with the 5x7 menu font, and writes the tiles
back. Ink that lands on a cell not listed (a shared tile) is an error.
"""
import json
from pathlib import Path


def load_font(path):
    glyphs, name, rows = {}, None, []
    for line in Path(path).read_text().splitlines():
        if line.startswith("# ") or not line.strip():
            continue
        s = line.strip()
        if set(s) <= {"#", "."} and name is not None and (rows or len(s) > 1):
            rows.append(s)
        else:
            name, rows = (" " if s == "space" else s), []
            glyphs[name] = rows
    return glyphs


def text_width(font, text):
    return sum(len(font[c][0]) for c in text) + len(text) - 1


def vram_offset(tile, signed):
    if signed:
        t = tile - 256 if tile >= 128 else tile
        return (0x9000 + t * 16) & 0xFFF
    return (0x8000 + tile * 16) & 0xFFF


def cells(screen):
    out = []
    for row, (col0, tiles) in screen["cells"].items():
        for i, t in enumerate(tiles.split()):
            if t != "--":
                out.append((int(row), col0 + i, int(t, 16)))
    return out


def apply_screen(rom, screen, font):
    base = int(screen["tileset"], 16)
    owned = {(r, c): (base + vram_offset(t, screen["signed"])) for r, c, t in cells(screen)}
    # pixel canvas of the owned cells: (x, y) -> color
    px = {}
    for (r, c), off in owned.items():
        tile = rom[off:off + 16]
        for y in range(8):
            lo, hi = tile[2 * y], tile[2 * y + 1]
            for x in range(8):
                px[(c * 8 + x, r * 8 + y)] = ((lo >> (7 - x)) & 1) | (((hi >> (7 - x)) & 1) << 1)
    ink, paper = screen.get("ink", 3), screen.get("paper", 0)
    x0, y0, x1, y1 = screen["clear"]
    for (x, y) in px:
        if x0 <= x <= x1 and y0 <= y <= y1:
            px[(x, y)] = paper
    problems = []
    for line in screen["lines"]:
        w = text_width(font, line["text"])
        x = screen["cx"] - w // 2 if line["x"] == "center" else line["x"]
        y = line["y"]
        if x < x0 or x + w - 1 > x1 or y < y0 or y + len(font["A"]) - 1 > y1:
            problems.append(f"{screen['name']}: {line['text']!r} leaves the clear area")
        for ch in line["text"]:
            g = font[ch]
            for gy, row in enumerate(g):
                for gx, bit in enumerate(row):
                    if bit != "#":
                        continue
                    p = (x + gx, y + gy)
                    if p not in px:
                        problems.append(f"{screen['name']}: {line['text']!r} inks shared cell at {p}")
                    else:
                        px[p] = ink
            x += len(g[0]) + 1
    for (r, c), off in owned.items():
        data = bytearray()
        for y in range(8):
            lo = hi = 0
            for x in range(8):
                v = px[(c * 8 + x, r * 8 + y)]
                lo |= (v & 1) << (7 - x)
                hi |= (v >> 1) << (7 - x)
            data += bytes([lo, hi])
        rom[off:off + 16] = data
    return problems


def apply_all(rom, root):
    spec = json.loads((root / "graphics" / "menus.json").read_text())
    font = load_font(root / "font" / "menu5x7.txt")
    problems = []
    for screen in spec["screens"]:
        problems += apply_screen(rom, screen, font)
    return len(spec["screens"]), problems
