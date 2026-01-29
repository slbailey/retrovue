# MPEG-TS Playout Sink Contract

_Related: [Playout Engine Contract](PlayoutEngineContract.md) · [Phase Model](../../contracts/PHASE_MODEL.md) · [Phase 6A Overview](Phase6A-Overview.md) · [File Producer Contract](FileProducerDomainContract.md) · [Timing Contract](MpegTSPlayoutSinkTimingContract.md)_

**Applies starting in:** Phase 7+ (MPEG-TS serving)  
**Status:** Deferred (Applies Phase 7+); Enforced when TS output is in scope

**Principle:** Air must be correct before it is fast. Performance guarantees are explicitly deferred until correctness is contractually proven.

## Phase 6A Deferral

**This contract is not enforced during Phase 6A.** Phase 6A explicitly defers **MPEG-TS serving**: real TS output, tune-in, byte-level checks. During 6A.0–6A.3, execution uses hard-coded output (e.g. null sink or test file); no TS streaming. All guarantees below are **preserved** as institutional knowledge and **future intent**; they apply when the MPEG-TS sink path is implemented (e.g. Phase 7). Nothing in this document is deleted — only scoped to post-6A enforcement.

---

## Purpose

Define the observable guarantees for the **MPEG-TS Playout Sink** — the component that consumes decoded frames, encodes them to H.264, wraps them in MPEG-TS format, and streams over TCP. This contract specifies **what** the sink guarantees, not how it is implemented. Output responsibility is an intentional design boundary: either Air outputs MPEG-TS directly or a Renderer/sink component muxes MPEG-TS; this contract applies when the sink path is used.

---

## Core Guarantees

### SINK-010: Lifecycle Management

**Guarantee:** Sink supports clean start, stop, and teardown.

**Observable behavior:**
- Sink starts in stopped state
- Start returns false if already running (idempotent)
- Stop blocks until complete and is idempotent
- Destructor automatically stops if running

---

### SINK-011: Frame Consumption

**Guarantee:** Frames consumed in FIFO order.

**Observable behavior:**
- Frames output in same order as received
- PTS values increase monotonically in output
- No frame reordering

---

### SINK-012: MasterClock Timing

**Guarantee:** Output timing follows MasterClock.

**Observable behavior:**
- Frames output when `frame.pts ≤ current_time`
- Frames with future PTS are held
- Late frames are dropped (see SINK-020)

---

### SINK-013: H.264 Encoding

**Guarantee:** Output is valid H.264 encoded video.

**Observable behavior:**
- Encoded output is valid H.264 bitstream
- SPS/PPS generated for IDR frames
- Bitrate within 10% of configured value
- GOP structure follows configuration

---

### SINK-014: MPEG-TS Muxing

**Guarantee:** Output is valid MPEG-TS stream.

**Observable behavior:**
- All packets are 188 bytes with 0x47 sync
- PTS/DTS monotonically increasing
- PCR packets at 20-100ms intervals (ISO/IEC 13818-1)
- DTS ≤ PTS for all packets

---

### SINK-015: Network Streaming

**Guarantee:** Stream delivered over TCP.

**Observable behavior:**
- TCP server accepts connections
- Stream delivered to connected client
- Non-blocking writes (no blocking on backpressure)
- Graceful disconnect handling

---

### SINK-020: Empty Buffer Handling

**Guarantee:** Empty buffer handled gracefully.

**Observable behavior:**
- `buffer_empty_count` increments
- Sink backs off (does not spin)
- Resumes when frames available
- No crash or hang

---

### SINK-021: Late Frame Handling

**Guarantee:** Late frames are dropped.

**Observable behavior:**
- Frames beyond threshold are dropped
- `late_frames` and `frames_dropped` increment
- Sink continues to next frame
- Real-time pacing maintained

---

### SINK-022: Backpressure Handling

**Guarantee:** Network backpressure handled gracefully.

**Observable behavior:**
- Packets queued when socket busy
- Queue bounded (older packets dropped on overflow)
- Sink continues running during backpressure
- No deadlock or crash

---

### SINK-023: Client Disconnect Handling

**Guarantee:** Client disconnect handled gracefully.

**Observable behavior:**
- Disconnect detected
- Resources cleaned up
- Sink continues waiting for new connection
- Reconnection works normally

---

### SINK-030: Error Recovery

**Guarantee:** Recoverable errors do not stop sink.

**Error classification:**
- **Recoverable:** Late frames, temporary starvation, transient errors
- **Degraded:** Sustained starvation, repeated late frames
- **Fault:** Corrupted memory, critical failure

**Observable behavior:**
- Recoverable errors logged, counters updated, operation continues
- Degraded mode: output valid but with degraded quality
- Fault: sink stops or enters safe mode

---

### SINK-031: Fault Latching

**Guarantee:** Faults are latched until explicit reset.

**Observable behavior:**
- Fault state persists until reset
- No auto-recovery from faults
- Fault report available (type, last values, error events)

---

## Telemetry

| Metric | Type | Description |
|--------|------|-------------|
| `sink_frames_sent_total{channel}` | Counter | Frames successfully sent |
| `sink_frames_dropped_total{channel}` | Counter | Frames dropped |
| `sink_late_frames_total{channel}` | Counter | Late frame events |
| `sink_encoding_errors_total{channel}` | Counter | Encoding failures |
| `sink_network_errors_total{channel}` | Counter | Network errors |
| `sink_buffer_empty_total{channel}` | Counter | Buffer empty events |
| `sink_running{channel}` | Gauge | 1 if running, 0 if stopped |
| `sink_status{channel}` | Gauge | 0=stopped, 1=running, 2=degraded, 3=faulted |

---

## Performance Targets

### Throughput

| Metric | Target |
|--------|--------|
| Frame rate (1080p30) | ≥ 30 fps sustained |
| Network output rate | ≥ target_fps × 0.95 |

### Latency

| Metric | Target |
|--------|--------|
| Encoding latency (p95, 1080p30) | ≤ 33ms |

### Resources

| Metric | Target |
|--------|--------|
| Memory per channel | ≤ 200 MB |
| CPU per channel (1080p30) | ≤ 40% single core |

---

## Output Format Guarantees

### MPEG-TS Compliance

- Packet size: 188 bytes
- Sync byte: 0x47 at every 188-byte boundary
- PCR interval: 20-100ms (ISO/IEC 13818-1)
- PTS monotonicity: strictly increasing
- DTS ≤ PTS: always

### H.264 Compliance

- Valid NAL unit structure
- SPS/PPS present for IDR frames
- Decodable by standard decoders

### Stream Playability

- Readable by FFprobe/FFmpeg
- Playable by VLC Media Player
- Valid codec parameters

---

## Behavioral Rules Summary

| Rule | Guarantee |
|------|-----------|
| SINK-010 | Clean lifecycle management |
| SINK-011 | FIFO frame consumption |
| SINK-012 | MasterClock timing |
| SINK-013 | Valid H.264 encoding |
| SINK-014 | Valid MPEG-TS muxing |
| SINK-015 | TCP streaming |
| SINK-020 | Empty buffer handling |
| SINK-021 | Late frame handling |
| SINK-022 | Backpressure handling |
| SINK-023 | Disconnect handling |
| SINK-030 | Error recovery |
| SINK-031 | Fault latching |

---

## Test Coverage

| Rule | Test |
|------|------|
| SINK-010 | `test_sink_lifecycle` |
| SINK-011 | `test_sink_frame_order` |
| SINK-012 | `test_sink_timing` |
| SINK-013, SINK-014 | `test_sink_encoding` |
| SINK-015 | `test_sink_streaming` |
| SINK-020, SINK-021 | `test_sink_buffer_handling` |
| SINK-022, SINK-023 | `test_sink_network_handling` |
| SINK-030, SINK-031 | `test_sink_error_handling` |

---

## See Also

- [Timing Contract](MpegTSPlayoutSinkTimingContract.md) — timing details
- [Playout Engine Contract](PlayoutEngineContract.md) — control plane
- [Phase Model](../../contracts/PHASE_MODEL.md) — phase taxonomy
- [Phase 6A Overview](Phase6A-Overview.md) — deferral of MPEG-TS
- [File Producer Contract](FileProducerDomainContract.md) — frame production
- [Contract Hygiene Checklist](../../standards/contract-hygiene.md) — authoring guidelines
