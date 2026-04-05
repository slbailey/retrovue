# MasterClock

**Domain:** systems  
**Slug:** `master-clock`

## Responsibility

**Orchestration time authority** in Core runtime: wall-clock reads and timebase decisions for scheduling-of-runtime (activation, staleness, manifest timing) — **not** AIR’s frame clock.

## Owns vs reads

- **Owns:** the single writer semantics for “what time is it **for Core orchestration**” per `INV-AUTHORITY-SINGLE-OWNER-001` (clock slice).
- **Reads:** OS clock / injectable clock for tests (conceptually).

## Upstream inputs

Environment, test doubles in CI only outside production.

## Downstream outputs

Timestamps consumed by `program-director`, HLS segment timing, feed deadlines, etc.

## Must NOT do

- Duplicate competing wall-clock sources inside Core for the same decision class.
- Replace AIR’s internal pacing clock (different layer).
