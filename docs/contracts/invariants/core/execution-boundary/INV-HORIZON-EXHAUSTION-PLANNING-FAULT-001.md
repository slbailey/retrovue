# INV-HORIZON-EXHAUSTION-PLANNING-FAULT-001 — Execution horizon exhaustion is a planning fault; ChannelManager must not compensate

Status: Invariant
Authority Level: Runtime
Derived From: `LAW-RUNTIME-AUTHORITY`, `LAW-CONTENT-AUTHORITY`

## Purpose

When the execution horizon is exhausted — no ExecutionWindowStore entry covers the time at which ChannelManager requires the next block — this is a failure of horizon maintenance by the planning layer. It is not a failure of the execution layer.

`LAW-RUNTIME-AUTHORITY` designates the execution plan as the sole runtime authority for what plays. If that authority is absent, there is no constitutional basis for ChannelManager to improvise. `LAW-CONTENT-AUTHORITY` designates SchedulePlan as the sole editorial authority — ChannelManager inserting filler, selecting fallback content, or retrying planning calls would introduce content outside the authorized derivation chain.

Silent compensation at the execution layer is constitutionally more dangerous than visible failure. Compensation masks planning faults, makes them unattributable, and allows unauthorized content to reach broadcast.

See also: `ScheduleHorizonManagementContract_v0.1.md §7`, `ScheduleExecutionInterfaceContract_v0.1.md §6`.

## Guarantee

When ChannelManager requires a block and no locked execution entry covers the required time window, ChannelManager MUST:

1. Log a `POLICY_VIOLATION` with fault class `planning`, identifying: channel ID, required time window, and the exhaustion event.
2. Signal the failure to the supervising layer (ProgramDirector or equivalent).
3. Either halt the affected channel's playout session cleanly, or hold the last valid output per runtime fallback laws (freeze/pad/black per AIR invariants) — but NOT substitute, resolve, or request new planning content.

ChannelManager MUST NOT:
- Retry a planning or resolution call in response to missing execution data.
- Insert filler content not present in the execution plan.
- Query the Asset Library or Playlist to fill the gap.
- Silently skip the missing window and continue.

## Preconditions

- A playout session is active for the channel.
- The execution horizon is defined: `min_execution_hours` ahead of MasterClock, maintained by HorizonManager.
- A "required time window" is defined as: the block boundary at which ChannelManager will next need execution data.

## Observability

`POLICY_VIOLATION` log entry MUST be emitted with:
- `fault_class = "planning"`
- `channel_id`
- `required_utc_ms` (the timestamp for which no entry exists)
- `last_available_utc_ms` (end of the last committed execution entry)
- Reason: `"execution_horizon_exhausted"`

No playout decision outside the ExecutionWindowStore may follow this log entry for the same channel without an intervening repopulation by HorizonManager.

## Deterministic Testability

Using FakeAdvancingClock: populate ExecutionWindowStore with entries covering [T, T+min_execution_hours]. Advance clock to T+min_execution_hours+1ms without triggering HorizonManager. Trigger ChannelManager block evaluation. Assert `POLICY_VIOLATION` is logged. Assert no Asset Library call, no Playlog extension call, and no filler insertion occurs. Assert playout session enters a clean halt or freeze state, not a silent skip. No real-time waits required.

## Failure Semantics

**Planning fault** when the horizon is exhausted (HorizonManager failed to extend ahead of clock progression). **Runtime fault** if ChannelManager compensated silently rather than surfacing the failure.

## Required Tests

- `pkg/core/tests/contracts/test_scheduling_constitution.py` (EXEC-BOUNDARY-004, EXEC-BOUNDARY-005)

## Enforcement Evidence

- `HorizonManager` (`horizon_manager.py`) is responsible for maintaining the execution horizon ahead of clock progression — when the horizon is exhausted (no `ExecutionWindowStore` entry covers the required time), a `POLICY_VIOLATION` with `fault_class="planning"` is emitted.
- **ChannelManager does not compensate:** Per `INV-CHANNELMANAGER-NO-PLANNING-001`, `ChannelManager` has no imports of planning modules and cannot retry planning calls, insert filler, or query the Asset Library to fill the gap.
- `ChannelManager` signals the failure to `ProgramDirector` for clean halt or AIR-level fallback (freeze/pad/black per AIR invariants) — it does not silently skip the missing window.
- Dedicated contract tests (EXEC-BOUNDARY-004, EXEC-BOUNDARY-005) are referenced in `## Required Tests` but not yet implemented in the current tree.
