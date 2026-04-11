# INV-PLAYLOG-NO-RETROACTIVE-FILL-001 — No retroactive playlog backfill

Status: Invariant
Authority Level: Cross-layer
Derived From: `LAW-RUNTIME-AUTHORITY`, `LAW-CLOCK`

## Purpose

Protects `LAW-RUNTIME-AUTHORITY` by ensuring the playlog records only what actually aired. Channels in RetroVue only materialize when viewers exist. During downtime, no playout instance is active, so no content is emitted. Fabricating as-run records for periods when no playout occurred would violate the principle that the playlog is execution truth — not editorial intent projected backward.

## Guarantee

The playlog MUST NOT fabricate as-run records for time periods when no playout instance was active. On resume from downtime, only the current block is backfilled. Blocks wholly missed during downtime produce no playlog entries. This gap is intentional and correct.

## Preconditions

- The system was down (no playout instance active) for a period that spans one or more complete schedule blocks.
- On resume, the playlog daemon begins recording from the current position.

## Observability

A playlog gap is observable as a contiguous range of broadcast time with no ExecutionEntry rows. This is distinguishable from a fault because no playout session existed during that period (no session_id, no AIR process). Monitoring can cross-reference playout session logs against playlog gaps to confirm expected vs. unexpected gaps.

## Deterministic Testability

Simulate a channel with a schedule spanning multiple blocks. Advance wall clock past several blocks without starting a playout instance. Start playout. Verify that the playlog contains entries only for blocks that aired after the playout instance started. Verify no retroactive entries exist for the skipped blocks.

## Failure Semantics

**Cross-layer fault.** If the system retroactively fills playlog entries for blocks that never aired, the as-run log becomes fiction — misrepresenting what viewers actually received. Downstream analytics, compliance reporting, and EPG reconciliation become unreliable.

## Required Tests

- TODO: `server/tests/contracts/cross-cutting/test_inv_playlog_no_retroactive_fill_001.py`

## Enforcement Evidence

Design acceptance — the system already exhibits this behavior. Test to be implemented to protect against regression.
