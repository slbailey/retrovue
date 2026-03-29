# NEXT_INSTRUCTION.md

**Instruction ID:** PASS-MERGE-03-REBASE
**Issued by:** RetrovueBot / Robbie (Architect)
**Status:** IN PROGRESS

---

## Objective

Rebase `refactor/simplify-single-authority-l3` onto current `main` to resolve the 29-test branch divergence. Re-run the previously failing test groups to confirm they resolve cleanly.

---

## Exact Files / Components

- Branch: `refactor/simplify-single-authority-l3`
- Rebase target: `main` (current HEAD)
- Conflict resolution: minimal — only what is necessary
- If any conflict requires an architectural decision, STOP and report BLOCKED

---

## Constraints

- Do NOT make code changes beyond conflict resolution
- Do NOT change VISION.md or CURRENT_PASS.md
- If a conflict requires architectural judgement, halt: status = BLOCKED
- After rebase, run the divergent test groups first before full suite

---

## Required Proof

Update `EXECUTION_STATE.md` with:
1. Conflicts encountered (files, nature of conflict)
2. How each was resolved
3. Post-rebase results for the 5 previously divergent test groups
4. Then full suite results
5. Merge readiness verdict

---

## What Is NOT To Be Changed

- VISION.md
- CURRENT_PASS.md
- Any production logic beyond what conflict resolution strictly requires
