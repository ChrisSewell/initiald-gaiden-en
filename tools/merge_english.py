#!/usr/bin/env python3
"""Merge script/en_dialog.txt, script/en_strings.txt and script/en_windows.txt
into the english column of script/script.tsv.

Usage: python3 -I merge_english.py <project_dir>

Checks every dialog box against the 8x8 font limits: 18 characters per line,
3 lines per box. Checks the other strings against their original byte size:
table records and the name grid must fit, while inline strings that don't are
listed as needing relocation. Exits non-zero on any error. Also flags
characters the font can't draw yet (see README).
"""
import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import windows  # noqa: E402

LINE_MAX = 18
BOX_LINES = 3
# Characters the patched font can draw. ASCII with real glyphs in the original
# font (no comma, slash, double quote or backslash there), plus the lowercase
# and comma tiles build_patch.py adds, plus the kept kana punctuation.
DRAWABLE = set(" !#$%&'()*+-.0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ_")
DRAWABLE |= set("abcdefghijklmnopqrstuvwxyz,")
DRAWABLE |= set("。「」、・")


def load_english(path):
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        sid, text = line.split(" = ", 1)
        out[sid.strip()] = text.strip()
    return out


def to_tagged(text):
    if text.startswith("RAW "):
        return text[4:]
    boxes = [b.strip() for b in text.split("//")]
    body = "<wait><clear>".join("<br>".join(l.strip() for l in b.split("|")) for b in boxes)
    return f"<open>{body}<wait><end>"


def check(sid, tagged):
    problems = []
    for box in re.split(r"<wait><clear>|<wait>", tagged):
        lines = [l for l in re.sub(r"<(open|end)>", "", box).split("<br>") if l != ""]
        n = len(lines)
        if n > BOX_LINES and sid != "S207":  # S207 keeps the original's 4-line box
            problems.append(f"{n} lines in box: {lines}")
        for l in lines:
            if len(l) > LINE_MAX:
                problems.append(f"{len(l)} chars: {l!r}")
            bad = sorted(set(l) - DRAWABLE)
            if bad:
                problems.append(f"undrawable {bad}: {l!r}")
    return problems


def fit_string(row, text):
    """English for a non-dialog row, plus (errors, notes)."""
    raw = bytes.fromhex(row["raw_hex"])
    grid = row["id"].startswith("G")
    budget = len(raw) if grid else len(raw) - 1
    if text == "KEEP":
        return row["japanese"], [], []
    if grid:
        if not text.startswith("GRID "):
            return "", [f"{row['id']}: grid needs GRID rows"], []
        cells = "".join(text[5:].split("|"))
        errs = [] if len(cells) == budget else [
            f"{row['id']}: grid has {len(cells)} cells, needs {budget}"]
        bad = sorted(set(cells) - DRAWABLE)
        if bad:
            errs.append(f"{row['id']}: undrawable {bad}")
        return cells, errs, []
    if text.startswith("^"):
        body = text[1:]
        pad = max(budget - len(body), 0)
        body = " " * (pad // 2) + body + " " * (pad - pad // 2)
    else:
        body = text.ljust(budget)
    errs, notes = [], []
    bad = sorted(set(body) - DRAWABLE)
    if bad:
        errs.append(f"{row['id']}: undrawable {bad}: {body!r}")
    over = len(body) - budget
    if over > 0:
        msg = f"{row['id']}: {body.strip()!r} is {over} byte(s) over its {budget}"
        if row["id"].startswith("I"):
            notes.append(msg + " -> relocate")
        else:
            errs.append(msg + " (fixed record)")
    return body + "<end>", errs, notes


def main():
    root = Path(sys.argv[1])
    tsv = root / "script" / "script.tsv"
    english = load_english(root / "script" / "en_dialog.txt")
    strings = load_english(root / "script" / "en_strings.txt")
    win_edits = windows.parse_edits((root / "script" / "en_windows.txt").read_text(encoding="utf-8"))

    with open(tsv, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    fields = list(rows[0].keys())

    by_id = {r["id"]: r for r in rows}
    missing, errors, notes, filled = [], [], [], 0
    for r in rows:
        if r["kind"].startswith("window"):
            w = int(r["kind"].split()[1].split("x")[0])
            new, probs = windows.apply_edits(r["japanese"].split("/"), w, win_edits.get(r["id"], {}))
            left = sorted({c for row in new for c in row if "぀" <= c <= "ヿ" or c in "゛゜"})
            if left:
                probs.append(f"still has Japanese {left}")
            bad = sorted({c for row in new for c in row}
                         - DRAWABLE - set(windows.BOX_TILE) - {windows.KEEP, windows.SPACE} - set(left))
            if bad:
                probs.append(f"undrawable {bad}")
            errors += [f"{r['id']}: {p}" for p in probs]
            r["english"] = "/".join(new)
            filled += 1
            continue
        if not r["kind"].startswith("dialog"):
            if r["id"] not in strings:
                missing.append(r["id"])
                continue
            r["english"], errs, note = fit_string(r, strings[r["id"]])
            errors += errs
            notes += note
            filled += 1
            continue
        src = r["id"]
        m = re.match(r"same as (\S+)", r["japanese"])
        if m:
            src = m.group(1)
        if src not in english:
            missing.append(r["id"])
            continue
        tagged = to_tagged(english[src])
        r["english"] = tagged
        filled += 1
        if src == r["id"]:
            errors += [f"{r['id']}: {p}" for p in check(r["id"], tagged)]

    # S208 is the tail of S207 in ROM; their English must agree.
    if "S207" in by_id and "S208" in by_id:
        if not by_id["S207"]["english"].endswith(by_id["S208"]["english"]):
            errors.append("S207 must end with S208's text (they share bytes in ROM)")

    with open(tsv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)

    print(f"filled {filled} rows; missing {len(missing)}: {missing}")
    if notes:
        print(f"{len(notes)} inline string(s) need relocating:")
        for n in notes:
            print("  ", n)
    for e in errors:
        print("  ", e)
    sys.exit(1 if errors or missing else 0)


if __name__ == "__main__":
    main()
