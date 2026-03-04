# LAW-DERIVATION

## Constitutional Principle

Each downstream scheduling artifact is a pure, traceable derivation of its immediate upstream authority.

`SchedulePlan → ScheduleRevision → ScheduleItem → PlaylistEvent → ExecutionSegment → BlockPlan → AIR → AsRun`

No layer may redefine or editorially reinterpret upstream truth.

## Implications

- ScheduleRevision must be derived from and traceable to an active SchedulePlan.
- ScheduleItem must belong to exactly one ScheduleRevision.
- ScheduleDay is a derived grouping of ScheduleItems by broadcast_day, not an authority in the derivation chain.
- PlaylistEvent must be derived from and traceable to a ScheduleItem.
- ExecutionSegment must be derived from and traceable to a PlaylistEvent.
- AsRun must record the PlaylistEvent that authorized the playback.
- Derivation traceability must be preserved through substitutions and operator overrides; override records must reference the artifact being superseded.
- A downstream layer may specialize or resolve upstream intent (e.g., expanding a Program to physical assets) but may not contradict it.

## Violation

Any artifact that cannot be traced to its immediate upstream authority, or any layer that reinterprets upstream content selections, timing, or editorial intent without a recorded operator override.
