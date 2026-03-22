# INV-PLAYLOG-PLAN-VS-RUNTIME-001 — Playlog Plan vs runtime playlog authority

Status: Invariant  
Authority Level: Runtime  
Derived From: `LAW-RUNTIME-AUTHORITY`, `LAW-DERIVATION`

## Purpose

RetroVue names three related artifacts. Without explicit vocabulary, **playlog** becomes ambiguous in logs, APIs, and code review. This invariant fixes the authority split:

| Identifier (prose / config) | Meaning |
|-------------------------------|---------|
| **`playlog_plan`** | Persisted horizon: `PlaylistEvent` rows and the `playlog_plan` scheduling layer. |
| **`runtime_playlog`** | Ephemeral execution timeline produced when orchestration prepares the feed for AIR at wall-clock *now* (join-in-progress, trim, renumber, execution-only adjustments). |
| **as-run / transmission log** | Historical record of what aired (immutable after write). |

The Playlog Plan may **cache** planned segment payloads (including materialized paths and block wall times) for horizon extension, operator tooling, and evidence. That cache MUST NOT be confused with the executable structure AIR consumes.

## Guarantee

1. **Executable feed** — The segment list AIR decodes MUST be produced only through the documented runtime execution path (today: `ChannelManager` transforming persisted plan inputs). Execution MUST NOT treat raw `PlaylistEvent.segments` as the final emission timeline without that path.

2. **Join-aware offsets and order** — Authoritative **decode offsets** and **segment ordering for emission** at a given join time MUST be derived in the **runtime playlog** construction step (e.g. `_apply_jip_to_segments` and successors). Persisted `PlaylistEvent.segments` alone MUST NOT be interpreted as already containing final join-aware offsets or final emission order.

3. **Planned vs executed** — Fields stored on `PlaylistEvent` (including segment JSON and block `start_utc_ms` / `end_utc_ms`) are **Playlog Plan** materialization: planning and horizon truth, not a substitute for **runtime playlog** state or for as-run history.

## Non-goals

This invariant does **not** forbid storing segment dictionaries or URIs on `PlaylistEvent` for horizon materialization. It forbids **conflating** that persistence with the runtime executable timeline.

## Observability

Code review: any path that hands AIR or the muxer a segment list copied verbatim from `PlaylistEvent` without passing through runtime execution transforms is a violation.

## Deterministic Testability

With a fixed `PlaylistEvent`-shaped segment list and `jip_offset_ms > 0`, assert that the runtime transform output is not byte-identical to the persisted list as the executable timeline (trim, skip, offset bump, or renumbering occurs).

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_playlog_plan_vs_runtime_001.py`

## Enforcement Evidence

- `retrovue.runtime.channel_manager._apply_jip_to_segments` implements join-aware transformation between persisted segments and the list used for emission.
- `ChannelManager` builds `plan_segments` from scheduled block data before feeding AIR (see `_generate_next_block` / block plan assembly around `plan_segments` and JIP application).

## See also

- [program-schedule-playlog-plan-horizon.md](../../../../architecture/program-schedule-playlog-plan-horizon.md)
- `docs/core/GLOSSARY.md` — Playlog Plan vs runtime playlog
