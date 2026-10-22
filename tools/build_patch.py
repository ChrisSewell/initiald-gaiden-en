#!/usr/bin/env python3
"""Build the English ROM and an IPS patch from script/script.tsv.

Usage: python3 -I build_patch.py <original.gb> <project_dir> <out.gb>

Run tools/merge_english.py first so the english column is current.

What it does:
  1. Expands the ROM from 256 KB to 512 KB (MBC1, header byte 0x148 = 04).
  2. Draws lowercase a-z over kana tiles B1-CA and a comma over CB in the
     dialog font at 0x14000 (tile = position of the code in the table at $0DCB).
  3. Moves the dialog script to bank 0x10: a new pointer table at $4000, with
     the text after it. Patches the dialog routine at $0CE6 to use it.
  4. Writes non-dialog strings in place; inline strings that no longer fit
     move to free space at the end of bank 1, and their call $0CE0 sites
     become `ld hl,addr / call $0D05`.
  5. Rewrites the bank 4 window tilemaps (text as tile numbers) in place.
  6. Redraws the kanji/kana menu graphics in English (graphics/menus.json).
  7. Fixes the header and global checksums and writes <out>.ips beside <out>.
"""
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import menus  # noqa: E402
import windows  # noqa: E402

FONT = 0x14000
CHAR_TABLE = 0x0DCB
SCRIPT_BANK = 0x10
SCRIPT_TABLE_CPU = 0x4000
SCRIPT_COUNT = 224
DIALOG_DE = 0x0CEB      # operand of LD DE,$5600
DIALOG_BANK = 0x0CF2    # operand of LD A,$02
INLINE_FREE = 0x7F00    # end of bank 1, unused 0xFF bytes
PRINT = 0x0D05

TAGS = {"open": 0x62, "clear": 0x63, "end": 0x65, "br": 0x6C, "wait": 0x74}
LOWER = {chr(ord("a") + i): 0xB1 + i for i in range(26)}
SPECIAL = {",": 0xCB, "。": 0xA1, "「": 0xA2, "」": 0xA3, "、": 0xA4, "・": 0xA5}


def encode(text):
    out = bytearray()
    for tag, ch in re.findall(r"<([a-z]+)>|(.)", text, re.S):
        if tag:
            out.append(TAGS[tag])
        elif ch in LOWER:
            out.append(LOWER[ch])
        elif ch in SPECIAL:
            out.append(SPECIAL[ch])
        elif 0x20 <= ord(ch) <= 0x5F and ch not in ',/"\\':
            out.append(ord(ch))
        else:
            raise ValueError(f"no glyph for {ch!r} in {text!r}")
    return bytes(out)


def load_glyphs(path):
    glyphs, name, rows = {}, None, []
    for line in path.read_text().splitlines():
        if line.startswith("# ") or not line.strip():  # glyph rows can start with '#'
            continue
        if len(line.strip()) == 1:
            name, rows = line.strip(), []
            glyphs[name] = rows
        else:
            rows.append(line.strip())
    return glyphs


COMMA = ["........"] * 5 + ["...##...", "...##...", "..##...."]


def tile_bytes(rows):
    assert len(rows) == 8, rows
    out = bytearray()
    for r in rows:
        v = int(r.replace("#", "1").replace(".", "0"), 2)
        out += bytes([v, v])  # both planes: color 3
    return bytes(out)


def write_font(rom, glyphs):
    table = list(rom[CHAR_TABLE:CHAR_TABLE + 128])
    pairs = [(LOWER[c], glyphs[c]) for c in LOWER] + [(SPECIAL[","], COMMA)]
    for code, rows in pairs:
        idx = table.index(code)
        rom[FONT + idx * 16:FONT + idx * 16 + 16] = tile_bytes(rows)


def build_script_bank(rom, rows):
    base = SCRIPT_BANK * 0x4000
    text_at = SCRIPT_TABLE_CPU + SCRIPT_COUNT * 2
    blob = bytearray()
    placed = {}
    pointers = []
    for r in rows:
        if not r["id"].startswith("S"):
            continue
        m = re.match(r"same as (\S+)", r["japanese"])
        src = m.group(1) if m else r["id"]
        if src not in placed:
            placed[src] = text_at + len(blob)
            blob += encode(next(x for x in rows if x["id"] == src)["english"])
        pointers.append(placed[src])
    assert len(pointers) == SCRIPT_COUNT
    end = text_at + len(blob)
    assert end <= 0x8000, f"script overflows bank: ends at ${end:04X}"
    for i, p in enumerate(pointers):
        rom[base + 2 * i:base + 2 * i + 2] = p.to_bytes(2, "little")
    t = base + (text_at - 0x4000)
    rom[t:t + len(blob)] = blob
    rom[DIALOG_DE:DIALOG_DE + 2] = SCRIPT_TABLE_CPU.to_bytes(2, "little")
    rom[DIALOG_BANK] = SCRIPT_BANK
    return len(blob), end


def write_strings(rom, rows):
    free = INLINE_FREE
    moved = []
    for r in rows:
        rid = r["id"]
        if rid[0] not in "ITG" or r["english"] == r["japanese"]:
            continue  # KEEP rows
        off = int(r["rom_offset"], 16)
        old = bytes.fromhex(r["raw_hex"])
        new = encode(r["english"])
        if len(new) <= len(old):
            rom[off:off + len(new)] = new
            continue
        assert rid.startswith("I"), f"{rid} does not fit and can't move"
        call = off - 3
        assert rom[call:call + 3] == b"\xcd\xe0\x0c", rid
        cpu = 0x4000 + free % 0x4000
        rom[free:free + len(new)] = new
        free += len(new)
        assert free <= 0x8000
        span = 3 + len(old)
        stub = b"\x21" + cpu.to_bytes(2, "little") + b"\xcd" + PRINT.to_bytes(2, "little")
        rom[call:call + span] = stub + b"\x00" * (span - len(stub))
        moved.append(rid)
    return moved


def write_windows(rom, rows):
    count = 0
    for r in rows:
        if not r["kind"].startswith("window"):
            continue
        w = int(r["kind"].split()[1].split("x")[0])
        body = bytes.fromhex(r["raw_hex"])
        tiles = windows.encode_rows(rom, r["english"].split("/"), body, w, lambda c: encode(c)[0])
        assert len(tiles) == len(body), r["id"]
        off = int(r["rom_offset"], 16) + 3
        rom[off:off + len(tiles)] = tiles
        count += 1
    return count


def fix_checksums(rom):
    x = 0
    for b in rom[0x134:0x14D]:
        x = (x - b - 1) & 0xFF
    rom[0x14D] = x
    s = (sum(rom) - rom[0x14E] - rom[0x14F]) & 0xFFFF
    rom[0x14E:0x150] = s.to_bytes(2, "big")


def write_ips(orig, new, path):
    orig = orig + b"\xff" * (len(new) - len(orig))
    out = bytearray(b"PATCH")
    i = 0
    while i < len(new):
        if new[i] == orig[i]:
            i += 1
            continue
        j = i
        while j < len(new) and j - i < 0xFFFF and (new[j] != orig[j] or (
                j + 1 < len(new) and new[j + 1] != orig[j + 1])):
            j += 1
        if i == 0x454F46:  # would read as "EOF"
            i -= 1
        out += i.to_bytes(3, "big") + (j - i).to_bytes(2, "big") + new[i:j]
        i = j
    if len(new) > len(orig.rstrip(b"\xff")) and new[-1] == 0xFF:
        # make sure patchers grow the file to full size
        out += (len(new) - 1).to_bytes(3, "big") + (1).to_bytes(2, "big") + b"\xff"
    out += b"EOF"
    path.write_bytes(out)


def main():
    src, root, dst = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    orig = src.read_bytes()
    assert len(orig) == 0x40000 and orig[0x148] == 0x03, "expected the 256 KB original"
    with open(root / "script" / "script.tsv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))

    rom = bytearray(orig) + bytearray(b"\xff" * 0x40000)
    rom[0x148] = 0x04
    write_font(rom, load_glyphs(root / "font" / "lowercase.txt"))
    size, end = build_script_bank(rom, rows)
    moved = write_strings(rom, rows)
    nwin = write_windows(rom, rows)
    nmenu, problems = menus.apply_all(rom, root)
    if problems:
        sys.exit("menu graphics:\n  " + "\n  ".join(problems))
    fix_checksums(rom)

    dst.write_bytes(rom)
    write_ips(orig, bytes(rom), dst.with_suffix(".ips"))
    print(f"script: {size} bytes in bank ${SCRIPT_BANK:02X}, ends at ${end:04X}")
    print(f"relocated inline strings: {', '.join(moved)}")
    print(f"rewrote {nwin} bank 4 windows")
    print(f"redrew {nmenu} menu graphics")
    print(f"wrote {dst} and {dst.with_suffix('.ips')}")


if __name__ == "__main__":
    main()
