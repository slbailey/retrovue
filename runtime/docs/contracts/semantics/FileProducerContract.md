# ⚠️ RETIRED — Superseded by BlockPlan Architecture

**See:** [Phase8DecommissionContract.md](../../../../docs/contracts/architecture/Phase8DecommissionContract.md)

This document describes legacy playlist/Phase8 execution and is no longer active.

---

# File Producer Contract

_Related: [Playout Engine Contract](PlayoutEngineContract.md) · [Phase 6A Overview](../phases/Phase6A-Overview.md) · [Phase6A-2 FileBackedProducer](../phases/Phase6A-2-FileBackedProducer.md) · [Renderer Contract](RendererContract.md)_

**Applies starting in:** Phase 6A.2 (lifecycle, segment params); frame rate, format, buffer, and performance Deferred (Applies Phase 7+)  
**Status:** Enforced for Phase 6A–compatible rules; remainder Deferred (Applies Phase 7+) with intent preserved

**Principle:** Air must be correct before it is fast. Performance guarantees are explicitly deferred until correctness is contractually proven.

## Purpose

Define the observable guarantees for the **File Producer** — one kind of execution producer that reads video files and produces decoded frames. File-backed producers may use ffmpeg subprocesses or libav internally; decoding is an implementation detail. This contract specifies **what** the producer guarantees (lifecycle and segment semantics first; output contract when Renderer/TS path exists). **Producers are passive:** they respond to Start/Stop only; the **engine** owns preview/live slots, switch timing, and deadline enforcement. Producers must not self-switch or interpret schedules.

---

## Phase 6A–Enforced Rules (6A.2)

### PROD-010: Lifecycle Management

**Guarantee:** Producer supports clean start, stop, and teardown. Fits ExecutionProducer interface (Start(segment params), Stop()).

**Phase applicability:** 6A.2+

**Observable behavior:**
- Producer starts in stopped state.
- **Start(segment)** succeeds on first call with valid segment (asset_path, start_offset_ms, hard_stop_time_ms); duplicate start semantics are implementation-defined (idempotent false or no-op acceptable).
- **Stop()** stops production and is idempotent; blocks until complete or within bounded time.
- On teardown (channel stop or segment boundary), resources are released; no orphan processes (e.g. ffmpeg).

**Segment params:** From LoadPreview: `asset_path`, `start_offset_ms` (media-relative), `hard_stop_time_ms` (wall-clock epoch ms). Producer must honor start offset (seek at or before start_offset_ms) and must stop **at or before** hard_stop_time_ms. Engine may enforce hard stop by duration limit and/or wall-clock supervision.

**End PTS / hard stop as safety clamp:** The end boundary (e.g. derived from `hard_stop_time_ms`) is a **maximum output boundary**—a **guardrail**, not a trigger. It is **not** used to decide when to switch producers; it exists solely to prevent output beyond the agreed boundary (clock skew, late commands, content bleed). The producer MUST NOT emit frames beyond this boundary. If the producer reaches the boundary and Core has not yet issued the next command, the engine clamps output and satisfies always-valid-output (e.g. black/silence). This is **failsafe containment**, not a scheduling action. Transitions remain only via explicit Core commands (e.g. SwitchToLive).

---

### PROD-010b: Invalid Input Handling (6A.2)

**Guarantee:** Invalid or unreadable asset yields defined error.

**Observable behavior:**
- Invalid path or unreadable file: LoadPreviewResponse.success=false (or equivalent); producer does not enter running state; no crash.

**Deferred:** Fallback to synthetic frames (PROD-030) — optional post-6A; 6A.2 may require only defined error.

---

## Deferred (Applies Phase 7+) — Institutional Knowledge Preserved

The following guarantees are **not required for Phase 6A** but are **retained** for Phase 7+ when frame output, buffer depth, and performance are enforced. **Nothing is deleted;** only re-scoped.

### PROD-011: Frame Production Rate

**Guarantee:** Producer delivers decoded frames at target rate.

**Observable behavior (future):**
- Frames produced at configured `target_fps` (default: 30 fps).
- Frame interval approximately `1.0 / target_fps` seconds; no frame bursts.
- Verification: `frames_produced / elapsed_time ≥ target_fps × 0.95`.

**Why deferred:** Phase 6A.2 validates segment start/stop and lifecycle; sustained frame rate and pacing validated when consumer (Renderer/TS) exists.

---

### PROD-012: Frame Format

**Guarantee:** All frames are decoded YUV420 with valid metadata (when output path exists).

**Observable behavior (future):**
- Frames decoded (not encoded packets); format YUV420 planar; size `width × height × 1.5` bytes.
- Metadata: PTS, DTS, duration, asset_uri, dimensions.

**Why deferred:** Phase 6A.2 output may be hard-coded (null sink or test file); full format contract applies when Renderer or TS sink consumes frames.

---

### PROD-013: PTS Monotonicity

**Guarantee:** Frame PTS values monotonically increasing within segment.

**Observable behavior (future):** `frame[i].pts < frame[i+1].pts`; DTS ≤ PTS; duration approximately `1.0 / target_fps`.

**Why deferred:** Enforced when frame pipeline and continuity (e.g. SwitchToLive PTS) are required.

---

### PROD-020: Backpressure Handling

**Guarantee:** Producer handles full buffer gracefully.

**Observable behavior (future):** When buffer full, producer backs off; `buffer_full_count` increments; no CPU spinning.

**Why deferred:** Phase 6A does not require buffer depth contracts; validated with Renderer/TS.

---

### PROD-021: Buffer Filling

**Guarantee:** Producer fills buffer when consumer idle (depth ≥ 30 during steady-state; capacity e.g. 60 frames).

**Why deferred:** Buffer depth and filling are post-6A when frame consumer exists.

---

### PROD-030: Decode Fallback

**Guarantee:** Producer may fall back to synthetic frames if decode init fails (e.g. libav/ffmpeg unavailable).

**Observable behavior (future):** Fallback to synthetic; error logged; producer does not crash; synthetic frames have valid metadata and format.

**Why deferred:** Phase 6A.2 may define “invalid path → error” only; fallback is optional post-6A.

---

### PROD-031: Decode Error Recovery

**Guarantee:** Transient decode errors do not stop producer; log, retry, resume.

**Why deferred:** Validation when sustained decode pipeline and metrics exist.

---

### PROD-032: End of File Handling

**Guarantee:** Producer stops gracefully on EOF; no frames after EOF.

**Phase note:** For 6A.2, segment is bounded by hard_stop_time_ms; EOF may also stop segment. Intent preserved for file-backed streams.

---

### PROD-040: Teardown Operation

**Guarantee:** Graceful teardown with bounded timeout; drain buffer up to timeout then force stop.

**Why deferred:** Full teardown timing and buffer drain validated post-6A.

---

### PROD-041: Statistics Accuracy

**Guarantee:** Statistics (frames_produced, buffer_full_count, etc.) accurately reflect state; thread-safe to read.

**Why deferred:** Producer telemetry validated when metrics pipeline is required (Phase 7+).

---

## Performance Targets (Future Enforcement — Phase 7+)

### Throughput

| Metric | Target |
|--------|--------|
| Frame rate (1080p30) | ≥ 30 fps sustained |
| Frame rate (4K) | ≥ 30 fps with hardware acceleration |

### Latency

| Metric | Target |
|--------|--------|
| Frame production (p95, 1080p30) | ≤ 33ms |
| Frame production (p95, 4K) | ≤ 50ms with HW accel |

### Resources

| Metric | Target |
|--------|--------|
| Memory per channel | ≤ 250 MB |
| CPU per channel (1080p30) | ≤ 30% single core |

**Why deferred:** Phase 6A explicitly defers performance tuning and latency guarantees.

---

## Error Handling (Summary)

| Condition | Phase 6A | Deferred (Applies Phase 7+) |
|-----------|----------|----------------------|
| Invalid path / unreadable file | success=false; no crash | same + optional synthetic fallback |
| Transient decode error | — | Log, retry with backoff |
| Buffer full | — | Backoff, retry when space available |
| Teardown timeout | Stop; release resources | Force stop within timeout + 100ms |

---

## Telemetry (Definitions Preserved; Enforcement Phase 7+)

| Metric | Type | Description |
|--------|------|-------------|
| `producer_frames_produced_total{channel}` | Counter | Frames successfully produced |
| `producer_buffer_full_total{channel}` | Counter | Backpressure events |
| `producer_decode_errors_total{channel}` | Counter | Decode failures |
| `producer_running{channel}` | Gauge | 1 if running, 0 if stopped |

---

## Behavioral Rules Summary

| Rule | Guarantee | Phase |
|------|-----------|--------|
| PROD-010 | Clean lifecycle (Start/Stop); ExecutionProducer interface | 6A.2+ |
| PROD-010b | Invalid path → defined error | 6A.2+ |
| PROD-011 | Target frame rate maintained | 7+ |
| PROD-012 | Decoded YUV420 format | 7+ |
| PROD-013 | PTS monotonicity | 7+ |
| PROD-020 | Graceful backpressure | 7+ |
| PROD-021 | Buffer filling | 7+ |
| PROD-030 | Decode fallback to synthetic | 7+ |
| PROD-031 | Decode error recovery | 7+ |
| PROD-032 | EOF handling | 7+ (intent in 6A) |
| PROD-040 | Bounded teardown | 7+ |
| PROD-041 | Accurate statistics | 7+ |

---

## Test Coverage

| Rule | Test | Phase |
|------|------|--------|
| PROD-010, PROD-010b | `test_producer_lifecycle`, segment start/stop | 6A.2+ |
| PROD-011–013 | `test_producer_frame_production` | 7+ |
| PROD-020, PROD-021 | `test_producer_backpressure` | 7+ |
| PROD-030–032 | `test_producer_error_handling` | 7+ |
| PROD-040 | `test_producer_teardown` | 7+ |
| PROD-041 | `test_producer_statistics` | 7+ |

---

## See Also

- [Playout Engine Contract](PlayoutEngineContract.md) — control plane
- [Phase 6A Overview](../phases/Phase6A-Overview.md) — segment-based control
- [Phase6A-2 FileBackedProducer](../phases/Phase6A-2-FileBackedProducer.md) — minimal file-backed producer
- [Renderer Contract](RendererContract.md) — frame consumption (post-6A)
- [Contract Hygiene Checklist](../../standards/contract-hygiene.md) — authoring guidelines
