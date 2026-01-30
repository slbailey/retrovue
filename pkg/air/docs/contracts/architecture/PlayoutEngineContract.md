# Playout Engine Contract

_Related: [Proto Schema](../../../protos/playout.proto) · [Phase 6A Overview](../phases/Phase6A-Overview.md) · [Phase6A-0 Control Surface](../phases/Phase6A-0-ControlSurface.md) · [Renderer Contract](RendererContract.md) · [Metrics Contract](MetricsAndTimingContract.md)_

**Applies starting in:** Phase 6A.0 (control plane); many guarantees Deferred (Applies Phase 7+)  
**Status:** Enforced for Phase 6A–compatible sections; Deferred (Applies Phase 7+) for performance/TS/Renderer

**Principle:** Air must be correct before it is fast. Performance guarantees are explicitly deferred until correctness is contractually proven.

## Purpose

Define the observable guarantees for the RetroVue Playout Engine's gRPC control plane and telemetry. This contract specifies **what** the engine guarantees, not how it is implemented internally.

**THINK vs ACT:** Core performs THINK (authoritative timeline, what plays next, when transitions occur); Air performs ACT (executes explicit commands). Air **does not** make scheduling, timing, or sequencing decisions. Air does **not** track asset duration to decide transitions, initiate transitions on EOF or producer exhaustion, or decide "what comes next." Producers are treated as continuous sources; a producer ending does **not** imply a transition. Transitions occur **only** via explicit Core commands (e.g. LoadPreview, SwitchToLive). Air is intentionally "dumb" with respect to timing—it executes commands; it does not infer intent.

**Clock authority** lives in the Python runtime (MasterClock); Air enforces deadlines (e.g. `hard_stop_time_ms`) but does not compute schedule time. **Segment-based control** is canonical: execution is driven by LoadPreview (segment payload) + SwitchToLive (control-only); StartChannel initializes channel state and does not imply media playback.

---

## Part 1: gRPC Control Plane

**Phase applicability:** Part 1 is enforced from Phase 6A.0 onward, with Phase 6A–specific semantics below. Deferred guarantees are listed in [Deferred (Applies Phase 7+)](#deferred-applies-phase-7) and remain institutional knowledge for future phases.

### Service Definition

```proto
service PlayoutControl {
  rpc StartChannel(StartChannelRequest) returns (StartChannelResponse);
  rpc UpdatePlan(UpdatePlanRequest) returns (UpdatePlanResponse);
  rpc StopChannel(StopChannelRequest) returns (StopChannelResponse);
  rpc GetVersion(ApiVersionRequest) returns (ApiVersion);
  rpc LoadPreview(LoadPreviewRequest) returns (LoadPreviewResponse);
  rpc SwitchToLive(SwitchToLiveRequest) returns (SwitchToLiveResponse);
}
```

**Idempotency (per-RPC):**

- **StartChannel:** Duplicate calls with the same `channel_id` (already-started channel) → **idempotent success** (same result as first start). No requirement that payload (plan_handle, port) match; broadcast systems favor safe, idempotent start.
- **StopChannel:** Unknown or already-stopped channel → **idempotent success** (same result as first stop). Safe, idempotent stop.
- **LoadPreview:** Not idempotent by argument; loading new preview replaces any existing preview. Duplicate LoadPreview with same segment is defined as “replace” — acceptable but not required to be no-op.
- **SwitchToLive:** No segment payload; idempotency is by channel state (e.g. switching when already on that content may be no-op or success; see Phase 6A.0 for “no preview loaded” → error).
- **UpdatePlan:** Treated as optional/legacy in Phase 6A; idempotency rules deferred with plan semantics.

---

### StartChannel

**Purpose:** Initialize channel state for playout. Does **not** imply media playback or frame availability. **Execution begins only after LoadPreview + SwitchToLive.**

| Request Field | Type | Description |
|---------------|------|-------------|
| `channel_id` | int32 | Unique channel identifier |
| `plan_handle` | string | Opaque reference (accepted for proto compatibility; not interpreted in Phase 6A) |
| `port` | int32 | Port for frame output (reserved for future use) |

| Response Field | Type | Description |
|----------------|------|-------------|
| `success` | bool | Whether startup succeeded |
| `error_message` | string | (optional) Failure reason |

**Guarantees (Phase 6A):**

- On success, **channel state is initialized** and ready to accept LoadPreview for that channel.
- On failure, `success=false` with descriptive error message.
- Duplicate calls with same `channel_id` (already-started) → idempotent success.

**Deferred (Applies Phase 7+) (see [Deferred (Applies Phase 7+)](#deferred-applies-phase-7)):** “Channel ready within 2s”, “frames available within 2s”, and any metric indicating “ready == outputting frames” apply only after Phase 6A when Renderer/TS path exists.

---

### UpdatePlan

**Purpose:** Hot-swap playout plan without stopping the channel. **Optional/legacy for Phase 6A;** plans are not the canonical execution path; segment-based control (LoadPreview + SwitchToLive) is.

| Request Field | Type | Description |
|---------------|------|-------------|
| `channel_id` | int32 | Existing channel identifier |
| `plan_handle` | string | New playout plan reference |

| Response Field | Type | Description |
|----------------|------|-------------|
| `success` | bool | Whether update succeeded |
| `error_message` | string | (optional) Failure reason |

**Phase 6A:** Air may accept and return; no requirement to drive behavior from `plan_handle`.  
**Deferred (Applies Phase 7+):** Plan swap timing (e.g. 500ms), no frame loss, error state transitions — see [Deferred (Applies Phase 7+)](#deferred-applies-phase-7).

---

### StopChannel

**Purpose:** Gracefully stop playout for a channel.

| Request Field | Type | Description |
|---------------|------|-------------|
| `channel_id` | int32 | Channel to stop |

| Response Field | Type | Description |
|----------------|------|-------------|
| `success` | bool | Whether shutdown succeeded |
| `error_message` | string | (optional) Failure reason |

**Guarantees (Phase 6A):**

- Channel state becomes stopped; all producers for that channel are stopped and resources released.
- Stopping an already-stopped or unknown channel → **idempotent success**.

**Deferred (Applies Phase 7+):** “Stopped within 1 second” timing SLA — see [Deferred (Applies Phase 7+)](#deferred-applies-phase-7).

---

### LoadPreview

**Purpose:** Load the next segment into the **preview slot**. This is the **primary execution instruction** for segment-based control. Segment payload: `asset_path`, `start_offset_ms` (media-relative), `hard_stop_time_ms` (wall-clock epoch ms, authoritative). Air may stop at or before `hard_stop_time_ms` but must never play past it.

**End PTS / hard stop as guardrail (normative):** The end boundary (e.g. `hard_stop_time_ms` or derived end PTS) defines a **maximum output boundary** for that producer. It is **not** a signal to initiate a transition and **not** used by Air to decide when to switch. If the producer reaches the boundary and Core has not yet issued the next control command: Air **MUST NOT** emit frames from that producer beyond the boundary; Air **MUST** clamp output for that producer; Air **MUST** continue to satisfy always-valid-output (e.g. black/silence via BlackFrameProducer). This is a **failsafe containment mechanism**, not a scheduling action. Core still decides *when* transitions occur; Air enforces output limits. Design intent: prefer **bounded silence/black** over **content bleed**.

| Request Field | Type | Description |
|---------------|------|-------------|
| `channel_id` | int32 | Target channel |
| `asset_path` | string | Fully-qualified media file path (or asset reference) |
| `start_offset_ms` | int64 | Media-relative start position (ms). Join-in-progress. |
| `hard_stop_time_ms` | int64 | Wall-clock time (epoch ms) when this segment must stop. Authoritative. |

| Response Field | Type | Description |
|----------------|------|-------------|
| `success` | bool | Whether preview loaded |
| `message` | string | (optional) Status message |
| `shadow_decode_started` | bool | True if producer entered shadow decode mode (optional in 6A) |

**Guarantees (Phase 6A):**

- LoadPreview **before** StartChannel for that channel → **error** (`success=false`).
- On success, preview slot holds the segment for the channel; loading new preview replaces any existing preview.
- Invalid path (or unreadable file when file-backed producer is used) returns `success=false` with error.

**Deferred (Applies Phase 7+):** “Preview ready for switching” (first frame decoded), “live playout continues uninterrupted” — enforced when producers and Renderer/TS path exist; see [Deferred (Applies Phase 7+)](#deferred-applies-phase-7).

---

### SwitchToLive

**Purpose:** Promote the current preview to live atomically. **Control-only;** no segment payload.

| Request Field | Type | Description |
|---------------|------|-------------|
| `channel_id` | int32 | Target channel |

| Response Field | Type | Description |
|----------------|------|-------------|
| `success` | bool | Whether switch succeeded |
| `message` | string | (optional) Status message |
| `pts_contiguous` | bool | (optional) Continuity hint (not required in 6A) |
| `live_start_pts` | uint64 | (optional) Continuity details |

**Guarantees (Phase 6A):**

- **SwitchToLive** with no preview loaded for that channel → **error** (`success=false`).
- On success, preview content is promoted to live; old live producer is stopped or recycled; preview slot is cleared or ready for next LoadPreview.

**Deferred (Applies Phase 7+):** “Switch completes within 100ms”, “PTS continuity maintained”, “no visual discontinuity”, “no black frames, no stutter” — see [Deferred (Applies Phase 7+)](#deferred-applies-phase-7). Phase 6A does not enforce output continuity or Renderer/TS semantics.

---

## Part 2: Telemetry

**Phase applicability:** Metric **definitions** and **names** are preserved. **Deferred (Applies Phase 7+).** Validated when metrics pipeline and output path exist.

### Metrics Endpoint

**URL:** `GET /metrics`

**Response:** Content-Type: `text/plain; version=0.0.4`; Prometheus exposition format.  
**Deferred (Applies Phase 7+):** “Response time ≤ 100ms”.

### Required Metrics (definition only; enforcement Phase 7+)

| Metric | Type | Description |
|--------|------|-------------|
| `retrovue_playout_channel_state{channel}` | Gauge | Channel state: 0=stopped, 1=buffering, 2=ready, 3=error |
| `retrovue_playout_buffer_depth_frames{channel}` | Gauge | Frames currently buffered (0-60) |
| `retrovue_playout_frame_gap_seconds{channel}` | Gauge | Deviation from scheduled time |
| `retrovue_playout_decode_failure_count{channel}` | Counter | Decode errors |
| `retrovue_playout_frames_decoded_total{channel}` | Counter | Total frames decoded |
| `retrovue_playout_frames_dropped_total{channel}` | Counter | Frames dropped |
| `retrovue_playout_buffer_underrun_total{channel}` | Counter | Buffer underrun events |
| `retrovue_playout_decode_latency_seconds{channel}` | Histogram | Decode latency distribution |
| `retrovue_playout_channel_uptime_seconds{channel}` | Gauge | Time in ready state |

### Channel State Values

| Value | State | Meaning |
|-------|-------|---------|
| 0 | stopped | Channel not running |
| 1 | buffering | Building buffer, not ready for output |
| 2 | ready | Normal operation, outputting frames |
| 3 | error | Error condition, may be recovering |

**Note:** During Phase 6A, “ready” may mean “channel initialized and may have live producer”; exact semantics align with Phase 7 when Renderer/TS exist.

### Metric Guarantees (Phase 7+)

- **PE-TEL-001:** All metrics include `channel` label
- **PE-TEL-002:** Counters never decrease (reset to 0 on channel restart)
- **PE-TEL-003:** State transitions reflected in metrics
- **PE-TEL-004:** Histogram includes `_bucket`, `_sum`, `_count` suffixes

---

## Part 3: Performance Targets

**Phase applicability:** **Not enforced during Phase 6A.** Targets are **retained** as future intent for Phase 7+.

### Latency Targets (future enforcement)

| Operation | Target |
|-----------|--------|
| StartChannel → first frame | ≤ 2 seconds |
| UpdatePlan downtime | ≤ 500ms |
| StopChannel → stopped | ≤ 1 second |
| SwitchToLive | ≤ 100ms |
| Frame decode (p95) | ≤ 25ms |
| Frame decode (p99) | ≤ 50ms |

### Throughput Targets (future enforcement)

| Metric | Target |
|--------|--------|
| Channels per 4-core CPU | ≥ 4 @ 1080p30 |
| Frame rate per channel | ≥ 30 fps sustained |
| Memory per channel | ≤ 100 MB |

### Timing Targets (future enforcement)

| Metric | Target |
|--------|--------|
| Clock skew (p99) | ≤ 50ms |
| Frame gap (normal) | ≤ 16ms |
| PTS continuity during switch | No gaps or resets |

---

## Part 4: Error Handling

### Error Responses (Phase 6A)

All gRPC methods return structured responses:

| Field | Description |
|-------|-------------|
| `success` | `false` on error |
| `error_message` | Human-readable description |

gRPC status codes: `NOT_FOUND` (invalid channel_id), `INVALID_ARGUMENT` (invalid parameters), `INTERNAL` (resource/decode failure).

### Error Recovery (Deferred — Phase 7+)

The following are **not required for Phase 6A** but are **retained** as institutional knowledge:

- **PE-ERR-001:** Critical errors (decode crash) trigger automatic retry
- **PE-ERR-002:** Retry follows exponential backoff: 1s, 2s, 4s, 8s, 16s
- **PE-ERR-003:** Max 5 retries per minute
- **PE-ERR-004:** After max retries, channel falls back to slate output
- **PE-ERR-005:** Other channels unaffected by single-channel errors

---

## Part 5: Versioning

- **PE-VER-001:** API version is defined in proto file options
- **PE-VER-002:** Breaking changes require version bump
- **PE-VER-003:** Version changes require synchronized Core and Air releases

---

## Behavioral Rules Summary

### Phase 6A–Enforced

| Category | Rule | Guarantee |
|----------|------|-----------|
| Startup | PE-START-001 | Channel state initialized; execution only after LoadPreview + SwitchToLive |
| Startup | PE-START-002 | StartChannel idempotent on already-started channel |
| Stop | PE-STOP-001 | Stopped state; resources released |
| Stop | PE-STOP-002 | StopChannel idempotent on unknown/stopped channel |
| Control | PE-CTL-001 | LoadPreview before StartChannel → error |
| Control | PE-CTL-002 | SwitchToLive with no preview loaded → error |

### Deferred (Applies Phase 7+)

| Category | Rule | Guarantee (future) |
|----------|------|--------------------|
| Startup | PE-START-D | Channel ready within 2s; frames available within 2s |
| Update | PE-UPDATE-001 | Plan swap within 500ms |
| Update | PE-UPDATE-002 | No frame loss during swap |
| Stop | PE-STOP-D | Stopped within 1s |
| Switch | PE-SWITCH-001 | SwitchToLive completes within 100ms |
| Switch | PE-SWITCH-002 | PTS continuity maintained |
| Switch | PE-SWITCH-003 | No visual discontinuity |
| Telemetry | PE-TEL-001–004 | Metric presence and guarantees |
| Error | PE-ERR-001–005 | Auto-retry, backoff, slate, isolation |

---

## Deferred (Applies Phase 7+)

The following guarantees are **intentionally deferred** until Phase 7+ (see [Phase contracts](../phases/README.md)) when MPEG-TS serving, Renderer placement, and/or performance validation are in scope. **Nothing below is deleted;** it is re-scoped so Phase 6A tests do not conflict.

- **StartChannel:** “Channel ready within 2 seconds”, “frames available for consumption within 2 seconds”, and any definition of “ready == outputting frames”. **Why deferred:** Phase 6A does not require real media playback or frame output; execution begins only after LoadPreview + SwitchToLive.
- **UpdatePlan:** Hot-swap timing (500ms), no frame loss, error state semantics. **Why deferred:** Plans are optional/legacy in 6A; segment-based control is canonical.
- **StopChannel:** “Stopped within 1 second” timing. **Why deferred:** Phase 6A validates clean stop and idempotency; strict wall-clock timing is Phase 7.
- **SwitchToLive:** “Completes within 100ms”, “PTS continuity maintained”, “no visual discontinuity”, “no black frames, no stutter”. **Why deferred:** No Renderer or TS path in 6A; continuity is enforced when output path exists.
- **Telemetry:** Full metrics presence, response time ≤ 100ms. **Why deferred:** Phase 6A.0 may use stub implementations; metrics validated in Phase 7.
- **Performance targets:** All latency, throughput, and timing targets in Part 3. **Why deferred:** Phase 6A defers performance tuning and latency guarantees.
- **Error recovery:** PE-ERR-001 through PE-ERR-005 (retry, backoff, slate, isolation). **Why deferred:** Validation in Phase 7; 6A focuses on control surface and producer lifecycle.

---

## Test Coverage

**Phase 6A:** Tests verify control-plane behavior and Phase 6A semantics (e.g. StartChannel → initialized; LoadPreview before StartChannel → error; SwitchToLive with no preview → error; idempotent Start/Stop). See [Phase6A-0 Control Surface](../phases/Phase6A-0-ControlSurface.md).

**Phase 7+:** Tests for timing, metrics, switch seamlessness, and error recovery as in original contract (PE-START-D, PE-UPDATE-*, PE-SWITCH-*, PE-TEL-*, PE-ERR-*).

---

## See Also

- [Proto Schema](../../protos/playout.proto) — gRPC service definition
- [Phase 6A Overview](../phases/Phase6A-Overview.md) — segment-based control and deferrals
- [Phase6A-0 Control Surface](../phases/Phase6A-0-ControlSurface.md) — 6A.0 RPC semantics
- [Renderer Contract](RendererContract.md) — frame consumption (post-6A)
- [Metrics Contract](MetricsAndTimingContract.md) — telemetry details
