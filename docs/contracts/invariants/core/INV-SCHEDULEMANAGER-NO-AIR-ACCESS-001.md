# INV-SCHEDULEMANAGER-NO-AIR-ACCESS-001 — Schedule Manager must never communicate with AIR

Status: Invariant
Authority Level: Cross-layer
Derived From: `LAW-RUNTIME-AUTHORITY`, `LAW-CONTENT-AUTHORITY`

## Purpose

AIR is the real-time playout engine. It owns frame timing, encoding, muxing, and transport. `LAW-RUNTIME-AUTHORITY` designates the PlaylogEvent / execution plan as the sole runtime authority — the data pipeline flows one way: planning produces execution artifacts, execution consumes them.

If Schedule Manager were to communicate directly with AIR, it would bypass ChannelManager as the coordination layer and introduce a second, unmediated command path into the playout engine. This produces two failure modes:

1. **Authority collision:** Schedule Manager issuing runtime commands to AIR would compete with ChannelManager's block-switching and session lifecycle management, creating undefined behavior in real-time playout.
2. **Dependency inversion:** AIR is a stateless execution engine that must not know about schedules, EPG, zones, or editorial intent. A direct Schedule Manager → AIR channel imports planning concepts into the execution layer, collapsing the boundary defined in `CLAUDE.md`.

The authoritative communication topology is:

```
Schedule Manager → ChannelManager → AIR
```

ChannelManager is the sole interface between planning artifacts and the playout engine. It mediates all interactions in both directions.

See also: `CLAUDE.md §COMPONENT RESPONSIBILITIES`, `ScheduleExecutionInterfaceContract_v0.1.md §10`.

## Guarantee

Schedule Manager MUST NOT hold a reference to, call, or send messages to any AIR interface — including but not limited to: the AIR gRPC control surface, any AIR session lifecycle API, any AIR producer or segment control interface.

All interaction between the planning layer and AIR MUST be mediated by ChannelManager. The dependency graph is:

- `ScheduleManager → ChannelManager`: permitted (planning authority supplies execution data to execution authority).
- `ChannelManager → AIR`: permitted (execution authority drives playout engine).
- `ScheduleManager → AIR`: **prohibited**.
- `AIR → ScheduleManager`: **prohibited**.
- `AIR → ChannelManager`: permitted for telemetry and state signals flowing upward.

## Preconditions

- AIR gRPC interfaces are exposed only to ChannelManager's runtime process context.
- Schedule Manager and ChannelManager run in distinct service contexts (or, if co-located, ScheduleManager's dependency graph must not include any AIR client stub or transport handle).

## Observability

Schedule Manager's dependency graph MUST contain no import of, reference to, or instantiation of any AIR client stub, AIR gRPC channel, or AIR session handle. This is enforced at the dependency injection boundary and verified by static analysis or import graph inspection.

Any call stack that originates in Schedule Manager and terminates in an AIR interface is a violation, regardless of whether it affects playout output.

## Deterministic Testability

Static: inspect Schedule Manager's dependency graph. Assert no AIR client stub, gRPC channel handle, or AIR transport reference appears as a direct or transitive import. Assert ChannelManager holds the only reference to AIR client interfaces.

Behavioral: in a test harness, replace the AIR process with a spy. Run Schedule Manager through a full planning cycle (plan creation, ScheduleDay generation, horizon extension). Assert the spy receives zero calls originating from Schedule Manager. Assert all AIR calls originate from ChannelManager only.

## Failure Semantics

**Runtime fault** if a Schedule Manager call stack reaches an AIR interface at runtime — the architectural boundary has been violated at the coordination layer. **Planning fault** if the dependency is introduced at build time (static import) — the violation exists regardless of whether it is exercised.

## Required Tests

- `pkg/core/tests/contracts/test_scheduling_constitution.py` (ARCH-BOUNDARY-001, ARCH-BOUNDARY-002)

## Enforcement Evidence

**Structural (no production code changes needed — the boundary is already clean):**
- `schedule_manager.py` and `schedule_manager_service.py` contain zero imports of AIR-related modules (`playout_session`, `PlayoutSession`, `playout_pb2`, `grpc`, or any `air` package path).
- `ScheduleManager.__init__` accepts only `ScheduleManagerConfig`; no AIR types in its parameter annotations or instance attributes.

**Tests:**
- ARCH-BOUNDARY-001 (`test_inv_schedulemanager_no_air_access_001_no_air_imports`): Uses `ast` module to parse both source files. Extracts all `import` and `from ... import` statements. Asserts none reference AIR-related tokens.
- ARCH-BOUNDARY-002 (`test_inv_schedulemanager_no_air_access_001_no_air_attributes`): Inspects `ScheduleManager.__init__` signature via `inspect`. Asserts no parameters carry AIR-related type annotations.
