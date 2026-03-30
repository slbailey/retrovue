**Instruction ID:** PASS-CLEANUP-01-DOC-AUDIT
**Issued by:** RetrovueBot / Robbie (Architect)
**Status:** IN PROGRESS

---

## Pass Alignment

This step performs a bounded documentation hygiene audit to remove clearly temporary working artifacts left over from prior implementation/debugging efforts, while preserving authoritative engineering state and architectural records. It does not change production behavior.

---

## Objective

Audit the repository for documentation files that are clearly temporary and no longer needed (for example: stale todo lists, scratch working notes, one-off debugging writeups, ad hoc cleanup notes, superseded pass artifacts).

Produce a keep/remove recommendation set, and remove only files that are unambiguously temporary and obsolete.

Do **not** remove any authoritative engineering, contract, invariant, pass-state, or decision-tracking documents.

---

## Exact Files / Components

You may inspect documentation/markdown/text note files across the repo as needed.

You may remove only files that fit **all** of the following:
1. They are clearly temporary working artifacts.
2. They are not referenced as active authority by the current workflow.
3. Their removal does not delete contracts, invariants, test matrices, decision records, or active pass/state files.

---

## Constraints

- No production code changes.
- No test changes.
- Do NOT remove any of the following unless explicitly directed later:
  - `VISION.md`
  - `CURRENT_PASS.md`
  - `NEXT_INSTRUCTION.md`
  - `EXECUTION_STATE.md`
  - `DECISIONS.md`
  - contract/invariant docs
  - test matrix docs
  - architecture/design docs
  - user-facing README/setup docs
- If classification of a file is ambiguous, do **not** delete it. Mark it as KEEP or BLOCKED with rationale.
- Prefer a conservative cleanup. We want removal of obvious clutter, not aggressive pruning.

---

## Required Work

1. Inventory candidate temporary documentation files.
2. Classify each candidate as:
   - KEEP
   - REMOVE
   - BLOCKED (unclear / needs decision)
3. Remove only files in the REMOVE category.
4. Do not touch BLOCKED files.

---

## Required Proof

Update `EXECUTION_STATE.md` with:

1. Plain-English summary of the cleanup.
2. List of all candidate files reviewed.
3. Classification for each candidate (KEEP / REMOVE / BLOCKED) with one-line rationale.
4. Exact files deleted.
5. Explicit confirmation that no authoritative state/contract/invariant/decision docs were removed.

---

## What Is NOT To Be Changed

- Production code
- Tests
- Contracts / invariants / test matrices
- Active agent-loop authority files
- Architecture / decision records
