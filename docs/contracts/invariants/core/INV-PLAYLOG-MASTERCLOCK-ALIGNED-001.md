# INV-PLAYLOG-MASTERCLOCK-ALIGNED-001 — PlaylogEvent timestamps must be aligned to MasterClock

Status: Invariant
Authority Level: Runtime
Derived From: `LAW-RUNTIME-AUTHORITY`, `LAW-CLOCK`

## Purpose

Ensures PlaylogEvent timing is grounded in the single authoritative time source. PlaylogEvent is the runtime authority (`LAW-RUNTIME-AUTHORITY`); its timestamps govern when ChannelManager presents content to AIR. Timestamps derived from any time source other than MasterClock produce playout drift and undermine the coordination contract between Core and AIR, violating `LAW-CLOCK`.

## Guarantee

All `start_utc` and `end_utc` values on PlaylogEvent records must be derived exclusively from MasterClock at generation time. No PlaylogEvent entry may use an independent wall-clock, local timestamp, or any time source other than the session's MasterClock.

## Preconditions

- A MasterClock instance is established and injectable at PlaylogEvent generation time.

## Observability

PlaylogEvent generation code must accept an explicit clock dependency (not read `datetime.utcnow()` or equivalent directly). Any call path that uses a non-injected time source is a violation detectable by static analysis or test-layer clock substitution.

## Deterministic Testability

Inject a deterministic clock set to a known time T. Generate a PlaylogEvent. Assert `start_utc` and `end_utc` are derived from T (within the expected offset). Inject a second deterministic clock at a different time T2 and assert timestamps change accordingly. No real-time waits required.

## Failure Semantics

**Runtime fault.** The PlaylogService used a non-authorized time source when generating entries. This indicates a missing or bypassed clock dependency.

## Required Tests

- `pkg/core/tests/contracts/test_inv_playlog_masterclock_aligned.py`

## Enforcement Evidence

TODO
