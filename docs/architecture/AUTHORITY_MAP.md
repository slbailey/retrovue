# AUTHORITY MAP — Retrovue Single-Authority Enforcement

> Phase 1 output: maps current authority holders per concern, identifies overlaps, and
> ranks them by refactor priority. Feed into subsequent L3 phases.

Generated: 2026-03-28 (America/New_York)
Branch: `refactor/simplify-single-authority-l3`

---

## Summary

Four concerns require exactly one owner each. Current state: three concerns have
clearly-designated primary owners; two concerns have secondary decision points that
violate single-authority. One concern (diagnostics) has its entire activation logic in
a component that is not the narrowest scope for the job.

| Concern | Primary Owner | Secondary Decision Points | Overlap Risk |
|---|---|---|---|
| Clock/timebase | `MasterClock` (runtime/clock.py) | `dsl_schedule_service.py`, `playlist_builder_daemon.py` use raw `datetime.now()` | MEDIUM |
| Segment window (HLS) | `SegmentRing` (runtime/hls/segment_ring.py) | `ChannelManager` calls `segment_ring.clear()` on `stop_channel()` | LOW |
| Channel lifecycle | `ProgramDirector` (runtime/program_director.py) | `ChannelManager._linger_expire` calls `program_director.stop_channel()` back (callback inversion); deferred teardown poll in PD `_health_check_loop` | HIGH |
| Diagnostics | `ProgramDirector` (`_hls_diag_*`) | Triggering logic spread across: `hls_diag_event` (wallclock audit violation), `_hls_diag_note_reconnect_attempt` (30-second sliding window), and `_hls_diag_trigger` (inside segment serve) | MEDIUM |

---

## Concern 1 — Clock / Timebase

### Who should own it
`MasterClock` (`runtime/clock.py`) — one instance per ProgramDirector, injected everywhere.
Per LAW-CLOCK: "No subsystem may invent, reset, or locally reinterpret time."

### Current primary owner
`MasterClock` via `ProgramDirector._embedded_clock`. All live playout decisions go through
`ChannelManager.clock.now_utc()` → `BlockPlanProducer.clock.now_utc()`.

### Secondary decision points (violations)
| File | Location | Usage |
|---|---|---|
| `runtime/dsl_schedule_service.py` | Lines 1005, 1051 | `datetime.now(timezone.utc)` for horizon purge and expiry — bypasses injected clock |
| `runtime/playlist_builder_daemon.py` | Line 859 | `datetime.now(timezone.utc)` for DB timestamp — does not use clock |
| `runtime/program_director.py` | Line 2574 | `datetime.now(tz)` in `_generate_iptv_m3u` — cosmetic wall-clock only |
| `runtime/evidence_server.py` | Lines 261, 277, 294 | `datetime.now(timezone.utc)` for log/ack timestamps — evidence, not playout |

### Assessment
`dsl_schedule_service.py` is the highest-risk violation. Horizon purge timing
(`_purge_expired_program_schedule`) and `_maybe_extend_horizon` use raw wall-clock. Because
`DslScheduleService` receives no clock injection, it cannot participate in deterministic
test control. `playlist_builder_daemon.py` is a DB artifact timestamp — lower risk but
still creates an uncontrolled time source.

`evidence_server.py` and `program_director.py/iptv` are logging/diagnostic artifacts;
they do not affect playout decisions. Leave them.

### Action required
- **High priority**: Inject `MasterClock` into `DslScheduleService` constructor;
  replace bare `datetime.now(timezone.utc)` calls in `_purge_expired_program_schedule`
  and `_maybe_extend_horizon` with `self._clock.now_utc()`.
- **Medium priority**: Inject `MasterClock` into `PlaylistBuilderDaemon` (or pass
  `now_utc_ms` from caller).

---

## Concern 2 — Segment Window (HLS)

### Who should own it
`SegmentRing` (`runtime/hls/segment_ring.py`) — single bounded in-memory window per channel.
Owner of: what segments exist, what the manifest window is, eviction policy.

### Current primary owner
`SegmentRing`. Segments are pushed by `HlsSegmenter`; the window is read by
`ManifestGenerator`. Eviction is internal to `SegmentRing.push()`.

### Secondary decision points
| File | Location | Usage |
|---|---|---|
| `runtime/channel_manager.py` | `stop_channel()` body | `self._hls_segment_ring.clear()` — ChannelManager directly clears the ring on stop |

### Assessment
This is **low overlap**. The clear on stop is correct behavior (prevents stale segment
window from leaking across activations per "no stale HLS window" hard rule). However
the call crosses the ownership boundary: `ChannelManager` is reaching into `SegmentRing`
state directly rather than delegating to an HLS lifecycle coordinator.

The invariant is: clear must happen before a new session can serve segments. Currently
this is satisfied but is expressed as a direct field mutation in lifecycle code that
also handles teardown timeouts, recovery, and viewer counts.

### Action required
- **Low priority**: Extract HLS activation/deactivation into a thin `HlsLifecycle`
  helper or add `ChannelManager._reset_hls_for_stop()` that groups all three HLS
  reset operations (`clear()`, `update_counter()`, `reset_for_restart()`) as a single
  named boundary. No structural change required — just name the contract.

---

## Concern 3 — Channel Lifecycle

### Who should own it
`ProgramDirector` (`runtime/program_director.py`) per AGENTS.md embedded mode:
"PD is sole authority for ChannelManager lifecycle (creation, health, fanout, teardown)."

### Current primary owner
`ProgramDirector` — creates, health-checks, and stops ChannelManagers.

### Secondary decision points (HIGH — callback inversion)
| File | Location | Usage |
|---|---|---|
| `runtime/channel_manager.py` | `_linger_expire()` | Calls `program_director.stop_channel(channel_id)` — CM drives PD teardown |
| `runtime/channel_manager.py` | `_start_linger()` (no loop path) | Also calls `program_director.stop_channel()` directly when no event loop |
| `runtime/program_director.py` | `_health_check_loop()` lines ~1126-1141 | Polls `deferred_teardown_triggered()` to decide when to call `_stop_channel_internal` — dual decision point |

### Assessment
This is the **highest-priority overlap** in the codebase. The lifecycle authority is
split between two components in an inversion loop:

```
PD creates CM
  → CM starts producer (correct: CM owns producer)
  → CM decides "linger expired" (questionable: PD should decide teardown timing)
  → CM calls PD.stop_channel() (violation: CM is driving PD)
  → PD calls CM.stop_channel() (PD → CM, correct direction)
  → PD health_check_loop polls CM.deferred_teardown_triggered() (PD polls CM for teardown readiness)
```

The circular call chain means that linger logic lives in CM but the teardown authority
nominally lives in PD. This creates two interacting state machines that must agree, and
is a known source of reconnect bugs.

**Target model**: PD owns all teardown timing. CM fires an event/callback
(`on_linger_expired`) that tells PD "no viewers for N seconds". PD decides whether to
stop_channel. CM never calls PD.stop_channel() directly.

### Action required
- **Phase 2 target**: Invert the linger callback. CM exposes `on_linger_expired: Callable`
  (injected by PD at creation). CM calls it instead of calling PD.stop_channel() directly.
  PD registers a handler that calls `_stop_channel_internal`. This removes the CM→PD
  dependency and makes PD the sole teardown decision point.
- Also: simplify or remove `deferred_teardown_triggered()` poll — BlockPlan path always
  returns False, making this a dead poll loop.

---

## Concern 4 — Diagnostics

### Who should own it
A thin, bounded `HlsDiagnostics` unit — auto-expiring, per-channel, activated only by
specific observable invariant violations (not proactively).

### Current primary owner
`ProgramDirector` — contains all HLS diagnostic state (`_hls_diag_mode_until`,
`_hls_diag_reconnect_hits`, `_hls_diag_duration_s`) and all activation logic
(`_hls_diag_trigger`, `_hls_diag_note_reconnect_attempt`, `hls_diag_event`).

### Secondary decision points
| File | Location | Usage |
|---|---|---|
| `runtime/program_director.py` | Line 685 | `_hls_diag_trigger` from reconnect-hit count — activation decision logic embedded in PD |
| `runtime/program_director.py` | Line 691 | `hls_diag_event` triggers on wallclock audit violation from HlsSegmenter callback |
| `runtime/program_director.py` | Lines 2984, 3082 | `_hls_diag_is_active()` check during segment serve and manifest serve — diag state queried inside HTTP handler |

### Assessment
**Medium priority**. Diagnostics are currently self-contained within PD but are
structurally entangled: activation logic, state, and query are spread across 5+ methods
in a 3393-line file. This violates single-authority not because another component owns
diagnostics but because the diagnostic concern is insufficiently isolated from PD's
primary concern (lifecycle/mode management).

The risk: when changing reconnect logic (Phase 2), it will be hard to reason about
whether diagnostic state transitions are correct because they are not encapsulated.

### Action required
- **Phase 4 target**: Extract `_hls_diag_*` into a `HlsDiagnosticsState` dataclass
  (per channel, or per PD). PD holds one and delegates. This does not change behavior
  but makes the boundary explicit and testable in isolation.
- Ensure auto-expiry (`_hls_diag_mode_until` check in `_hls_diag_is_active`) is the
  ONLY expiry mechanism — no manual reset paths that could suppress diagnostics.

---

## Overlap Priority Ranking

1. **Channel lifecycle (HIGH)** — CM calling PD.stop_channel() is a callback inversion
   that creates a circular authority chain. This is the most likely root cause of
   reconnect edge cases. Fix in Phase 2.

2. **Clock/timebase — DslScheduleService (MEDIUM)** — schedule horizon decisions use
   bare wall-clock, excluding them from deterministic test control. Fix in Phase 1.5 /
   alongside Phase 2.

3. **Diagnostics isolation (MEDIUM)** — entangled within PD; not a runtime hazard
   today but will complicate Phase 2 lifecycle changes. Fix in Phase 4.

4. **Segment window (LOW)** — technically correct behavior, just poorly named.
   Extract as named boundary operation. Fix opportunistically in Phase 2.

---

## Dead Paths Identified

- `deferred_teardown_triggered()` in `ChannelManager`: BlockPlan path always returns
  `False`. The poll loop in `_health_check_loop` that checks this is dead code.
  **Delete** per L3 rules.

- `compute_jip_position()` in `runtime/channel_manager.py`: Marked `deprecated` in
  docstring ("Legacy utility from pre-INV-EXEC-NO-STRUCTURE-001 era"). Only retained
  for backward-compatible tests. **Delete** once those tests are migrated or removed.

- `_mock_grid_*` methods on `ChannelManager` (`_floor_to_grid`, `_calculate_join_offset`,
  `_calculate_filler_offset`, `_determine_active_content`, `_build_mock_grid_playout_plan`):
  Mock grid logic is now in `MockGridScheduleService`. Duplicate implementation on
  `ChannelManager` is unreachable in production. **Delete** from ChannelManager.

---

## Next Phase Recommendation

**Phase 2 — Lifecycle Hardening** (highest overlap risk):
1. Invert the linger callback: CM → `on_linger_expired` callback (injected by PD).
2. Delete `deferred_teardown_triggered()` dead poll and its call site in health_check_loop.
3. Delete mock grid methods from ChannelManager (dead code).
4. Add/adjust contract test for: "PD is sole teardown decision point (CM never calls
   PD.stop_channel directly)".
5. Inject `MasterClock` into `DslScheduleService` (clock authority cleanup).
