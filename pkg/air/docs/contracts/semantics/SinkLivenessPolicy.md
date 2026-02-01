# Sink Liveness Policy

**ID:** INV-P9-SINK-LIVENESS
**Status:** Canonical
**Owner:** OutputBus
**Applies to:** All frame routing paths through OutputBus

**Related:** [RealTimeHoldPolicy](RealTimeHoldPolicy.md) · [PlayoutInvariants-BroadcastGradeGuarantees](../laws/PlayoutInvariants-BroadcastGradeGuarantees.md)

---

## 1. Policy statement

**Policy A: Pre-attach discard is legal; post-attach delivery is mandatory.**

The OutputBus operates in two distinct phases:

| Phase | Sink State | Frame Behavior | Status |
|-------|-----------|----------------|--------|
| **Pre-attach** | No sink attached | Frames routed to bus are silently discarded | LEGAL |
| **Post-attach** | Sink attached and running | Frames MUST be delivered to sink | REQUIRED |

This policy enables "hot standby" operation where the render loop runs continuously while sink attachment is asynchronous.

---

## 2. Rationale (first principles)

### Professional broadcast precedent

In professional broadcast systems:

1. **Signal flow is continuous** — Video routers and buses always carry signal whether captured or not
2. **Downstream attachment is asynchronous** — Recorders, transmitters, and monitors connect/disconnect without stopping upstream
3. **Hot standby minimizes latency** — When a viewer connects, frames are immediately available

### RetroVue context

RetroVue's architecture separates concerns:

1. **Core** decides when to start a channel (editorial intent)
2. **AIR** runs the playout engine (runtime execution)
3. **Viewers** trigger sink attachment (output delivery)

A channel may be "running" (producer decoding, renderer pacing) before any viewer connects. This is the pre-attach phase. Frames are rendered to maintain timing continuity but discarded because no one is watching.

When a viewer connects:
1. Core calls `AttachStream` with a file descriptor
2. AIR creates an `MpegTSOutputSink` connected to that FD
3. The sink is attached to the OutputBus
4. Frames now flow to the viewer

This separation allows:
- Minimal latency when viewers connect (engine already running)
- Clean resource management (no sink = no network/file I/O)
- Clear phase boundaries for reasoning about state

---

## 3. Formal invariant definitions

### INV-P9-SINK-LIVENESS-001: Pre-attach discard

**Statement:** When no IOutputSink is attached to OutputBus, frames routed via `RouteVideo` and `RouteAudio` SHALL be silently discarded without error.

**Rationale:** The render loop must run at real-time cadence (per INV-PACING-001) regardless of downstream attachment. Blocking or erroring on missing sink would violate timing guarantees.

**Observable behavior:**
- `RouteVideo` called with `sink_ == nullptr` returns without error
- No frames are queued or buffered
- No warning or error is logged (this is expected operation)

### INV-P9-SINK-LIVENESS-002: Post-attach delivery

**Statement:** Once `AttachSink` succeeds, all frames routed via `RouteVideo` and `RouteAudio` MUST be delivered to the attached sink until explicit `DetachSink` is called.

**Rationale:** After sink attachment, frames represent viewer-visible output. Dropping frames silently would violate output continuity guarantees.

**Observable behavior:**
- `sink_->ConsumeVideo(frame)` called for every `RouteVideo` call
- `sink_->ConsumeAudio(frame)` called for every `RouteAudio` call
- Sink remains attached until explicit detach

### INV-P9-SINK-LIVENESS-003: Sink stability

**Statement:** The sink pointer SHALL NOT become null between successful `AttachSink` and explicit `DetachSink`. Spontaneous sink loss is a violation.

**Rationale:** Sink stability is required for output continuity. If the sink disappears unexpectedly (crash, disconnect), this must be surfaced as an error, not silently tolerated.

**Observable violation signature:**
```
POST-ATTACH sink=null detected (was attached, not detached)
```

---

## 4. Allowed and forbidden states

### Allowed states

| State | output_bus_ | sink_ | Behavior |
|-------|------------|-------|----------|
| No bus | nullptr | N/A | ProgramOutput waits (INV-P10-SINK-GATE) |
| Pre-attach | valid | nullptr | Frames discarded silently |
| Post-attach | valid | valid, running | Frames delivered to sink |
| Post-detach | valid | nullptr | Frames discarded silently (back to pre-attach) |

### Forbidden states

| State | Condition | Why forbidden |
|-------|-----------|---------------|
| Zombie sink | `sink_` valid but `!sink_->IsRunning()` after attach | Sink must run continuously once attached |
| Silent sink loss | `sink_` becomes null without DetachSink call | Violates INV-P9-SINK-LIVENESS-003 |

---

## 5. Boundary conditions

### Startup sequence

1. `StartChannel` → OutputBus created, no sink (pre-attach)
2. ProgramOutput starts, sees bus, begins rendering
3. Frames routed to bus, discarded (legal)
4. `AttachStream` called → sink created and attached (post-attach)
5. Frames now delivered to sink

### Shutdown sequence

1. `DetachStream` called → sink detached (back to pre-attach)
2. Frames discarded (legal)
3. `StopChannel` → OutputBus destroyed

### Edge cases

- **AttachStream before StartChannel**: Rejected by control plane (CanAttachSink returns false)
- **Multiple AttachStream calls**: Handled by `replace_existing` parameter
- **DetachStream without AttachStream**: Idempotent no-op

---

## 6. Owner subsystem

**Owner:** OutputBus (`pkg/air/src/output/OutputBus.cpp`)

**Responsibilities:**
- Track sink attachment state
- Route frames to sink when attached
- Discard frames when not attached (no error, no warning)
- Notify control plane on attach/detach transitions

**Non-owner subsystems:**
- ProgramOutput: Relies on OutputBus for routing, does not check sink state
- PlayoutEngine: Manages OutputBus lifecycle, does not route frames directly
- PlayoutControl: Gates attach/detach via CanAttachSink/CanDetachSink

---

## 7. Observability

### Telemetry (mandatory)

| Metric | Meaning |
|--------|---------|
| `frames_routed_pre_attach` | Frames discarded in pre-attach phase |
| `frames_delivered_post_attach` | Frames delivered to sink |
| `sink_attach_count` | Number of successful AttachSink calls |
| `sink_detach_count` | Number of successful DetachSink calls |

### Log signals

**Pre-attach (debug level, not warning):**
```
[OutputBus] Pre-attach: frame discarded (no sink)
```

**Post-attach (info level):**
```
[OutputBus] Sink attached: <sink_name>
[OutputBus] Sink detached: <sink_name>
```

**Violation (error level):**
```
[OutputBus] INV-P9-SINK-LIVENESS-003 VIOLATION: sink lost without detach
```

---

## 8. Contract test requirements

Tests MUST verify:

1. **Pre-attach discard is silent** — No errors when routing frames without sink
2. **Post-attach delivery** — All frames reach sink after attachment
3. **Sink stability** — Sink remains attached until explicit detach
4. **Phase transitions** — Attach/detach transitions work correctly

Tests MUST NOT assume:
- Any specific timing between StartChannel and AttachStream
- Sink will be attached before first frame is rendered

---

## 9. Implementation notes

### Current warning removal

The existing warning:
```
INV-P9-SINK-LIVENESS WARNING: sink=null with frames routing
```

This warning conflates pre-attach (legal) and post-attach (violation) states. Per this contract:

- **Pre-attach**: Remove warning entirely (expected behavior)
- **Post-attach sink loss**: Upgrade to error with distinct message

### Detection of post-attach sink loss

Track attachment state explicitly:
```cpp
bool sink_ever_attached_ = false;  // Set true on first AttachSink

void RouteVideo(const Frame& frame) {
  if (!sink_) {
    if (sink_ever_attached_) {
      // VIOLATION: was attached, now null without detach
      LOG_ERROR("INV-P9-SINK-LIVENESS-003 VIOLATION");
    }
    // Pre-attach discard: silent, legal
    return;
  }
  sink_->ConsumeVideo(frame);
}
```

---

## 10. Summary

The OutputBus operates in a "hot standby" model where frames may be routed before any sink is attached. Pre-attach frame discard is legal and expected. Once a sink is attached, all frames MUST be delivered until explicit detach. Spontaneous sink loss is a violation that must be detected and reported.
