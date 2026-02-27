# LAW-ELIGIBILITY

## Constitutional Principle

Only assets with `state=ready` and `approved_for_broadcast=true` may appear in any materialized scheduling or execution artifact.

No other eligibility criterion may override this gate.

## Implications

- SchedulePlan zone resolution must exclude non-eligible assets before materialization.
- ScheduleDay must not reference assets that did not pass the eligibility gate at resolution time.
- Playlist entries must not reference ineligible assets.
- PlaylogEvent must not reference assets that have become ineligible since their Playlist entry was generated.
- Runtime must not begin playout for any asset that is not currently eligible.

## Violation

Any scheduling artifact or playout stream that contains a reference to an asset where `state != ready` or `approved_for_broadcast != true`.
