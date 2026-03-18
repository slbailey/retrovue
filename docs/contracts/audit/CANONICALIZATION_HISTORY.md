# Canonicalization History

Record of the governance audit and canonicalization pass performed on the RetroVue contract system. This document consolidates the former PHASE1–PHASE5 audit documents, execution tracker, and handoff record.

---

## Audit Scope

220+ rules inventoried across: root governance docs, `docs/contracts/`, `pkg/air/docs/contracts/`, `pkg/core/docs/contracts/`, individual invariant files, laws, and test matrices.

---

## Key Findings

### Duplicate Clusters (6)

| ID | Rules | Resolution |
|----|-------|------------|
| DUP-01 | LAW-001 / LAW-CLOCK / INV-TIME-AUTHORITY-SINGLE-SOURCE / Clock Law | Cosmetic — all express single time authority |
| DUP-02 | LAW-006 / LAW-SWITCHING / Switching Law | Cosmetic — output PTS continuity in three homes |
| DUP-03 | LAW-004 / LAW-GRID | 30-min vs configurable grid — open |
| DUP-04 | LAW-LIVENESS / INV-CONTENT-DEFICIT-FILL / INV-TS-EMISSION-LIVENESS | Parent/child — LAW-LIVENESS is constitutional |
| DUP-05 | LAW-OBS-001–005 / ObservabilityParityLaw | Parent/child — law + derived invariants |
| DUP-06 | CORE-005 / INV-ASSET-DURATION-CONTRACTUAL-TRUTH-001 | Superseded — CORE-005 deleted, canonical invariant covers |

### Conflicts Resolved (4)

| ID | Conflict | Resolution |
|----|----------|------------|
| CON-01 | LAW-005 (modulo filler) vs INV-SCHED-GRID-FILLER-PADDING (frame 0) | LAW-005 RETIRED. Filler always starts at frame 0. |
| CON-02 | AIR-013 MasterClock vs OutputTimingContract steady_clock | Split authority: MasterClock=CT, OutputTiming=delivery pacing. |
| CON-03 | LAW-003 retirement | Confirmed RETIRED (Phase 8 BlockPlan supersedes segment RPCs). |
| CON-04 | LAW-002 test skipped | LAW-002 rewritten under BlockPlan. Law002HardStopContractTests canonical. Legacy test RETIRED. |

### Migrations Completed

| Source | Destination | Rules |
|--------|-------------|-------|
| Legacy sink domain contract | OutputBusAndOutputSinkContract.md | AIR-012, AIR-015 |
| Legacy orchestration contract | OrchestrationLoopContract.md | AIR-016 |
| Phase 5 archive | ChannelManagerContract.md | CORE-002, CORE-003 |

### Placeholders Created and Deleted

CORE-004 through CORE-007, AIR-011, MET-002, OBS-002 — all created as placeholders, all subsequently deleted (dead, superseded, or non-behavioral).

---

## Remaining Open Items

| Item | Nature | Severity |
|------|--------|----------|
| DUP-01 (time authority consolidation) | Cosmetic cleanup | LOW |
| DUP-03 / C-05 (grid configurability) | Wording clarification | LOW |
| LAW-007 (no drift test) | Missing E2E harness | MEDIUM |
| CORE-002/CORE-003 (no tests) | Doc-only constraints | MEDIUM |
| INV-SWITCH-BOUNDARY-TIMING (no law derivation) | Orphaned invariant | LOW |

---

## Test Anchor Backlog

See `TEST_ANCHOR_BACKLOG.md` for the prioritized list of rules requiring test implementation.

---

## Phases (Historical)

| Phase | What | Outcome |
|-------|------|---------|
| A | Tracker created | Seeded from PHASE5 plan |
| B | Status labels applied | LAW-003 RETIRED, LAW-002 PARTIALLY-TESTED, LAW-005/AIR-013 CONFLICT-PENDING |
| C | Decision records created | CON-01 through CON-04 |
| D | Legacy contract migrations | AIR-012/015/016, CORE-002/003 migrated to canonical homes |
| E | Placeholders created | 7 placeholders for rules without canonical homes |
| F | Indexes updated | README, INVARIANTS, ledger updated |
| G | Test backlog created | P1–P4 prioritized test authoring backlog |
| H | Handoff | Final documentation of state |
| Post-H | Decisions resolved | All CON-* resolved, placeholders deleted, shadow invariants eliminated |
