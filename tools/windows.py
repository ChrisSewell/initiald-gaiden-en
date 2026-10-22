"""Bank 4 window tilemaps: list, render as text, and apply English edits.

Table of little-endian pointers at 0x10000 (CPU $4000, bank 4). A window
starts with 08, W-1, H-1 and then W*H tile numbers, row by row. Tile n is the
character at position n of the table at $0DCB, so text here is stored as tile
numbers, not character codes. Tiles 80-85 are the box border.
"""
import re
import struct
import unicodedata

TABLE = 0x10000
COUNT = 42
CHAR_TABLE = 0x0DCB
BOX = {0x80: "┌", 0x81: "─", 0x82: "┐", 0x83: "│", 0x84: "└", 0x85: "┘"}
BOX_TILE = {v: k for k, v in BOX.items()}
KEEP = "▒"  # tile with no text meaning; kept as-is
SPACE = "·"


def char_table(rom):
    return list(rom[CHAR_TABLE:CHAR_TABLE + 128])


def is_kana_tile(rom, t):
    return t < 128 and 0xA6 <= char_table(rom)[t] <= 0xDF


def windows(rom):
    """All plain (08) windows that hold kana, plus W16's border label."""
    out = []
    for k in range(COUNT):
        p = struct.unpack_from("<H", rom, TABLE + 2 * k)[0]
        off = TABLE + p - 0x4000
        if rom[off] != 0x08:
            continue
        w, h = rom[off + 1] + 1, rom[off + 2] + 1
        body = bytes(rom[off + 3:off + 3 + w * h])
        if any(is_kana_tile(rom, t) for t in body):
            out.append((f"W{k:02d}", off, w, h, body))
    return out


def tile_char(rom, t):
    if t in BOX:
        return BOX[t]
    if t >= 128:
        return KEEP
    c = char_table(rom)[t]
    if c == 0x20:
        return SPACE
    if 0xA1 <= c <= 0xDF:
        s = unicodedata.normalize("NFKC", bytes([c]).decode("cp932"))
        o = ord(s)
        if s == "゙":
            return "゛"
        if s == "゚":
            return "゜"
        return chr(o - 0x60) if 0x30A1 <= o <= 0x30F6 else s
    if 0x21 <= c <= 0x5F:
        return chr(c)
    return KEEP


def render(rom, body, w, h):
    return ["".join(tile_char(rom, t) for t in body[y * w:(y + 1) * w]) for y in range(h)]


def parse_edits(text):
    """{window_id: {row: (mode, text)}} from en_windows.txt."""
    edits = {}
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        m = re.match(r"(W\d\d)\.(\d+) (:?=) ?(.*)$", line)
        if not m:
            raise ValueError(f"bad line: {line!r}")
        wid, row, op, body = m.groups()
        edits.setdefault(wid, {})[int(row)] = ("full" if op == ":=" else "inner", body)
    return edits


def apply_edits(rows, w, edits):
    """Return new text rows and a list of problems."""
    rows = list(rows)
    problems = []
    for r, (mode, text) in sorted(edits.items()):
        old = rows[r]
        if mode == "full":
            if len(text) != w:
                problems.append(f"row {r}: {len(text)} wide, needs {w}")
                continue
            rows[r] = "".join(o if n == "~" else n for n, o in zip(text, old))
        else:
            inner = w - 2
            if len(text) > inner:
                problems.append(f"row {r}: {text!r} is {len(text)} chars, box fits {inner}")
                continue
            # keep the edge columns only if they are border tiles
            left = old[0] if old[0] in BOX_TILE else SPACE
            right = old[-1] if old[-1] in BOX_TILE else SPACE
            rows[r] = left + text.replace(" ", SPACE).ljust(inner, SPACE) + right
    return rows, problems


def encode_rows(rom, rows, body, w, char_code):
    """Tile numbers for text rows. char_code maps a character to its code."""
    table = char_table(rom)
    out = bytearray()
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            orig = body[y * w + x]
            if ch == KEEP:
                out.append(orig)
            elif ch in BOX_TILE:
                out.append(BOX_TILE[ch])
            else:
                out.append(table.index(char_code(" " if ch == SPACE else ch)))
    return bytes(out)
