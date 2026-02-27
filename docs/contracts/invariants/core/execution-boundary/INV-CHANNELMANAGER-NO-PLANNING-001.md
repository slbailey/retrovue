# INV-CHANNELMANAGER-NO-PLANNING-001 — ChannelManager must not perform or trigger planning operations at runtime

Status: Invariant
Authority Level: Runtime
Derived From: `LAW-RUNTIME-AUTHORITY`, `LAW-CONTENT-AUTHORITY`

## Purpose

Enforces the hard boundary between the execution layer and the planning layer. `LAW-RUNTIME-AUTHORITY` establishes ExecutionEntry as the sole runtime authority for what plays now. `LAW-CONTENT-AUTHORITY` establishes SchedulePlan as the sole editorial authority. Both laws are violated if ChannelManager reaches back into the planning stack at runtime — whether by querying the Asset Library, triggering episode resolution, building Playlists, computing block boundaries, or requesting Playlog extension on demand.

If this boundary is not invariant-protected, any planning gap at execution time creates pressure for ChannelManager to compensate. That compensation is the mechanism by which planning failures become silent and unattributable. The failure must surface as a planning fault, not disappear into runtime improvisation.

See also: `ScheduleExecutionInterfaceContract_v0.1.md §7`, `ScheduleManagerPlanningAuthority_v0.1.md §Non-Goals`.

## Guarantee

ChannelManager MUST NOT, at any point during an active playout session:

1. Query the Asset Library for asset metadata, paths, or eligibility.
2. Trigger or request episode resolution or program selection.
3. Build, extend, or modify a Playlist or ExecutionEntry sequence.
4. Perform schedule math (block boundary computation, grid alignment, zone lookup).
5. Request Playlog or horizon extension in response to content consumption.
6. Interpret EPG data as a source of playout decisions.

ChannelManager consumes pre-built execution artifacts as-is. It does not transform, repair, or augment them.

## Preconditions

- An active playout session exists for the channel.
- ExecutionWindowStore is populated by HorizonManager prior to playout start.

## Observability

All Asset Library interfaces, schedule resolution services, and Playlog write paths MUST be inaccessible to ChannelManager at the architectural boundary — not merely unused by convention. Any runtime call stack that originates from ChannelManager and terminates in a planning service is a violation regardless of whether content is affected.

Monitoring: ChannelManager MUST NOT hold a reference to any planning service (ScheduleManager, AssetLibrary, PlaylistScheduleManager, or equivalent). Dependency injection configuration is the primary enforcement surface.

## Deterministic Testability

Using FakeAdvancingClock and an ExecutionWindowStore pre-populated with a finite window: advance the clock past the end of the populated window without extending it. Assert that ChannelManager signals a planning failure rather than triggering any planning path. Assert that no Asset Library call, no episode resolution call, and no Playlog extension call is emitted from within the ChannelManager call stack. No real-time waits required.

## Failure Semantics

**Runtime fault.** ChannelManager invoking a planning operation at runtime indicates an architectural boundary violation — the execution layer has assumed planning responsibilities. This fault is attributable to ChannelManager's dependency graph, not to any operator action.

## Required Tests

- `pkg/core/tests/contracts/test_scheduling_constitution.py` (EXEC-BOUNDARY-001, EXEC-BOUNDARY-002)

## Enforcement Evidence

TODO
