# INV-PLAYLOG-LOCKED-IMMUTABLE-001 — PlaylogEvent entries in the locked execution window are immutable except via atomic override

Status: Invariant
Authority Level: Runtime
Derived From: `LAW-IMMUTABILITY`, `LAW-RUNTIME-AUTHORITY`

## Purpose

Protects in-flight execution from unauthorized modification. A PlaylogEvent inside the locked execution window is the active directive for playout. Mutating it without an atomic override record silently alters what the channel airs — violating `LAW-IMMUTABILITY`'s requirement that mutation require an explicit, pre-persisted override record, and undermining the sovereign runtime authority model of `LAW-RUNTIME-AUTHORITY`.

## Guarantee

A PlaylogEvent entry whose `start_utc` falls within the locked execution window MUST NOT be mutated in place. The only permitted modification is via an atomic operator override: the override record MUST be persisted before the PlaylogEvent entry is updated.

Entries whose `end_utc` is in the past (already-broadcast window) MUST NOT be mutated under any circumstance. No override mechanism applies retroactively.

## Preconditions

- The locked execution window is explicitly declared per channel (start boundary: current time; end boundary: current time + lock horizon depth).
- "Locked" and "past" windows are evaluated against MasterClock at the time of the attempted mutation.

## Observability

The application layer MUST reject any in-place mutation to a locked entry that is not preceded by a committed override record. Any such attempt MUST be logged with: entry ID, attempted mutation type, window status (locked / past), and fault class. Past-window mutations MUST be rejected unconditionally — no override mechanism exempts them.

## Deterministic Testability

Using FakeAdvancingClock: set clock to T. Create PlaylogEvent at [T+15m, T+45m] (within lock window). Attempt in-place mutation without override record. Assert rejected. Separately, advance clock past the entry's `end_utc` (entry is now in past window). Attempt mutation with a valid override record. Assert rejected unconditionally. No real-time waits required.

## Failure Semantics

**Runtime fault** if the system permitted the mutation without a preceding override record. **Operator fault** if the attempt was a direct database manipulation bypassing application-layer enforcement.

## Required Tests

- `pkg/core/tests/contracts/test_scheduling_constitution.py` (PLAYLOG-IMMUT-001, PLAYLOG-IMMUT-002, PLAYLOG-IMMUT-003)

## Enforcement Evidence

TODO
