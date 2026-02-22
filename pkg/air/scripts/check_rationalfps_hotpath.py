#!/usr/bin/env python3
from pathlib import Path
import re
import sys

root = Path(__file__).resolve().parents[1]
scan_dirs = [root / "src" / "blockplan"]

forbidden_words = [r"\bfloat\b", r"\bdouble\b", r"ToDouble\s*\(", r"duration\s*<\s*double\s*>"]
float_lit = re.compile(r"\d+\.\d+([eE][+-]?\d+)?|\d+[eE][+-]?\d+")
word_res = [re.compile(p) for p in forbidden_words]
bad_tick = re.compile(r"\bint32_t\b[^\n]*(session_frame_index|fence_tick|block_start_tick|remaining_block_frames)|(session_frame_index|fence_tick|block_start_tick|remaining_block_frames)[^\n]*\bint32_t\b")

violations = []

def strip_comments(line: str, in_block: bool):
    out = ""
    i = 0
    while i < len(line):
        if in_block:
            j = line.find("*/", i)
            if j == -1:
                return out, True
            i = j + 2
            in_block = False
            continue
        if line.startswith("//", i):
            break
        if line.startswith("/*", i):
            in_block = True
            i += 2
            continue
        out += line[i]
        i += 1
    return out, in_block

for d in scan_dirs:
    for f in d.rglob("*"):
        if f.suffix not in (".cpp", ".hpp"):
            continue
        if ".bak" in f.name:
            continue
        in_block = False
        for n, raw in enumerate(f.read_text(errors="ignore").splitlines(), start=1):
            code, in_block = strip_comments(raw, in_block)
            if not code.strip():
                continue
            if bad_tick.search(code):
                violations.append(f"{f}:{n}: int32 tick/budget type forbidden: {code.strip()}")
            hit = False
            for rx in word_res:
                if rx.search(code):
                    violations.append(f"{f}:{n}: forbidden token: {code.strip()}")
                    hit = True
                    break
            if not hit and float_lit.search(code):
                violations.append(f"{f}:{n}: floating literal forbidden: {code.strip()}")

if violations:
    print("RationalFps hot-path guard FAILED", file=sys.stderr)
    for v in violations[:200]:
        print(v, file=sys.stderr)
    sys.exit(1)

print("RationalFps hot-path guard PASSED")
