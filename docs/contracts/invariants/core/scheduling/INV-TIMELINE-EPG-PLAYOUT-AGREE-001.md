# INV-TIMELINE-EPG-PLAYOUT-AGREE-001 — EPG and playout consistency

Status: Invariant
Authority Level: Cross-layer
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring the EPG — the viewer's contract — matches what the playout engine plays. The EPG and playout MUST be projections of the same underlying timeline, not independently maintained datasets.

## Guarantee

The EPG and playback MUST reflect the same underlying timeline at all times.

## Observability

For any time T, EPG and playback queries MUST return identical program identity and timing.

## Deterministic Testability

At any time T, query the EPG for channel C and simultaneously query the playout block for the same T. The EPG entry's program title, start time, and duration MUST match the playout block's primary content asset title, start time, and block duration.

## Failure Semantics

**Cross-layer fault.** EPG/playout divergence breaks user trust — the viewer sees a different program than the one listed in the guide.

## Required Tests

- `pkg/core/tests/contracts/test_inv_timeline_authority.py`

## Enforcement Evidence

TODO
