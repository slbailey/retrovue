# INV-EXECUTIONENTRY-MASTERCLOCK-ALIGNED-001 — ExecutionEntry timestamps must be aligned to MasterClock

Status: Invariant
Authority Level: Runtime
Derived From: `LAW-RUNTIME-AUTHORITY`, `LAW-CLOCK`

## Purpose

Ensures ExecutionEntry timing is grounded in the single authoritative time source. ExecutionEntry is the runtime authority (`LAW-RUNTIME-AUTHORITY`); its timestamps govern when ChannelManager presents content to AIR. Timestamps derived from any time source other than MasterClock produce playout drift and undermine the coordination contract between Core and AIR, violating `LAW-CLOCK`.

## Guarantee

All `start_utc_ms` and `end_utc_ms` values on ExecutionEntry records must be derived exclusively from MasterClock at generation time. No ExecutionEntry may use an independent wall-clock, local timestamp, or any time source other than the session's MasterClock.

## Preconditions

- A MasterClock instance is established and injectable at ExecutionEntry generation time.

## Observability

ExecutionEntry generation code must accept an explicit clock dependency (not read `datetime.utcnow()` or equivalent directly). Any call path that uses a non-injected time source is a violation detectable by static analysis or test-layer clock substitution.

## Deterministic Testability

Inject a deterministic clock set to a known time T. Generate an ExecutionEntry. Assert `start_utc_ms` and `end_utc_ms` are derived from T (within the expected offset). Inject a second deterministic clock at a different time T2 and assert timestamps change accordingly. No real-time waits required.

## Failure Semantics

**Runtime fault.** HorizonManager used a non-authorized time source when generating entries. This indicates a missing or bypassed clock dependency.

## Required Tests

- `pkg/core/tests/contracts/test_inv_playlog_masterclock_aligned.py`

## Enforcement Evidence

TODO
