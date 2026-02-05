# BlockPlan Contract Layer

**Status:** FROZEN (blockplan-contracts-v1)

This directory contains the **contract layer** for BlockPlan execution as defined in:
- `docs/architecture/proposals/BlockLevelPlayoutAutonomy.md`

## What This Layer Contains

- **Data structures** (`BlockPlanTypes.hpp`)
- **Validation logic** (`BlockPlanValidator.hpp`)
- **Queue management** (`BlockPlanQueue.hpp`)

## What This Layer Does NOT Contain

**⚠️ DO NOT ADD EXECUTION LOGIC HERE ⚠️**

This layer is intentionally limited to:
- Input validation (CONTRACT-BLOCK-001)
- CT boundary computation (CONTRACT-SEG-001)
- Join parameter computation (CONTRACT-JOIN-001, CONTRACT-JOIN-002)
- Queue management (CONTRACT-LOOK-001, CONTRACT-LOOK-002, CONTRACT-LOOK-003)

Execution logic (decoding, encoding, frame emission, timing loops) belongs in a
separate execution layer that consumes these contracts.

## Frozen Invariants

Per Section 8 of the proposal, these contracts are **frozen**:
- Duration sum invariant
- Segment index contiguity
- CT boundary derivation
- Two-block queue maximum
- Lookahead exhaustion = termination

Changes to frozen contracts require a breaking-version declaration.

## Contract Tests

All contracts have corresponding tests in:
- `pkg/air/tests/contracts/BlockPlan/BlockPlanContractTests.cpp`

Run with: `pkg/air/build/blockplan_contract_tests`
