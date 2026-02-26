#!/usr/bin/env python3
"""
Canonical Contract Seeder

Purpose:
- Collapse legacy phase/task duplicates
- Extract authoritative MUST/MUST NOT lines
- Seed canonical invariant docs with real legacy language
- Update migration ledger status to 🟡

Constraints:
- Docs only
- No code changes
- No test edits
"""

import pathlib
import re
import json
from collections import defaultdict

LEGACY_ROOT = pathlib.Path("docs/contracts/_legacy")
CANON_ROOT = pathlib.Path("docs/contracts")
LEDGER = CANON_ROOT / "_migration/LEDGER.md"

INVARIANT_PATTERN = re.compile(r"\b(INV|LAW|RULE)-[A-Z0-9\-]+")

def collect_legacy_invariants():
    index = defaultdict(lambda: {
        "files": set(),
        "must_lines": set(),
    })

    for md in LEGACY_ROOT.rglob("*.md"):
        text = md.read_text(encoding="utf-8", errors="ignore")

        ids = set(INVARIANT_PATTERN.findall(text))
        # full match extraction
        full_ids = set(re.findall(r"\b(?:INV|LAW|RULE)-[A-Z0-9\-]+", text))

        must_lines = []
        for line in text.splitlines():
            if "MUST" in line or "MUST NOT" in line or "FORBIDDEN" in line:
                l = line.strip()
                if len(l) < 300:
                    must_lines.append(l)

        for inv in full_ids:
            index[inv]["files"].add(md.as_posix())
            for ml in must_lines:
                index[inv]["must_lines"].add(ml)

    return index


def canonical_path_for(inv_id):
    if inv_id.startswith("LAW-"):
        return CANON_ROOT / "laws" / f"{inv_id}.md"
    if inv_id.startswith("RULE-"):
        return CANON_ROOT / "invariants/air" / f"{inv_id}.md"
    if inv_id.startswith("INV-P9") or "TS-EMISSION" in inv_id or "PCR" in inv_id:
        return CANON_ROOT / "invariants/sink" / f"{inv_id}.md"
    if inv_id.startswith("INV-P8") or "BOUNDARY" in inv_id or "SWITCH" in inv_id:
        return CANON_ROOT / "invariants/core" / f"{inv_id}.md"
    if inv_id.startswith("INV-P10"):
        return CANON_ROOT / "invariants/air" / f"{inv_id}.md"
    if inv_id.startswith("INV-TEARDOWN") or inv_id.startswith("INV-SESSION"):
        return CANON_ROOT / "invariants/core" / f"{inv_id}.md"
    return CANON_ROOT / "invariants/shared" / f"{inv_id}.md"


def seed_canonical_doc(inv_id, data):
    path = canonical_path_for(inv_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        existing = path.read_text()
    else:
        existing = f"# {inv_id}\n\n**Type:** INVARIANT\n\n"

    legacy_block = "\n".join(sorted(data["must_lines"]))

    content = f"""{existing}

---

## Legacy Extract (auto-seeded)

Sources:
{chr(10).join(sorted(data["files"]))}

### Authoritative MUST / MUST NOT statements
{legacy_block}

---

## Canonical Contract (TO BE WRITTEN)
Rewrite above into outcome-based invariant.

## Required Tests
- TODO: list contract tests

## Enforcement Evidence
- TODO: log lines / metrics
"""

    path.write_text(content, encoding="utf-8")
    print(f"Seeded {path}")


def update_ledger(inv_ids):
    if not LEDGER.exists():
        return

    text = LEDGER.read_text(encoding="utf-8")
    for inv in inv_ids:
        text = text.replace(f"| {inv} | 🔴 |", f"| {inv} | 🟡 |")
    LEDGER.write_text(text, encoding="utf-8")


def main():
    index = collect_legacy_invariants()

    print(f"Collected {len(index)} unique invariant IDs from legacy.")

    for inv_id, data in index.items():
        seed_canonical_doc(inv_id, data)

    update_ledger(index.keys())

    print("\nMigration seeding complete.")
    print("Now open canonical docs and rewrite outcome-based statements.")


if __name__ == "__main__":
    main()