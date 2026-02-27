# LAW-IMMUTABILITY

## Constitutional Principle

Materialized scheduling artifacts are immutable once published within their authority window.

Mutation requires explicit regeneration or operator override and must be atomic.

## Implications

- ScheduleDay is immutable for its broadcast date once materialized; modification requires force-regeneration (atomic replacement) or a recorded manual override.
- PlaylogEvent entries inside the locked execution window are immutable except via atomic operator override with an explicit override record.
- AsRun entries are immutable once recorded; no post-hoc mutation is permitted under any circumstance.
- Regeneration replaces an artifact atomically; partial in-place updates to published artifacts are not permitted.
- Override records must reference the artifact being superseded and must be persisted before the superseding artifact takes effect.
- The locked execution window boundary is defined per channel and must be explicitly declared.

## Violation

Any in-place mutation of a published ScheduleDay, a locked PlaylogEvent entry, or an AsRun record, without an atomic regeneration or a persisted operator override record that precedes the change.
