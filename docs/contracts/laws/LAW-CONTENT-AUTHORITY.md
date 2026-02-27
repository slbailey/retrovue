# LAW-CONTENT-AUTHORITY

## Constitutional Principle

SchedulePlan is the sole editorial authority for channel programming.

No component may introduce content into any scheduling or execution artifact unless that content is derivable from an active SchedulePlan.

## Implications

- HorizonManager and scheduling services may not inject content not sanctioned by an active SchedulePlan.
- PlaylogEvent generation may not introduce assets absent from the Playlist derived from ScheduleDay.
- Runtime fallback content must be declared as system-defined filler within the plan or as an explicit filler policy on the channel.
- Operator overrides are permitted but must be explicit, recorded, and traceable to the superseded artifact.
- No AI, heuristic, or external system may modify content selection without an explicit operator-authorized record.

## Violation

Any scheduling or execution artifact that references content not derivable from an active SchedulePlan, without a recorded explicit operator override.
