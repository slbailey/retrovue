import os, re, json, pathlib

LEGACY_ROOT = pathlib.Path("docs/contracts/_legacy")
OUT_JSON = pathlib.Path("docs/contracts/_migration/legacy_extraction.json")

RULE_PATTERNS = [
    re.compile(r"\bLAW-[A-Z0-9\-]+"),
    re.compile(r"\bINV-[A-Z0-9\-]+"),
    re.compile(r"\bRULE-[A-Z0-9\-]+"),
    re.compile(r"\bSS-[0-9]{3}\b"),
]

def extract_rules(text: str):
    hits = set()
    for pat in RULE_PATTERNS:
        hits.update(pat.findall(text))
    return sorted(hits)

def main():
    rows = []
    for path in LEGACY_ROOT.rglob("*.md"):
        rel = path.as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        rules = extract_rules(text)
        # also grab “must/must not” sentences as candidates
        must_lines = []
        for line in text.splitlines():
            l = line.strip()
            if not l: continue
            if re.search(r"\bMUST\b|\bMUST NOT\b|\bSHALL\b|\bFORBIDDEN\b", l):
                must_lines.append(l[:240])
        rows.append({
            "file": rel,
            "rules_found": rules,
            "must_lines_sample": must_lines[:60],
            "bytes": len(text.encode("utf-8", errors="ignore")),
        })
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps({
        "legacy_root": str(LEGACY_ROOT),
        "count_files": len(rows),
        "files": rows,
    }, indent=2), encoding="utf-8")
    print(f"Wrote {OUT_JSON} with {len(rows)} legacy files.")

if __name__ == "__main__":
    main()
