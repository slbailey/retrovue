# LAW-DERIVATION

## Constitutional Principle

Each downstream scheduling artifact is a pure, traceable derivation of its immediate upstream authority.

`SchedulePlan → ScheduleDay → Playlist → PlaylogEvent → AsRun`

No layer may redefine or editorially reinterpret upstream truth.

## Implications

- ScheduleDay must be derived from and traceable to an active SchedulePlan.
- Playlist must be derived from and traceable to a ScheduleDay.
- PlaylogEvent must be derived from and traceable to a Playlist entry.
- AsRun must record the PlaylogEvent that authorized the playback.
- Derivation traceability must be preserved through substitutions and operator overrides; override records must reference the artifact being superseded.
- A downstream layer may specialize or resolve upstream intent (e.g., expanding a Program to physical assets) but may not contradict it.

## Violation

Any artifact that cannot be traced to its immediate upstream authority, or any layer that reinterprets upstream content selections, timing, or editorial intent without a recorded operator override.
