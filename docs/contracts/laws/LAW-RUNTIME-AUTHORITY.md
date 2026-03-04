# LAW-RUNTIME-AUTHORITY

## Constitutional Principle

PlaylistEvent is the sole runtime authority for what plays now.

ScheduleDay is a planning artifact only; it does not execute.

ChannelManager and AIR must derive playout instructions exclusively from PlaylistEvent and its derived ExecutionSegments.

## Implications

- ChannelManager must not read ScheduleDay directly to determine current playout content.
- AIR receives playout plans derived from PlaylistEvent; it does not interpret schedule constructs.
- No component other than the authorized PlaylistBuilder service may generate, substitute, or cancel active PlaylistEvent entries without an explicit operator override record.
- A ScheduleDay mutation after PlaylistEvents have been generated does not affect in-flight PlaylistEvents.
- The locked execution window is defined per channel; entries inside it are governed by `LAW-IMMUTABILITY`.

## Violation

Any component that reads ScheduleDay or SchedulePlan directly to determine current playout instructions, bypassing PlaylistEvent.
