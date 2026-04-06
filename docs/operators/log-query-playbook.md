# Log Query Playbook

Recipes for tracing viewer sessions and channel lifecycle events in RetroVue production logs.

## Prerequisites

RetroVue Core uses structlog with `JSONRenderer`. Every log line is a JSON object on stdout with these standard fields:

```json
{"event": "<message>", "logger": "<module>", "level": "debug", "timestamp": "2026-04-06T12:34:56.789Z"}
```

Lifecycle events emitted by `ChannelManager._emit_lifecycle_event()` follow the format:

```
[lifecycle] channel=<channel_id> event=<event_name> event_scope=<session|channel> key=value ...
```

This message appears in the structlog `event` field.

### Event scoping (INV-LIFECYCLE-OBSERVABILITY-001)

Every lifecycle event includes `event_scope`:
- `session` — per-viewer events (`viewer_join`, `viewer_leave`). Always include `session_id`.
- `channel` — per-channel state transitions (`channel_activated`, `first_segment`, `linger_start`, `linger_expire`, `teardown`). Include `trigger_session_id` when a single session caused the transition.

## Production Log Access

On the production server (`192.168.1.199`):

```bash
ssh 192.168.1.199
cd /opt/retrovue

# Live tail (all logs)
journalctl -u retrovue -f -o cat

# Last hour, JSON output
journalctl -u retrovue --since "1 hour ago" -o cat
```

If running via docker or direct process (no systemd unit), substitute with:

```bash
# Docker
docker logs -f retrovue-core 2>&1

# Direct process — logs go to stdout
# Redirect at launch: retrovue serve 2>&1 | tee /var/log/retrovue/core.log
```

> **Note:** Core writes structlog JSON to stdout/stderr. No file sink is configured by default. Ensure your capture method preserves the JSON structure (use `-o cat` with journalctl, not the default syslog format).

---

## Lifecycle Event Queries

### Filter all lifecycle events

```bash
journalctl -u retrovue --since "1 hour ago" -o cat \
  | jq -c 'select(.event | test("^\\[lifecycle\\]"))'
```

### Channel activation

When did a channel start producing segments?

```bash
jq -c 'select(.event | test("event=channel_activated"))' < logs.json
```

Sample output fields: `channel`, `event_scope=channel`, `mode`, `viewer_count`, `jip_offset_ms`, `trigger_session_id`.

### First segment produced

When did the first HLS segment land in the ring buffer after activation?

```bash
jq -c 'select(.event | test("event=first_segment"))' < logs.json
```

Sample output fields: `channel`, `segment_index`, `viewer_count`.

### Viewer join

```bash
jq -c 'select(.event | test("event=viewer_join"))' < logs.json
```

Fields: `channel`, `session_id`, `viewer_count`.

### Viewer leave

```bash
jq -c 'select(.event | test("event=viewer_leave"))' < logs.json
```

Fields: `channel`, `session_id`, `viewer_count`.

### Linger lifecycle

```bash
# Linger start (grace period begins after last viewer leaves)
# Includes trigger_session_id of the last viewer who left
jq -c 'select(.event | test("event=linger_start"))' < logs.json

# Linger expire (no viewers reconnected — teardown follows)
jq -c 'select(.event | test("event=linger_expire"))' < logs.json

# Linger cancel (viewer reconnected during grace period)
jq -c 'select(.event | test("event=linger_cancel"))' < logs.json
```

### Teardown

```bash
jq -c 'select(.event | test("event=teardown"))' < logs.json
```

Fields: `channel`, `reason`, `viewer_count`.

---

## Scope-Based Filtering

### All session-scoped events (per-viewer)

```bash
jq -c 'select(.event | test("event_scope=session"))' < logs.json
```

### All channel-scoped events (per-channel state)

```bash
jq -c 'select(.event | test("event_scope=channel"))' < logs.json
```

### Find which session triggered a channel activation

```bash
jq -r 'select(.event | test("event=channel_activated"))
  | .event
  | capture("trigger_session_id=(?<sid>[^ ]+)")
  | .sid' < logs.json
```

---

## Session Tracing

### Trace a single viewer session end-to-end

Given a `session_id`, extract all lifecycle events for that session:

```bash
SESSION="abc12345-..."
jq -c "select(.event | test(\"session_id=$SESSION\"))" < logs.json
```

Expected sequence: `viewer_join → viewer_leave` (and possibly `linger_start` if last viewer).

### Find all sessions for a channel

```bash
CHANNEL="my-channel"
jq -c "select(.event | test(\"\\[lifecycle\\] channel=$CHANNEL\"))" < logs.json
```

### Extract session_id values from join events

```bash
jq -r 'select(.event | test("event=viewer_join"))
  | .event
  | capture("session_id=(?<sid>[^ ]+)")
  | .sid' < logs.json
```

---

## HLS Session Manager Events

The HLS phantom session manager (`HlsSessionManager`) emits its own lifecycle events:

| Event | Meaning |
|-------|---------|
| `first_viewer` | First phantom session touched (0→1 transition) |
| `last_viewer` | Last phantom session expired or removed (1→0 transition) |
| `reap_expiration` | Expired sessions cleaned up during reap cycle |

These events include `session_id` and `transition_count`.

```bash
jq -c 'select(.event | test("event=(first_viewer|last_viewer|reap_expiration)"))' < logs.json
```

---

## Aggregate Queries

### Count events by type in the last hour

```bash
jq -r 'select(.event | test("^\\[lifecycle\\]"))
  | .event
  | capture("event=(?<ev>[^ ]+)")
  | .ev' < logs.json \
  | sort | uniq -c | sort -rn
```

### Timeline of a channel's lifecycle (human-readable)

```bash
CHANNEL="my-channel"
jq -r "select(.event | test(\"\\[lifecycle\\] channel=$CHANNEL\"))
  | [.timestamp, .event] | @tsv" < logs.json
```

### Viewer count over time

```bash
CHANNEL="my-channel"
jq -r "select(.event | test(\"\\[lifecycle\\] channel=$CHANNEL\"))
  | .event
  | capture(\"event=(?<ev>[^ ]+).*viewer_count=(?<vc>[^ ]+)\")
  | [.ev, .vc] | @tsv" < logs.json
```

---

## Troubleshooting Scenarios

### "Channel is stuck — no segments produced"

Check if activation happened and whether first_segment followed:

```bash
CHANNEL="stuck-channel"
jq -c "select(.event | test(\"channel=$CHANNEL event=(channel_activated|first_segment)\"))" < logs.json
```

If `channel_activated` appears but `first_segment` does not, the producer started but is not producing segments. Check for producer errors in non-lifecycle logs.

### "Viewer reports stream cut off"

Trace the session:

```bash
SESSION="viewer-session-id"
jq -c "select(.event | test(\"session_id=$SESSION\"))" < logs.json
```

Look for `viewer_leave` followed by `linger_start` → `linger_expire` → `teardown`. If teardown happened while the viewer was still connected, this indicates a session tracking bug.

### "Channel keeps restarting"

Look for repeated activation/teardown cycles:

```bash
CHANNEL="flapping-channel"
jq -r "select(.event | test(\"channel=$CHANNEL event=(channel_activated|teardown)\"))
  | [.timestamp, .event] | @tsv" < logs.json
```

Frequent cycles suggest viewers connecting briefly and the linger period expiring before the next viewer arrives.
