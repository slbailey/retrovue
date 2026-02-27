# LAW-RUNTIME-AUTHORITY

## Constitutional Principle

PlaylogEvent is the sole runtime authority for what plays now.

ScheduleDay and Playlist are planning artifacts only; they do not execute.

ChannelManager and AIR must derive playout instructions exclusively from PlaylogEvent.

## Implications

- ChannelManager must not read ScheduleDay or Playlist directly to determine current playout content.
- AIR receives playout plans derived from PlaylogEvent; it does not interpret schedule constructs.
- No component other than the authorized Playlog service may generate, substitute, or cancel active PlaylogEvent entries without an explicit operator override record.
- A ScheduleDay mutation after the Playlog has been generated does not affect in-flight PlaylogEvents.
- The locked execution window is defined per channel; entries inside it are governed by `LAW-IMMUTABILITY`.

## Violation

Any component that reads ScheduleDay, Playlist, or SchedulePlan directly to determine current playout instructions, bypassing PlaylogEvent.
