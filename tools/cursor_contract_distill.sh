#!/usr/bin/env bash
# =====================================================================
# Cursor Script: Contract Distillation + Legacy Phase Purge (Docs-only)
# Goal:
#   1) quarantine legacy PHASE* docs (keep history, remove from canon)
#   2) extract still-relevant rules into a NEW authoritative structure
#   3) create a migration ledger so nothing “falls on the floor”
#
# Constraints:
#   - NO code changes
#   - NO test changes
#   - docs/contracts only
#
# Usage (from repo root):
#   bash tools/cursor_contract_distill.sh
# Then open docs/contracts/README.md + docs/contracts/_migration/LEDGER.md
# =====================================================================

set -euo pipefail

ROOT="$(pwd)"
DC="docs/contracts"

if [[ ! -d "$DC" ]]; then
  echo "ERROR: expected $DC/ to exist (run from repo root)."
  exit 1
fi

echo "==> [1/8] Create new authoritative contract structure"
mkdir -p \
  "$DC/README.d" \
  "$DC/laws" \
  "$DC/invariants/air" \
  "$DC/invariants/core" \
  "$DC/invariants/sink" \
  "$DC/invariants/shared" \
  "$DC/diagnostics" \
  "$DC/components" \
  "$DC/coordination" \
  "$DC/_legacy/phases" \
  "$DC/_legacy/tasks" \
  "$DC/_legacy/coordination" \
  "$DC/_migration"

echo "==> [2/8] Quarantine legacy PHASE docs (keep, but remove from canon)"
# PHASE root docs
for f in "$DC"/PHASE*.md; do
  [[ -e "$f" ]] || continue
  mv "$f" "$DC/_legacy/phases/"
done

# Legacy phase tasks (these are “old world” artifacts)
if [[ -d "$DC/tasks" ]]; then
  # move only phase task trees, keep other tasks if present
  mkdir -p "$DC/_legacy/tasks"
  shopt -s nullglob
  for d in "$DC/tasks"/phase*; do
    mv "$d" "$DC/_legacy/tasks/"
  done
  shopt -u nullglob
fi

# Legacy coordination phase docs
if [[ -d "$DC/coordination" ]]; then
  shopt -s nullglob
  for f in "$DC/coordination"/PHASE*.md "$DC/coordination"/PHASE*_*.md "$DC/coordination"/PHASE*/*.md; do
    [[ -e "$f" ]] || continue
    mkdir -p "$DC/_legacy/coordination/$(dirname "$(basename "$f")")" >/dev/null 2>&1 || true
    mv "$f" "$DC/_legacy/coordination/"
  done
  shopt -u nullglob
fi

echo "==> [3/8] Add canonical README + index entrypoint"
cat > "$DC/README.md" <<'MD'
# Contracts (Authoritative)

This directory is the **only canonical source of runtime guarantees** for playout.

## Canonical taxonomy
- **Laws**: non-negotiable “physics” of the system. If a law conflicts with anything else, the law wins.
- **Invariants**: testable, enforceable runtime guarantees. Every invariant MUST list required contract tests.
- **Diagnostics**: observability-only rules (logs/metrics), not correctness by themselves.
- **Legacy**: archived phase docs kept for archaeology only. Not authoritative.

## Navigation
- Laws: `docs/contracts/laws/`
- Invariants:
  - AIR: `docs/contracts/invariants/air/`
  - Core: `docs/contracts/invariants/core/`
  - Sink: `docs/contracts/invariants/sink/`
  - Shared: `docs/contracts/invariants/shared/`
- Migration ledger (track what was extracted and where it landed):
  - `docs/contracts/_migration/LEDGER.md`

## Rules of the road
1) A contract is **outcomes, not procedures**.  
2) Every invariant MUST list required tests under `tests/contracts/` (or `pkg/*/tests/contracts/`).  
3) Legacy phase docs are **not** allowed to be referenced by new work.
MD

echo "==> [4/8] Create migration ledger template"
cat > "$DC/_migration/LEDGER.md" <<'MD'
# Legacy Contract Migration Ledger

**Purpose:** make sure every still-relevant guarantee from legacy PHASE docs is migrated into the new canonical structure.

## Status tags
- ✅ Migrated (canonical doc exists + legacy text copied + tests listed)
- 🟡 Migrated but needs tests list
- 🔴 Not migrated (still only exists in legacy)
- 🧊 Deprecated / Not in use (explicitly retired)

## Ledger (seeded from legacy extraction)
This file is intentionally verbose. We will delete rows only when they are explicitly marked 🧊.

> NOTE: If an item has a PROPOSED_NEW_ID, assign a final canonical ID as part of migration
> (do not leave PROPOSED_NEW_ID in canon).

### Laws (candidate set)
| Legacy source | Legacy statement (short) | Proposed canonical doc | Status | Notes |
|---|---|---|---|---|
| PHASE1.md | Output liveness (pad within bounded time; never stall) | laws/LAW-OUTPUT-LIVENESS.md | 🔴 | |
| PHASE1.md | Video decodability (IDR gate resets on segment switch) | laws/LAW-VIDEO-DECODABILITY.md | 🔴 | |
| PHASE8.md | MasterClock only source of “now”; epoch fixed per session | laws/LAW-CLOCK-MASTERCLOCK.md | 🔴 | |
| PHASE11.md | Authority hierarchy: clock authority supersedes frame completion | laws/LAW-AUTHORITY-HIERARCHY.md | 🔴 | |

### Invariants (candidate set)
| Legacy source | Legacy ID / label | Proposed canonical doc | Status | Notes |
|---|---|---|---|---|
| PHASE1.md | INV-PAD-PRODUCER-007 | invariants/air/INV-PAD-PRODUCER-007.md | 🔴 | already referenced elsewhere; migrate phrasing + required tests |
| PHASE10_FLOW_CONTROL.md | RULE-P10-DECODE-GATE | invariants/air/RULE-P10-DECODE-GATE.md | 🔴 | slot-based gating, no hysteresis |
| PHASE10_FLOW_CONTROL.md | INV-P10-BACKPRESSURE-SYMMETRIC | invariants/air/INV-P10-BACKPRESSURE-SYMMETRIC.md | 🔴 | ensure aligns with code + diagnostics |
| PHASE10_FLOW_CONTROL.md | INV-P10-PCR-PACED-MUX | invariants/sink/INV-P10-PCR-PACED-MUX.md | 🔴 | time-driven mux algorithm |
| PHASE9_STEADY_STATE_CORRECTNESS.md | INV-P9-STEADY-* set | invariants/sink/INV-P9-STEADY-*.md | 🔴 | split into discrete invariants, keep one-per-file |
| PHASE12.md | INV-SESSION-CREATION-UNGATED-001 | invariants/core/INV-SESSION-CREATION-UNGATED-001.md | 🔴 | index-only today; needs full contract |
| PHASE11.md | INV-STARTUP-BOUNDARY-FEASIBILITY-001 | invariants/core/INV-STARTUP-BOUNDARY-FEASIBILITY-001.md | 🔴 | index-only today; needs full contract |

### Diagnostics (candidate set)
| Legacy source | Legacy label | Proposed canonical doc | Status | Notes |
|---|---|---|---|---|
| PHASE9_STEADY_STATE_CORRECTNESS.md | “pad emitted with depth ≥ 10 is violation” | diagnostics/DIAG-NO-PAD-WHILE-DEPTH-HIGH.md | 🔴 | classify as diagnostic invariant |
MD

echo "==> [5/8] Create canonical doc templates (authoritative targets)"
# Helper: write a template doc if it doesn't exist yet
write_doc () {
  local path="$1"
  local title="$2"
  local owner="$3"
  local kind="$4"
  shift 4
  if [[ -f "$path" ]]; then return; fi
  cat > "$path" <<MD
# ${title}

**Type:** ${kind}  
**Owner:** ${owner}

## Contract statement (canonical)
- TODO: Write the outcome-focused statement(s) here.

## Required tests
> List the required contract tests (path + test name).
- TODO

## Required enforcement / evidence
> Logs/metrics that prove this is being enforced.
- TODO

## Legacy sources (archival quotes)
> Copy the relevant legacy text here verbatim (as evidence), then adapt wording above.
$*
MD
}

# Laws
write_doc "$DC/laws/LAW-OUTPUT-LIVENESS.md" "LAW-OUTPUT-LIVENESS" "AIR (ProgramOutput)" "LAW" ""
write_doc "$DC/laws/LAW-VIDEO-DECODABILITY.md" "LAW-VIDEO-DECODABILITY" "AIR" "LAW" ""
write_doc "$DC/laws/LAW-CLOCK-MASTERCLOCK.md" "LAW-CLOCK-MASTERCLOCK" "AIR" "LAW" ""
write_doc "$DC/laws/LAW-AUTHORITY-HIERARCHY.md" "LAW-AUTHORITY-HIERARCHY" "Core + AIR" "LAW" ""

# Invariants (high-impact first)
write_doc "$DC/invariants/air/INV-PAD-PRODUCER-007.md" "INV-PAD-PRODUCER-007 (Content-before-pad gate)" "AIR" "INVARIANT" ""
write_doc "$DC/invariants/air/RULE-P10-DECODE-GATE.md" "RULE-P10-DECODE-GATE (Slot-based decode gating)" "AIR (Producer)" "INVARIANT" ""
write_doc "$DC/invariants/air/INV-P10-BACKPRESSURE-SYMMETRIC.md" "INV-P10-BACKPRESSURE-SYMMETRIC" "AIR" "INVARIANT" ""
write_doc "$DC/invariants/sink/INV-P10-PCR-PACED-MUX.md" "INV-P10-PCR-PACED-MUX" "Sink (Mux)" "INVARIANT" ""
write_doc "$DC/invariants/sink/INV-P9-TS-EMISSION-LIVENESS.md" "INV-P9-TS-EMISSION-LIVENESS" "Sink" "INVARIANT" ""

# Core invariants you called out as “index-only / missing sections”
write_doc "$DC/invariants/core/INV-SESSION-CREATION-UNGATED-001.md" "INV-SESSION-CREATION-UNGATED-001" "Core" "INVARIANT" ""
write_doc "$DC/invariants/core/INV-STARTUP-BOUNDARY-FEASIBILITY-001.md" "INV-STARTUP-BOUNDARY-FEASIBILITY-001" "Core" "INVARIANT" ""

# Diagnostics
write_doc "$DC/diagnostics/DIAG-NO-PAD-WHILE-DEPTH-HIGH.md" "DIAG-NO-PAD-WHILE-DEPTH-HIGH" "AIR (ProgramOutput)" "DIAGNOSTIC" ""

echo "==> [6/8] Generate an extraction report from quarantined legacy docs"
mkdir -p tools
cat > "tools/extract_legacy_contracts.py" <<'PY'
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
PY

python3 tools/extract_legacy_contracts.py

echo "==> [7/8] Create a human-readable summary from extraction JSON"
cat > "tools/render_legacy_extraction.py" <<'PY'
import json, pathlib

IN = pathlib.Path("docs/contracts/_migration/legacy_extraction.json")
OUT = pathlib.Path("docs/contracts/_migration/legacy_extraction_summary.md")

data = json.loads(IN.read_text(encoding="utf-8"))
lines = []
lines.append("# Legacy Extraction Summary")
lines.append("")
lines.append(f"Files scanned: **{data['count_files']}**")
lines.append("")
for f in sorted(data["files"], key=lambda x: x["file"]):
    lines.append(f"## {f['file']}")
    lines.append(f"- Bytes: {f['bytes']}")
    lines.append(f"- IDs found: {', '.join(f['rules_found']) if f['rules_found'] else '(none)'}")
    if f["must_lines_sample"]:
        lines.append("")
        lines.append("Sample MUST/MUST NOT lines:")
        for l in f["must_lines_sample"][:12]:
            lines.append(f"- {l}")
    lines.append("")
OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"Wrote {OUT}")
PY

python3 tools/render_legacy_extraction.py

echo "==> [8/8] Finish"
echo "DONE."
echo "Next:"
echo "  - Open docs/contracts/_migration/legacy_extraction_summary.md"
echo "  - For each still-relevant rule, paste the legacy text into the right canonical doc"
echo "  - Update docs/contracts/_migration/LEDGER.md status + add required tests paths"