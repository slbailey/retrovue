# Retrovue Simplification Program — Locked Plan (v1)

Last updated: 2026-03-28 (America/New_York)
Owner: OpenClaw assistant (autonomous execution)

## Why this file exists
This file is the durable execution brief for the Retrovue complexity-reduction refactor so a session reset does not lose operating context, constraints, or sequencing.

---

## Locked Decisions (from Steve)

### Program mode
- **1A: Stability first** for a short focused window (pause most new features).
- **Aggressiveness: L3** (aggressive refactor allowed).
- **Cadence: daily concise updates**.
- **Done target: 5B**.

### Five non-negotiables (all hard YES)
1. Broadcast master clock remains authoritative (no drift-tolerant shortcuts).
2. YAML scheduling semantics remain as designed (editorial intent preserved).
3. Contract-first workflow remains mandatory.
4. No serving stale HLS window (hard rule).
5. Diagnostics remain bounded/auto-expiring with minimal baseline noise.

### Additional operating constraints
- Single-user system: no backward-compat requirement by default.
- Single source of truth per concern is mandatory.
- Remove irrelevant/duplicate paths completely (delete, not just deprecate).
- Execute on a **separate branch**.
- Deliver in **multiple PR-sized rollback units**.
- User remains hands-off until all-clear (available only for questions/pivots).

---

## Core diagnosis to drive the refactor
Authority overlap is creating regressions:
- schedule/block timing truth,
- HLS window truth,
- teardown/reconnect lifecycle truth,
- diagnostics behavior truth.

Primary simplification objective: enforce one owner per concern and make other components observers.

---

## Ownership model (target)
Define and enforce exactly one owner for:
- **Clock/timebase owner**
- **Segment-window owner**
- **Channel lifecycle owner**
- **Diagnostics owner**

No dual-authority merges.

---

## Execution phases (autonomous)

### Phase 0 — Baseline capture
- Create simplification branch.
- Capture current failing/passing contract and test baseline.
- Produce initial authority overlap map.

### Phase 1 — Ownership map enforcement
- Document current vs target owner for each concern.
- Remove/redirect duplicate decision points.
- Add/adjust boundary contracts to enforce ownership behavior.

### Phase 2 — Reconnect/lifecycle hardening
- Convert reconnect/teardown path into explicit state-machine-like flow.
- Eliminate implicit async ordering dependencies where possible.
- Add replay/regression tests for reconnect path.

### Phase 3 — Contract overlap reduction
- Keep boundary/invariant contracts.
- Merge/retire contracts that assert internal sequencing unless sequence is itself a required invariant.

### Phase 4 — Diagnostics isolation
- Ensure diagnostics cannot alter steady-state runtime behavior outside explicit bounded windows.
- Reduce baseline noise and enforce auto-expiry behavior.

### Phase 5 — Change-surface controls
- Add process gates for future work:
  - authority map check,
  - complexity budget,
  - touch-surface gate,
  - regression containment rule.

---

## Required per-change header (for each PR-sized chunk)
1. Authority map touched.
2. Complexity budget (removed / added / net moving parts).
3. Contract impact statement.
4. Rollback unit statement.

---

## Anti-regression operating rules
- If a fix touches 3+ components, treat as architecture issue first.
- If change touches >1 authority domain, split into staged work unless explicitly coordinated.
- Prefer deletion/consolidation over layering.
- Reject dead legacy path preservation “just in case.”

---

## Definition of Done (5B)
- Single ownership map enforced for timing/window/lifecycle/diagnostics.
- Contract overlap reduced.
- Reconnect path hardened.
- Fewer cross-component touches per feature change.

---

## Daily concise update format
- What changed
- Risk level
- Rollback note
- Next chunk

Proof requirement: report only completed, verifiable work (branch/commits/tests/files).

---

## Reset resilience note
If assistant session resets, resume from this file first, then validate repository state against this plan before continuing.
