# LAW-CONTENT-AUTHORITY

## Constitutional Principle

DSL schedule definitions, compiled via DslScheduleService into ScheduleRevision/ScheduleItem, are the sole editorial authority for channel programming.

No component may introduce content into any scheduling or execution artifact unless that content is derivable from an active ScheduleRevision produced by DSL compilation.

> **History:** Prior to RETA-88 Option B, SchedulePlan was the editorial authority. The SchedulePlan → Zone → Program CRUD island has been retired.

## Implications

- HorizonManager and scheduling services may not inject content not sanctioned by an active ScheduleRevision.
- PlaylistEvent generation may not introduce assets absent from the ScheduleDay it derives from.
- Runtime fallback content must be declared as system-defined filler within the DSL schedule or as an explicit filler policy on the channel.
- Operator overrides are permitted but must be explicit, recorded, and traceable to the superseded artifact.
- No AI, heuristic, or external system may modify content selection without an explicit operator-authorized record.
- No CRUD endpoint may create or modify ScheduleRevision rows; DSL compilation is the sole write path.

## Violation

Any scheduling or execution artifact that references content not derivable from an active ScheduleRevision, without a recorded explicit operator override.
