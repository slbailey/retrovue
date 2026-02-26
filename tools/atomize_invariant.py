#!/usr/bin/env python3
"""
Invariant Atomizer

Purpose:
Split large merged invariants (INV-P8.md, INV-P9-STEADY.md)
into candidate atomic invariant files based on section boundaries.

This does NOT delete the original file.
It creates suggested atomic files under the same directory.
"""

import pathlib
import re

ROOT = pathlib.Path("docs/contracts/invariants")

TARGETS = [
    "core/INV-P8.md",
    "sink/INV-P9-STEADY.md"
]

SECTION_PATTERN = re.compile(r"\n##\s+(.+?)\n")

def atomize(file_path):
    full_path = ROOT / file_path
    if not full_path.exists():
        print(f"Missing: {full_path}")
        return

    text = full_path.read_text()

    sections = SECTION_PATTERN.split(text)

    if len(sections) < 3:
        print(f"No sections detected in {file_path}")
        return

    base_dir = full_path.parent

    print(f"Atomizing {file_path}")

    for i in range(1, len(sections), 2):
        title = sections[i].strip()
        content = sections[i+1]

        safe_name = title.upper().replace(" ", "-").replace("/", "-")
        safe_name = re.sub(r"[^A-Z0-9\-]", "", safe_name)

        new_file = base_dir / f"{safe_name}.md"

        new_text = f"# {safe_name}\n\n{content.strip()}\n"

        new_file.write_text(new_text)
        print(f"Created {new_file}")

def main():
    for t in TARGETS:
        atomize(t)

    print("Atomization complete (review required).")

if __name__ == "__main__":
    main()