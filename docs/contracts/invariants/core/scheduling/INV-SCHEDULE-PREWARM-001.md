# INV-SCHEDULE-PREWARM-001 — Schedule compilation is a startup responsibility, not a viewer-trigger responsibility

Status: Invariant
Authority Level: Cross-layer
Derived From: `LAW-LIVENESS`, `INV-CHANNEL-STARTUP-NONBLOCKING-001`

## Purpose

Protects `LAW-LIVENESS` by ensuring that multi-day DSL compilation and EPG horizon building never execute on a viewer-triggered code path. If schedule compilation occurs during channel startup, the event loop is blocked for 200-400ms, starving concurrent playout streams and causing BACKPRESSURE drops. The scheduler daemon MUST own all compilation; viewer-triggered paths MUST assume the schedule is already prepared.

## Guarantee

All EPG horizon building and multi-day DSL compilation MUST be performed by the scheduler daemon at server startup or via background extension threads.

`ProgramDirector._get_or_create_manager()` and the `tune_in()` call path MUST NOT:
1. Invoke `DslScheduleService._build_initial()`.
2. Invoke `DslScheduleService.load_schedule()`.
3. Trigger schedule expansion beyond the current playlog block.

Channel startup MUST be O(1) with respect to scheduling horizon size.

## Preconditions

- ProgramDirector is in embedded mode (no external ChannelManagerProvider).
- `start()` has been called, which runs `_prewarm_channel_schedules()` and `_init_playlog_daemons()` for all configured channels.

## Observability

Any call path from `stream_channel()` or `hls_playlist()` that reaches `_build_initial()` or `load_schedule()` is a violation. Detectable via AST analysis of `_get_or_create_manager()` and structural scan of the `ProgramDirector` viewer-join path.

Current violation paths (pre-fix):
1. `stream_channel()` → `_get_or_create_manager()` → `_get_dsl_service()` → `svc.load_schedule()` → `_build_initial()` (first-ever service creation)
2. `stream_channel()` → `_get_or_create_manager()` → `schedule_service.load_schedule()` (redundant call on line 939)
3. `hls_playlist()` → same paths as above
4. EPG endpoint → `schedule_service.load_schedule()` (phase3 channels)

## Deterministic Testability

AST-scan `ProgramDirector._get_or_create_manager()` source and verify no calls to `load_schedule` or `_build_initial`. AST-scan `ProgramDirector._get_dsl_service()` source and verify no calls to `load_schedule`. Verify that `_prewarm_channel_schedules()` exists and calls `load_schedule`. No real-time waits required.

## Failure Semantics

**Runtime fault.** Schedule compilation on a viewer-triggered path is an architectural boundary violation — the viewer-join layer has assumed scheduler daemon responsibilities.

## Required Tests

- `pkg/core/tests/contracts/scheduling/test_inv_schedule_prewarm_001.py`

## Enforcement Evidence

TODO
