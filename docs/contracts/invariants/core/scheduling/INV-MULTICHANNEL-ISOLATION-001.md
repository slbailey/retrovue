# INV-MULTICHANNEL-ISOLATION-001 — Multi-channel schedule isolation

Status: Invariant
Authority Level: Cross-layer
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring N channels compile, cache, and serve schedule blocks independently. State leakage between channels causes one channel's editorial decisions to corrupt another's timeline.

## Guarantee

Each channel MUST compile, cache, and serve its schedule blocks independently. No scheduling state — compiled blocks, URI caches, sequence positions, or horizon markers — MUST leak between channels.

## Preconditions

Two or more channels are active with distinct channel_ids and independent SchedulePlans.

## Observability

For channels A and B compiled concurrently: modifying, extending, or invalidating A's horizon MUST NOT alter any block in B's compiled output.

## Deterministic Testability

Compile the full derivation chain (SchedulePlan -> ResolvedScheduleDay -> TransmissionLog -> ExecutionEntry) for two channels with different channel_ids. Assert that all channel_id fields on produced artifacts match their respective channel and that no artifact references the other channel's identifiers, plan_ids, or asset selections.

## Failure Semantics

**Planning fault.** Cross-channel contamination produces incorrect editorial output on the affected channel.

## Required Tests

- `server/tests/contracts/scheduling/test_vertical_slice_derivation_chain.py`
- `server/tests/contracts/scheduling/test_multichannel_isolation.py`

## Enforcement Evidence

TODO
