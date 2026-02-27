# INV-PLAYLOG-DERIVED-FROM-PLAYLIST-001 — Every PlaylogEvent must be traceable to a Playlist entry

Status: Invariant
Authority Level: Runtime
Derived From: `LAW-DERIVATION`, `LAW-RUNTIME-AUTHORITY`, `LAW-CONTENT-AUTHORITY`

## Purpose

Enforces `LAW-DERIVATION` at the runtime layer. A PlaylogEvent that cannot be traced to a Playlist entry represents content introduced into the execution stream outside the constitutional derivation chain. This would allow the runtime layer to play content that was never authorized by a SchedulePlan, violating `LAW-CONTENT-AUTHORITY`. It also severs the audit chain required by `INV-ASRUN-TRACEABILITY-001`.

## Guarantee

Every PlaylogEvent entry, except those created by an explicit recorded operator override, must be derived from a Playlist entry that is itself traceable to a ScheduleDay.

A PlaylogEvent with no Playlist reference and no operator override record MUST NOT be persisted.

## Preconditions

- PlaylogEvent is not an operator-initiated override (i.e., no override record exists for it).

## Observability

Application-layer enforcement at PlaylogEvent creation time. Audit query: any PlaylogEvent with no Playlist reference and no override record is a violation. PlaylogService MUST verify derivation before committing each entry.

## Deterministic Testability

Attempt to create a PlaylogEvent without a Playlist reference and without an override record via the PlaylogService. Assert creation is rejected. Separately, create one with a valid Playlist reference and assert it is accepted. No real-time waits required.

## Failure Semantics

**Planning fault.** The PlaylogService generated an entry outside the constitutional derivation chain. Indicates a logic error in the Playlist-to-Playlog conversion.

## Required Tests

- `pkg/core/tests/contracts/test_inv_playlog_derived_from_playlist.py`

## Enforcement Evidence

TODO
