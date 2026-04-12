# INV-TIMELINE-SINGLE-AUTHORITY-001 — Single authoritative timeline

Status: Invariant
Authority Level: Cross-layer
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-CLOCK`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` and `LAW-CLOCK` by ensuring all system components derive their timeline answers from a single authority. Multiple independent representations create divergence between what is played, displayed, and recorded.

## Guarantee

At any point in time, there MUST be exactly one authoritative timeline per channel. All system components — playback, EPG, scheduling, and planning — MUST derive their answers from this single timeline.

The sole editorial authority path is: **DSL schedule definitions → DslScheduleService compilation → ScheduleRevision/ScheduleItem**. No CRUD path, manual insertion, or alternative compilation pipeline may produce or modify ScheduleRevision rows. The former SchedulePlan → Zone → Program CRUD island is retired (RETA-88 Option B).

## Observability

For any time T, all system interfaces MUST return the same program, start time, and duration.

## Deterministic Testability

Query "what is scheduled at time T on channel C" through three interfaces: playback block lookup, EPG query, and playlog plan. All three MUST return the same program title, start time, and duration.

## Failure Semantics

**Cross-layer fault.** Divergent authorities cause the viewer to see one program while the EPG displays another and the as-run log records a third.

## Required Tests

- `server/tests/contracts/test_inv_timeline_authority.py`

## Enforcement Evidence

- `TestTimelineSingleAuthority::test_build_initial_uses_load_existing_timeline` — _build_initial has _load_existing_timeline for DB loading
- `TestTimelineSingleAuthority::test_load_existing_timeline_returns_blocks_and_day_sets` — signature accepts channel_id, start_date, horizon_days
- `TestTimelineSingleAuthority::test_save_compiled_schedule_refuses_existing_revision` — delegates to revision writer with conflict resolution
