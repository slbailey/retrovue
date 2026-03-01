# INV-EPG-IDENTITY-STABLE-001 — Identity stable in lock window

Status: Invariant
Authority Level: Planning
Derived From: `LAW-IMMUTABILITY`, `LAW-DERIVATION`

## Purpose

Once a `ResolvedScheduleDay` is materialized, its content identities are immutable (`LAW-IMMUTABILITY`). EPG events derived from that day MUST reflect the same identities on every query. If EPG identity drifts between queries, viewers see inconsistent listings and the derivation chain (`LAW-DERIVATION`) is broken.

## Guarantee

Within the locked execution window, repeated queries to `get_epg_events()` for the same channel and time range MUST return EPG events with identical `title`, `episode_id`, `episode_title`, `start_time`, and `end_time` values.

## Observability

Query `get_epg_events()` twice for the same (channel, time range). Compare all identity fields. Any difference between the two result sets is a violation.

## Deterministic Testability

Resolve a `ResolvedScheduleDay`, then call `get_epg_events()` twice with the same parameters. Assert all identity fields match between corresponding events. No real-time waits required.

## Failure Semantics

**Planning fault.** Identity drift indicates either the underlying `ResolvedScheduleDay` was mutated (violating `LAW-IMMUTABILITY`) or the derivation logic is non-deterministic.

## Required Tests

- `pkg/core/tests/contracts/test_epg_invariants.py::TestInvEpgIdentityStable001`

## Enforcement Evidence

TODO
