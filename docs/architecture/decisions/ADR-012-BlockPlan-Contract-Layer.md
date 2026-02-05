# ADR-012: BlockPlan Contract Layer Complete; Execution Intentionally Absent

**Status:** Accepted
**Date:** 2026-02-05
**Tag:** `blockplan-contracts-v1`

## Context

The BlockPlan execution model was designed in `docs/architecture/proposals/BlockLevelPlayoutAutonomy.md` to enable block-level playout autonomy while preserving all existing invariants (Phase 8, 11, 12).

Section 7 defines 13 formal contracts covering:
- Block acceptance (CONTRACT-BLOCK-001 through 003)
- Segment execution (CONTRACT-SEG-001 through 005)
- Mid-block join (CONTRACT-JOIN-001, 002)
- Two-block lookahead (CONTRACT-LOOK-001 through 003)

Section 8 establishes governance: frozen contracts, extension points, and forbidden extensions.

## Decision

Implement **only the contract layer** (data structures, validation, queue management) without any execution logic.

### What was implemented:
- `BlockPlanTypes.hpp/cpp` — Data structures and error codes
- `BlockPlanValidator.hpp/cpp` — Validation per CONTRACT-BLOCK-001, CT boundary computation per CONTRACT-SEG-001, join computation per CONTRACT-JOIN-001/002
- `BlockPlanQueue.hpp/cpp` — Two-slot queue per CONTRACT-LOOK-001/002/003
- `BlockPlanContractTests.cpp` — 20 tests covering all acceptance, boundary, join, and lookahead contracts

### What was NOT implemented:
- Frame decoding
- Frame encoding
- CT advancement loops
- Segment transition execution
- Underrun padding
- Overrun truncation
- Output emission

## Rationale

1. **Validate contracts before execution** — The contracts can be proven correct through testing without building the full execution machinery.

2. **Prevent premature optimization** — Execution logic is complex. Freezing contracts first ensures we don't accidentally violate them while implementing execution.

3. **Enable parallel development** — Another contributor can implement execution against these contracts without re-reasoning the design.

4. **Enforce governance** — Section 8 frozen/forbidden rules are now tested. Any execution implementation must pass these tests.

## Consequences

### Positive
- Contract layer is complete and tested (20 tests, 100% pass)
- Frozen invariants are codified and enforced
- Clear boundary: contracts here, execution elsewhere

### Negative
- No runnable BlockPlan executor yet
- Execution layer still needs to be built

### Neutral
- This is intentional phasing, not incompleteness

## Validation

```
$ pkg/air/build/blockplan_contract_tests
[==========] Running 20 tests from 5 test suites.
[  PASSED  ] 20 tests.
```

## References

- `docs/architecture/proposals/BlockLevelPlayoutAutonomy.md` — Full specification
- `pkg/air/include/retrovue/blockplan/README.md` — Layer constraints
- `pkg/air/tests/contracts/BlockPlan/BlockPlanContractTests.cpp` — Contract tests
