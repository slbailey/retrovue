#!/usr/bin/env python3
"""
Invariant ID Normalizer

Purpose:
- Collapse numbered variants (INV-P9-STEADY-001..008 → INV-P9-STEADY)
- Remove malformed IDs (INV-P8-.md, INV-SEGMENT-.md)
- Merge legacy extract blocks into single canonical file
"""

import pathlib
import re
from collections import defaultdict

ROOT = pathlib.Path("docs/contracts/invariants")

NUMBERED_PATTERN = re.compile(r"(INV-[A-Z0-9\-]+)-\d+$")

def find_invariants():
    files = list(ROOT.rglob("INV-*.md"))
    groups = defaultdict(list)

    for f in files:
        name = f.stem

        if name.endswith("-"):
            print(f"Deleting malformed ID: {f}")
            f.unlink()
            continue

        m = NUMBERED_PATTERN.match(name)
        if m:
            base = m.group(1)
            groups[base].append(f)
        else:
            groups[name].append(f)

    return groups


def merge_group(base, files):
    if len(files) <= 1:
        return

    print(f"Merging {len(files)} variants into {base}.md")

    canonical_path = files[0].parent / f"{base}.md"

    merged_text = f"# {base}\n\n"

    for f in files:
        merged_text += f"\n---\n## Source: {f.name}\n"
        merged_text += f.read_text()

    canonical_path.write_text(merged_text)

    for f in files:
        if f != canonical_path:
            f.unlink()


def main():
    groups = find_invariants()

    for base, files in groups.items():
        merge_group(base, files)

    print("Normalization complete.")


if __name__ == "__main__":
    main()