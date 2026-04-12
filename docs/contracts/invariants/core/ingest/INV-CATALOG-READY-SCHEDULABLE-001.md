# INV-CATALOG-READY-SCHEDULABLE-001 — All ready assets are playable and schedulable

Status: Invariant
Authority Level: Planning
Derived From: `LAW-ELIGIBILITY`, `LAW-CONTENT-AUTHORITY`

## Purpose

Protects `LAW-ELIGIBILITY` by establishing `ready` as the trust boundary between ingest and scheduling. Without this guarantee, scheduling must re-validate or probe assets before placement, creating runtime dependencies on ingest infrastructure during schedule compilation.

## Guarantee

If an asset is in state `ready`, scheduling MAY place it in any matching pool slot without further validation. Scheduling MUST NOT re-validate or probe assets — `ready` is the trust boundary. If an asset becomes unplayable after reaching `ready`, the system MUST transition it out of `ready` before the next schedule compile.

## Preconditions

- The asset has passed all required validators.
- The asset has been approved (auto or manual).

## Observability

A `ready` asset that fails playout is a violation. Detection occurs when playout reports a decode or file-access failure for an asset that was in `ready` state at schedule compile time.

## Deterministic Testability

1. Create an asset in `ready` state with valid metadata. Assert scheduling accepts it without probe.
2. Simulate an asset becoming unplayable (e.g. source file removed). Assert the system transitions it out of `ready`.
3. Assert that schedule compilation does not invoke any validator or file-access check on `ready` assets.

## Failure Semantics

**Planning fault.** A `ready` asset that is not playable causes playout failure at runtime. The fault lies in the ingest pipeline that promoted the asset to `ready` without ensuring playability.

## Required Tests

- `server/tests/contracts/ingest/test_inv_catalog_ready_schedulable.py`

## Enforcement Evidence

TODO
