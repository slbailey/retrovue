#!/usr/bin/env python3
from pathlib import Path
import re
import sys

root = Path(__file__).resolve().parents[1]
scan_dirs = [
    root / "src" / "blockplan",
    root / "src" / "producers",
    root / "src" / "runtime",
    root / "src" / "renderer",
]

# Exact-path allowlist for telemetry/diagnostics-only float usage.
# These files are outside cadence/fence/pacing decision loops.
telemetry_allow = {
    str(root / "src" / "runtime" / "TimingLoop.cpp"): "runtime stats/latency reporting",
    str(root / "src" / "runtime" / "PlayoutControl.cpp"): "control-plane latency percentiles",
    str(root / "src" / "runtime" / "ProgramFormat.cpp"): "format parsing helper",
    str(root / "src" / "renderer" / "ProgramOutput.cpp"): "renderer diagnostics",
    str(root / "src" / "renderer" / "FrameRenderer.cpp"): "renderer diagnostics",
}

forbidden_words = [r"\bfloat\b", r"\bdouble\b", r"ToDouble\s*\(", r"duration\s*<\s*double\s*>", r"av_q2d\s*\("]
float_lit = re.compile(r"\d+\.\d+([eE][+-]?\d+)?|\d+[eE][+-]?\d+")
word_res = [re.compile(p) for p in forbidden_words]
bad_tick = re.compile(r"\bint32_t\b[^\n]*(session_frame_index|fence_tick|block_start_tick|remaining_block_frames)|(session_frame_index|fence_tick|block_start_tick|remaining_block_frames)[^\n]*\bint32_t\b")
extra_patterns = [re.compile(r"1\.0\s*/"), re.compile(r"1000\.0\s*/"), re.compile(r"1000000\.0\s*/")]

violations = []

def strip_comments_and_strings(line: str, in_block: bool):
    """Strip comments and string literals to avoid false positives."""
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
        # Skip line comments
        if line.startswith("//", i):
            break
        # Skip block comments
        if line.startswith("/*", i):
            in_block = True
            i += 2
            continue
        # Skip string literals (both " and ')
        if line[i] in ('"', "'"):
            quote = line[i]
            i += 1
            while i < len(line):
                if line[i] == '\\' and i + 1 < len(line):
                    i += 2  # Skip escaped character
                    continue
                if line[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        out += line[i]
        i += 1
    return out, in_block

for d in scan_dirs:
    if not d.exists():
        continue
    for f in d.rglob("*"):
        if f.suffix not in (".cpp", ".hpp"):
            continue
        if ".bak" in f.name:
            continue
        allow_telemetry = str(f) in telemetry_allow
        in_block = False
        for n, raw in enumerate(f.read_text(errors="ignore").splitlines(), start=1):
            code, in_block = strip_comments_and_strings(raw, in_block)
            if not code.strip():
                continue
            if bad_tick.search(code):
                violations.append(f"{f}:{n}: int32 tick/budget type forbidden: {code.strip()}")
            hit = False
            for rx in word_res:
                if rx.search(code):
                    if allow_telemetry:
                        hit = True
                        break
                    violations.append(f"{f}:{n}: forbidden token: {code.strip()}")
                    hit = True
                    break
            if not hit and not allow_telemetry:
                if float_lit.search(code):
                    violations.append(f"{f}:{n}: floating literal forbidden: {code.strip()}")
                for rx in extra_patterns:
                    if rx.search(code):
                        violations.append(f"{f}:{n}: forbidden pacing literal pattern: {code.strip()}")
                        break

if violations:
    print("RationalFps hot-path guard FAILED", file=sys.stderr)
    for v in violations[:400]:
        print(v, file=sys.stderr)
    sys.exit(1)

print("RationalFps hot-path guard PASSED")
if telemetry_allow:
    print("ALLOWLIST:")
    for p, why in telemetry_allow.items():
        print(f" - {p}: {why}")
