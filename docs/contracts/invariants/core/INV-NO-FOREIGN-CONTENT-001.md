# INV-NO-FOREIGN-CONTENT-001 — No artifact may introduce content not traceable to its upstream authority

Status: Invariant
Authority Level: Cross-layer
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Prevents any scheduling layer from silently introducing content that bypasses the constitutional derivation chain. Even if an artifact passes individual layer structural validations, a foreign asset reference at any layer breaks `LAW-DERIVATION`'s traceability requirement and violates `LAW-CONTENT-AUTHORITY`'s mandate that SchedulePlan is the sole editorial authority. Foreign injection is the constitutional mechanism by which unauthorized content reaches broadcast.

## Guarantee

No artifact at any layer may reference an asset that cannot be traced to the upstream authority for that layer:

- A ScheduleDay slot MUST NOT reference an asset that was not present in the zones of the generating SchedulePlan.
- A Playlist entry MUST NOT reference an asset that was not present in the ScheduleDay from which it was derived.
- A PlaylogEvent MUST NOT reference an asset that was not present in the Playlist entry from which it was derived.

The only exception at any layer is a recorded operator override, which must explicitly authorize the substitution.

## Preconditions

- The artifact under validation does not carry an operator override record.

## Observability

At each layer's generation, the output artifact's asset references are validated against the upstream authority's asset set. Any reference not present in the upstream set and not covered by an override record is foreign content. Foreign content MUST be rejected and MUST NOT be committed. The violation MUST be logged with: artifact type, artifact ID, foreign asset ID, and the upstream authority that was checked.

## Deterministic Testability

At each layer: inject an asset reference that is absent from the upstream authority (e.g., insert an asset ID into a Playlist entry that was never mentioned in the ScheduleDay). Trigger layer generation or validation. Assert that the foreign reference is detected and the artifact is rejected. No real-time waits required.

## Failure Semantics

**Planning fault** if the injection occurred during ScheduleDay or Playlist generation (indicates a logic error in the generation service). **Runtime fault** if the injection occurred during PlaylogEvent generation or rolling-window extension.

## Required Tests

- `pkg/core/tests/contracts/test_scheduling_constitution.py` (CROSS-FOREIGN-001, CROSS-FOREIGN-002, CROSS-FOREIGN-003)

## Enforcement Evidence

TODO
