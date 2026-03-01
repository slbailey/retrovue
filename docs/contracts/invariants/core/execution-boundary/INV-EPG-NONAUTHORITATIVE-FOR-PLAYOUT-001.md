# INV-EPG-NONAUTHORITATIVE-FOR-PLAYOUT-001 — EPG data must not drive playout decisions

Status: Invariant
Authority Level: Runtime
Derived From: `LAW-RUNTIME-AUTHORITY`, `LAW-DERIVATION`

## Purpose

EPG data is a viewer-facing representation derived from ScheduleDay. It is produced for display purposes and is not an execution artifact. `LAW-RUNTIME-AUTHORITY` designates ExecutionEntry (the execution plan / Transmission Log) as the sole runtime authority for what plays now. Using EPG data to make playout decisions introduces a second, unaccountable authority — one that is derived, potentially stale, and not subject to the immutability and lock-window guarantees that apply to the execution plan.

EPG may contain program titles, timecodes, and metadata that partially overlap with execution plan data. That overlap is coincidental. EPG is never the ground truth for segment boundaries, asset paths, or playback offsets.

See also: `ScheduleManagerPlanningAuthority_v0.1.md §Non-Goals`, `ScheduleExecutionInterfaceContract_v0.1.md §10`.

## Guarantee

No playout decision — including block start time, segment selection, asset path, playback offset, or fence boundary — may be derived from EPG data.

EPG data MAY be read by ChannelManager for:
- Logging and telemetry enrichment (e.g. attaching a program title to an AsRun record).
- Display metadata supplied to viewers (e.g. "Now Playing" labels).

EPG data MUST NOT be read by ChannelManager for:
- Determining what asset to play next.
- Computing when to switch between segments.
- Filling gaps in the execution plan.
- Validating or repairing execution plan content.

The execution plan (ExecutionEntry / Transmission Log entries in ExecutionWindowStore) is the sole input to playout logic.

## Preconditions

- EPG data exists separately from the execution plan (ResolvedScheduleDay / EPG store vs. ExecutionWindowStore).
- ChannelManager has access to both stores.

## Observability

ChannelManager's playout decision path MUST NOT hold a read dependency on any EPG store, ResolvedScheduleDay store, or ScheduleDay for the purpose of driving playback. Dependency injection configuration and code review are the primary enforcement surfaces.

If a playout decision is made from EPG data, it will be observable as: an asset played that was not present in the corresponding ExecutionWindowStore entry, or a segment boundary that does not match the execution plan.

## Deterministic Testability

Using FakeAdvancingClock: populate ExecutionWindowStore with block B1 (asset A1, duration 30 min). Populate EPG store with an entry for the same window referencing asset A2. Trigger playout. Assert that ChannelManager plays A1, not A2. Assert that the EPG entry is not consulted in the playout decision call stack. No real-time waits required.

## Failure Semantics

**Runtime fault.** Using EPG as a playout source violates `LAW-RUNTIME-AUTHORITY` by introducing a second authority for execution content. The resulting broadcast is constitutionally unaccountable — it cannot be traced to an authorized execution plan entry.

## Required Tests

- `pkg/core/tests/contracts/test_scheduling_constitution.py` (EXEC-BOUNDARY-003)
- `pkg/core/tests/contracts/test_epg_invariants.py::TestEpgEndpointNonBlocking` (structural: EPG handlers must not block event loop)

## Enforcement Evidence

- **Architectural enforcement:** `ChannelManager` playout decision path reads from `ChannelStream` which sources execution data — no EPG store, `ResolvedScheduleDay` store, or `ScheduleDay` is referenced in the playout decision call stack.
- `ChannelManager` has no import of EPG-related modules for playout purposes — EPG access, if any, is limited to display metadata enrichment (program titles for "Now Playing" labels), not execution decisions.
- **Enforcement surface:** Dependency injection configuration ensures `ChannelManager` receives only `ExecutionWindowStore`-derived data for playout. Code review and import analysis are the primary enforcement mechanisms.
- Dedicated contract test (EXEC-BOUNDARY-003) is referenced in `## Required Tests` but not yet implemented in the current tree.
