#!/usr/bin/env python3
"""Quieter, lower tire squeal for Initial D Gaiden (GB).

Usage: python3 -I build_squeal_mod.py <rom.gb> <out_dir>

The tire squeal is three music-sequencer tracks (9, 10, 11) in bank 2, played
on channel 1 and restarted every 7 frames while the tires slip:
  track 9   wheelspin at launch    notes 45/47     (3.5-4.0 kHz)
  track 10  cornering drift        notes 48/47/46  (3.8-4.2 kHz)
  track 11  long slide             sweep, then 48/49 (up to 4.4 kHz)
Track table: $444D in bank 2 (file 0x844D). Each track header is a byte then
four little-endian channel offsets from the track start. In a channel stream,
F6 xx sets channel 1's volume envelope (NR12), a byte under F0 is a note
(bit 7 set = reuse the previous length, otherwise two length bytes follow),
and FF ends the stream.

This mod drops every note two octaves (24 semitones, so about 0.9-1.1 kHz)
and lowers the volume from 12 to 5. The streams keep their length, so they are
rewritten in place. Nothing else changes, so the patch applies to the original
Japanese ROM and to the English translation alike.

Writes <out_dir>/squeal-low-quiet.ips, plus <out_dir>/<rom name> (squeal mod).gb.
"""
import struct
import sys
from pathlib import Path

TRACK_TABLE = 0x444D
TRACKS = (9, 10, 11)
SEMITONES = -24
VOLUME = 0x50   # NR12: volume 5, no envelope change (original C0 = volume 12)


def file_off(cpu):
    return 0x8000 + cpu - 0x4000  # bank 2


def ch1_stream(rom, k):
    base = struct.unpack_from("<H", rom, file_off(TRACK_TABLE) + 2 * k)[0]
    off = struct.unpack_from("<H", rom, file_off(base) + 1)[0]
    start = file_off(base + off)
    return start, rom.index(0xFF, start) + 1


def soften(stream):
    out, i = bytearray(), 0
    while i < len(stream):
        b = stream[i]
        if b == 0xF6:                       # volume: keep "off" (00) as is
            out += bytes([0xF6, VOLUME if stream[i + 1] else 0])
            i += 2
        elif b >= 0xF0:
            out.append(b)
            i += 1
        else:
            note = (b & 0x7F) + SEMITONES
            assert 0 <= note < 0x70, f"note {b:02x} out of range"
            out.append((b & 0x80) | note)
            i += 1
            if not b & 0x80:                # explicit length follows
                out += stream[i:i + 2]
                i += 2
    assert len(out) == len(stream)
    return bytes(out)


def write_ips(orig, new, path):
    out, i = bytearray(b"PATCH"), 0
    while i < len(new):
        if new[i] == orig[i]:
            i += 1
            continue
        j = i
        while j < len(new) and new[j] != orig[j]:
            j += 1
        out += i.to_bytes(3, "big") + (j - i).to_bytes(2, "big") + new[i:j]
        i = j
    path.write_bytes(out + b"EOF")


def main():
    src, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
    orig = src.read_bytes()
    assert orig[0x134:0x144] == b"INITIAL D GAIDEN", "not Initial D Gaiden"
    rom = bytearray(orig)
    for k in TRACKS:
        s, e = ch1_stream(rom, k)
        assert rom[s:s + 2] == b"\xf6\xc0", f"track {k} already modified?"
        rom[s:e] = soften(rom[s:e])
        print(f"track {k}: {orig[s:e].hex(' ')}\n      -> {rom[s:e].hex(' ')}")
    out_dir.mkdir(parents=True, exist_ok=True)
    write_ips(orig, rom, out_dir / "squeal-low-quiet.ips")
    (out_dir / f"{src.stem} (squeal mod).gb").write_bytes(rom)
    print(f"wrote {out_dir / 'squeal-low-quiet.ips'}")


if __name__ == "__main__":
    main()
