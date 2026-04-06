# INV-LIFECYCLE-OBSERVABILITY-001 — Runtime Lifecycle Observability

## Behavioral Guarantee

Runtime lifecycle transitions MUST emit structured log events at DEBUG level.
Every lifecycle event MUST include an `event_scope` field (`session` or `channel`)
to distinguish per-viewer events from per-channel state transitions.

Session-scoped events MUST include `session_id`.
Channel-scoped events MUST include `channel_id`.
Channel-scoped events MAY include `trigger_session_id` when a single session
clearly caused the transition.
No lifecycle event may omit both `session_id` and `channel_id`.

## Authority Model

`ChannelManager._emit_lifecycle_event()` is the sole structured lifecycle event
emitter for channel runtime. `HlsSessionManager` emits HLS phantom session events.

## Boundary / Constraint

The following transitions MUST be logged:

| Event | Scope | Required IDs |
|---|---|---|
| `channel_activated` | channel | `channel_id`, `trigger_session_id` (first viewer) |
| `first_segment` | channel | `channel_id` |
| `viewer_join` | session | `session_id`, `channel_id` |
| `viewer_leave` | session | `session_id`, `channel_id` |
| `linger_start` | channel | `channel_id`, `trigger_session_id` (last viewer) |
| `linger_expire` | channel | `channel_id` |
| `teardown` | channel | `channel_id` |

All events MUST use structured `key=value` fields. Free-form log strings
for lifecycle events are prohibited.

All events MUST be emitted at DEBUG level. INFO-level lifecycle events
are prohibited (INFO duplicates for operational logging are separate and
not governed by this invariant).

## Violation

- A lifecycle transition with no log event (silent state change).
- A session-scoped event missing `session_id`.
- A channel-scoped event missing `channel_id`.
- A lifecycle event missing `event_scope`.
- Free-form log strings where structured fields are required.
- A lifecycle event emitted at INFO level instead of DEBUG.

## Future Considerations

A `correlation_id` field may be introduced if lifecycle events require
cross-scope grouping or multi-trigger causality tracking (e.g. schedule-driven
transitions overlapping viewer-driven transitions). This is deferred until such
scenarios exist. The current ID trio (`session_id` / `channel_id` /
`trigger_session_id`) provides full end-to-end traceability for all present
use cases.

## Derives From

`LAW-SIMPLICITY`, `LAW-LIVENESS`

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_lifecycle_observability_session_manager.py`
  - V8a: `first_viewer` emits structured DEBUG
  - V8b: `last_viewer` emits structured DEBUG
  - V8c: `reap_expiration` emits structured DEBUG
  - No INFO-level lifecycle events
- `tests/contracts/test_inv_lifecycle_traceability.py`
  - `channel_activated` emits structured DEBUG with `event_scope=channel`
  - `viewer_join` emits structured DEBUG with `event_scope=session` and `session_id`
  - `viewer_leave` emits structured DEBUG with `event_scope=session` and `session_id`
  - `linger_start` emits structured DEBUG with `event_scope=channel`
  - `linger_expire` emits structured DEBUG with `event_scope=channel`
  - `teardown` emits structured DEBUG with `event_scope=channel`
  - `first_segment` emits structured DEBUG with `event_scope=channel`
- `tests/contracts/test_channel_manager_observability.py`
  - `channel_activated` includes `trigger_session_id`
  - `linger_start` includes `trigger_session_id`
  - `first_segment` does not require `trigger_session_id`
  - All channel-scoped events include `event_scope=channel`
  - All session-scoped events include `event_scope=session`

## Enforcement Evidence

TODO
