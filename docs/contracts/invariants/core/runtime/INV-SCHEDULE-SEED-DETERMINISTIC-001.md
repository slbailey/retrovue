# INV-SCHEDULE-SEED-DETERMINISTIC-001 — Deterministic channel seed

Status: Invariant
Authority Level: Planning
Derived From: `LAW-LIVENESS`, `LAW-CONTENT-AUTHORITY`

## Purpose

Channel-specific seeds control movie selection ordering. If seeds change between process restarts, the compiled schedule changes, violating `LAW-CONTENT-AUTHORITY` (SchedulePlan is sole editorial authority) and causing EPG/playout disagreement that violates `LAW-LIVENESS`.

## Guarantee

Channel-specific seeds MUST be deterministic across process lifetimes. Same `channel_id` MUST always produce the same seed. Seeds MUST use `hashlib` (cryptographic, stable), not Python's `hash()` (randomized per process via `PYTHONHASHSEED`). A single shared `channel_seed()` function MUST be the sole source of channel seeds — no inline duplication.

## Preconditions

None. Applies unconditionally to all schedule compilation paths.

## Observability

`channel_seed(channel_id)` returns the same integer for the same input across all invocations. No call site uses `hash()` with a channel-related argument.

## Deterministic Testability

Call `channel_seed("showtime-cinema")` twice and assert identical results. Assert the result equals `int(hashlib.sha256(b"showtime-cinema").hexdigest(), 16) % 100000`. Use AST inspection to verify no `hash()` calls with channel arguments exist in `dsl_schedule_service.py`, `program_director.py`, or `epg.py`.

## Failure Semantics

Planning fault. Non-deterministic seeds produce different schedules on restart.

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_schedule_seed_deterministic.py`

## Enforcement Evidence

TODO
