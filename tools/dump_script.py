#!/usr/bin/env python3
"""Dump all text from Initial D Gaiden (Japan) (SGB Enhanced).gb.

Usage: python3 -I dump_script.py <rom.gb> <out_dir>

Text encoding: single-byte JIS X 0201 order. 0x20-0x5F are ASCII, 0xA1-0xDF
are half-width katakana codes that the font draws as hiragana. Dakuten (0xDE)
and handakuten (0xDF) are separate bytes that follow the base kana.

Control codes:
  62 <open>   start of a dialog message
  63 <clear>  clear the box and continue
  65 <end>    end of string / message
  6C <br>     newline
  74 <wait>   wait for button

Writes:
  script.tsv   one row per string: id, rom offset, cpu address, kind, raw hex,
               decoded Japanese, empty English column
  script.txt   the same, readable
"""
import struct
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import windows  # noqa: E402

SCRIPT_TABLE = 0x9600      # 224 little-endian pointers, bank 2
SCRIPT_COUNT = 224
PRINT_CALL = b"\xcd\xe0\x0c"  # call $0CE0, string follows inline
BANK1 = (0x4000, 0x8000)

CODES = {0x62: "<open>", 0x63: "<clear>", 0x65: "<end>", 0x6C: "<br>", 0x74: "<wait>"}


def char(b):
    if 0xA1 <= b <= 0xDF:
        c = unicodedata.normalize("NFKC", bytes([b]).decode("cp932"))
        o = ord(c)
        return chr(o - 0x60) if 0x30A1 <= o <= 0x30F6 else c
    if 0x20 <= b <= 0x5F:
        return chr(b)
    return CODES.get(b, "{%02X}" % b)


def decode(raw):
    return unicodedata.normalize("NFC", "".join(char(b) for b in raw))


def read_until_end(rom, off):
    end = rom.index(0x65, off)
    return rom[off:end + 1]


def is_text(b):
    return 0x20 <= b <= 0x5F or 0xA1 <= b <= 0xDF


def cpu_addr(off):
    return off if off < 0x4000 else 0x4000 + off % 0x4000


def main():
    rom = Path(sys.argv[1]).read_bytes()
    out = Path(sys.argv[2])
    rows = []

    # Main dialog script (bank 2). Several table entries share a message.
    seen = {}
    for i in range(SCRIPT_COUNT):
        ptr = struct.unpack_from("<H", rom, SCRIPT_TABLE + 2 * i)[0]
        off = 0x8000 + ptr - 0x4000
        if off in seen:
            rows.append((f"S{i:03d}", off, "dialog", None, f"same as {seen[off]}"))
            continue
        seen[off] = f"S{i:03d}"
        rows.append((f"S{i:03d}", off, "dialog", read_until_end(rom, off), None))

    # Messages in the script block that no table entry points to.
    covered = set()
    for off in seen:
        covered.update(range(off, off + len(read_until_end(rom, off))))
    block_end = max(covered) + 1
    n = 0
    off = SCRIPT_TABLE + 2 * SCRIPT_COUNT
    while off < block_end:
        if off in covered or rom[off] != 0x62:
            off += 1
            continue
        raw = read_until_end(rom, off)
        rows.append((f"O{n:03d}", off, "dialog (no table pointer)", raw, None))
        n += 1
        off += len(raw)

    # Inline strings printed by call $0CE0 (bank 1).
    inline = set()
    n = 0
    i = rom.find(PRINT_CALL)
    while i != -1:
        off = i + 3
        raw = read_until_end(rom, off)
        inline.update(range(off, off + len(raw)))
        y, x = rom[i - 4], rom[i - 2]
        rows.append((f"I{n:03d}", off, f"inline x={x} y={y}", raw, None))
        n += 1
        i = rom.find(PRINT_CALL, i + 1)

    # Table strings in bank 1: runs of text bytes ending in <end>.
    n = 0
    i = BANK1[0]
    while i < BANK1[1]:
        if i in inline or not is_text(rom[i]):
            i += 1
            continue
        j = i
        while j < BANK1[1] and is_text(rom[j]):
            j += 1
        if rom[i] == 0xC9 and j - i > 2:  # a `ret` opcode just before the data
            i += 1
        body = rom[i:j]
        letters = sum(1 for b in body if 0xA6 <= b <= 0xDF or 0x41 <= b <= 0x5A)
        solid = len(body) - body.count(0x20)
        code_like = any(b in b";<>@[]^" for b in body)
        if (j < BANK1[1] and rom[j] == 0x65 and letters >= 2
                and letters >= 0.6 * solid and not code_like):
            rows.append((f"T{n:03d}", i, "table", rom[i:j + 1], None))
            n += 1
        i = j + 1

    # Name-entry character grid: 10 columns, ended by a 64 byte (not included).
    grid = 0x5CFB
    rows.append(("G000", grid, "name-entry grid", rom[grid:rom.index(0x64, grid)], None))

    # Window tilemaps in bank 4 (text stored as tile numbers).
    for wid, off, w, h, body in windows.windows(rom):
        rows.append((wid, off, f"window {w}x{h}", body, "/".join(windows.render(rom, body, w, h))))

    with open(out / "script.tsv", "w", encoding="utf-8") as tsv, open(
        out / "script.txt", "w", encoding="utf-8"
    ) as txt:
        tsv.write("id\trom_offset\tcpu_addr\tkind\traw_hex\tjapanese\tenglish\n")
        for sid, off, kind, raw, note in rows:
            jp = note if raw is None or kind.startswith("window") else decode(raw)
            hexs = "" if raw is None else raw.hex()
            tsv.write(f"{sid}\t0x{off:05X}\t{off // 0x4000:02X}:{cpu_addr(off):04X}"
                      f"\t{kind}\t{hexs}\t{jp}\t\n")
            if raw is None:
                txt.write(f"[{sid}] -> {note}\n\n")
                continue
            if kind.startswith("window"):
                grid = "\n    ".join(note.split("/"))
                txt.write(f"[{sid}] 0x{off:05X} ({kind}, tiles start 3 bytes after the header)\n    {grid}\n\n")
                continue
            body = jp.replace("<br>", "<br>\n    ").replace("<wait>", "<wait>\n    ")
            txt.write(f"[{sid}] 0x{off:05X} ({kind}, {len(raw)} bytes)\n    {body}\n\n")

    total = sum(len(r[3]) for r in rows if r[3] is not None)
    print(f"{len(rows)} strings, {total} bytes of text")


if __name__ == "__main__":
    main()
