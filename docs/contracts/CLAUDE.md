# Working in docs/contracts — Agent Rules

This directory is the canonical source of runtime guarantees.
All new work MUST maintain the consistency of the index, style, and test coverage documents.

---

## When you add or modify an invariant or law

1. **Create the file** following `HOUSE-STYLE.md` exactly — section order, modal language, tone, and prohibitions all apply. No exceptions.

2. **Update `INVARIANTS.md`** — add the new invariant (or law) to the correct section table. Every row requires: invariant ID, relative file link, and `Derived From` law(s). An invariant that exists on disk but is absent from `INVARIANTS.md` is invisible to the rest of the system.

3. **Update the relevant TEST-MATRIX** — each test matrix covers a specific domain:
   - `TEST-MATRIX-SCHEDULING-CONSTITUTION.md` — scheduling pipeline (SchedulePlan → ResolvedScheduleDay → TransmissionLog → ExecutionEntry → AsRun)
   - `TEST-MATRIX-HORIZON-INVARIANTS.md` — horizon management and execution window coverage
   - If no TEST-MATRIX covers the new invariant's domain, flag this before proceeding.

   For each new invariant, add a row or test-case block to the matrix that maps the invariant ID to at least one concrete test scenario. Every invariant MUST be covered by at least one test.

4. **Add the test path to the invariant file** — the `## Required Tests` section of the invariant file MUST list the test file path(s) where coverage lives.

---

## When you add new tests for an existing invariant

1. Verify the invariant's `## Required Tests` section already lists the test file. If not, add it.
2. Verify the TEST-MATRIX row for that invariant reflects the new or updated test scenario. If not, update it.

---

## Style authority

`HOUSE-STYLE.md` is the sole style reference for invariant and law documents. When in doubt, read it before writing. Do not invent new section names, add rationale sections, or use SHOULD/MAY language.

---

## Order of operations (mandatory)

```
HOUSE-STYLE.md → draft invariant file → update INVARIANTS.md → update TEST-MATRIX → add Required Tests path
```

Never write an invariant file without completing all four subsequent steps in the same change.
