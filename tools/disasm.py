#!/usr/bin/env python3
"""Minimal SM83 disassembler. Usage: disasm.py <rom> <file_offset_hex> <count> [opcodes.py]

Opcode names and lengths are read from PyBoy's opcodes.py (path as 4th arg).
"""
import ast, re, sys

def load_tables(path):
    src = open(path).read()
    lens = ast.literal_eval(re.search(r'OPCODE_LENGTHS = array\.array\("B", (\[.*?\])\)', src, re.S).group(1))
    names = ast.literal_eval(re.search(r"CPU_COMMANDS = (\[.*?\])", src, re.S).group(1))
    return lens, names

def main():
    rom = open(sys.argv[1], "rb").read()
    off, count = int(sys.argv[2], 16), int(sys.argv[3])
    lens, names = load_tables(sys.argv[4])
    for _ in range(count):
        op = rom[off]
        if op == 0xCB:
            n, name = 2, names[0x100 + rom[off + 1]]
        else:
            n, name = lens[op], names[op]
        b = rom[off:off + n]
        if "d16" in name or "a16" in name:
            v = "$%04X" % (b[1] | b[2] << 8)
            name = name.replace("d16", v).replace("a16", v)
        elif "r8" in name:
            t = (off if off < 0x4000 else 0x4000 + off % 0x4000) + 2 + (b[1] - 256 if b[1] > 127 else b[1])
            name = name.replace("r8", "$%04X" % t)
        elif "d8" in name or "a8" in name:
            name = name.replace("d8", "$%02X" % b[1]).replace("a8", "$FF%02X" % b[1])
        cpu = off if off < 0x4000 else 0x4000 + off % 0x4000
        print("%05X %04X  %-9s %s" % (off, cpu, b.hex(), name or "db $%02X" % op))
        off += n

main()
