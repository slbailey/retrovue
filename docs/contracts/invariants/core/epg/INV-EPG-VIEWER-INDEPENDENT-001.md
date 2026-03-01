# INV-EPG-VIEWER-INDEPENDENT-001 — Available without viewers

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`, `LAW-CONTENT-AUTHORITY`

## Purpose

EPG data is a planning artifact derived from `ResolvedScheduleDay` (`LAW-DERIVATION`). Its availability MUST NOT depend on whether viewers are connected. A viewer tunes to the channel guide before tuning to a channel; if EPG data is only available when viewers are watching, the guide is useless. `LAW-CONTENT-AUTHORITY` places editorial truth in the scheduling pipeline, not in runtime viewer state.

## Guarantee

EPG data MUST be queryable for any resolved broadcast day regardless of whether viewers are connected to the channel. `get_epg_events()` MUST return results for any `(channel_id, time_range)` where a `ResolvedScheduleDay` exists, with no dependency on active playout sessions.

## Observability

Query `get_epg_events()` for a resolved future day with no active viewers or playout sessions. A non-empty result set confirms compliance. An error or empty result when a `ResolvedScheduleDay` exists is a violation.

## Deterministic Testability

Resolve a `ResolvedScheduleDay` for a future date. Without starting any playout session, call `get_epg_events()` for that date. Assert events are returned. No real-time waits required.

## Failure Semantics

**Runtime fault.** EPG unavailability without viewers indicates the query path has an incorrect dependency on runtime state (active sessions, connected viewers).

## Required Tests

- `pkg/core/tests/contracts/test_epg_invariants.py::TestInvEpgViewerIndependent001`

## Enforcement Evidence

TODO
