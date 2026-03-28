# Device Channel Surfing — Behavioral Contract

Status: Contract (Draft — Future Enhancement)
Authority Level: Runtime
Derived From: `LAW-CLOCK`, `LAW-LIVENESS`, `LAW-SWITCHING`
Design Reference: `docs/architecture/future_enhancements/DeviceChannelSurfing.md`

---

## Definitions

**DeviceSession:** A persistent runtime object representing a single TV device's connection to the system. Identified by `device_id`. Tracks current channel, last channel, and the set of channels in WARM state for this device.

**HOT:** A channel state indicating the channel is actively being viewed by a device. An AIR session is running and delivering content to the device's stream consumer.

**WARM:** A channel state indicating the channel has an active AIR session producing time-aligned content, but the output is not being delivered to the device. The channel is ready for instant attach. WARM channels operate at one of the defined WARM execution tiers.

**WARM Execution Tier:** The resource level at which a WARM channel operates. Three tiers are defined:

- **WARM-STREAMING** — Full encode pipeline (decode + encode + mux). MPEG-TS packets are being produced continuously. On attach, the next IDR frame is immediately deliverable. This is the ONLY tier eligible for the sub-300ms attach latency guarantee (INV-DEVICE-ATTACH-LATENCY-001). Highest resource cost.
- **WARM-ENCODING** — Reduced-quality encode pipeline (lower bitrate, fewer B-frames, or reduced resolution). Encoder is alive and producing frames, but at a quality level below the channel's target output. On attach, the existing low-quality stream is delivered immediately while the encoder promotes to full quality (see Promotion Rules). Not eligible for the 300ms guarantee — typical attach: 100-500ms depending on GOP alignment.
- **WARM-PRIMED** — Decode-only pipeline (frames decoded and timed, but not encoded). Decoder is primed and frame-current with MasterClock. On attach, the encoder must spin up, produce a GOP, stabilize the mux, and emit the first IDR. This can easily exceed 300ms. NOT eligible for the attach latency guarantee. Typical attach: 500ms-2s. This tier is a last resort — significantly better than COLD (3-10s) but not suitable for instant-feel switching.

The execution tier is configurable per deployment. The default is WARM-STREAMING. All tiers MUST maintain MasterClock alignment. The tier determines the tradeoff between attach latency and resource consumption.

**Tier Selection Guidance:**

| Hardware | Recommended Tier | Rationale |
|----------|-----------------|-----------|
| Server-class (Xeon, dedicated GPU) | WARM-STREAMING | CPU/GPU headroom supports multiple full pipelines. |
| Desktop-class (i5/i7, integrated GPU) | WARM-ENCODING | Full encode for 2-3 extra channels is feasible at reduced quality. |
| Embedded (Raspberry Pi 4) | WARM-PRIMED | Hardware encode capacity is limited to 1-2 streams. Decode-only is the only viable prewarm. |

**COLD:** A channel state indicating no AIR session is allocated for this device. Switching to a COLD channel requires a full cold start.

**Prewarm Window:** The set of channels maintained in WARM state for a device session. Determined by the prewarming strategy (initially: adjacent channels N-1, N+1, and last_channel).

**Tune Operation:** A command from a device that changes the active channel. Variants: tune-by-slug, channel-up, channel-down, numeric entry, last-channel recall.

---

## Invariants

### INV-DEVICE-SINGLE-ACTIVE-001

A DeviceSession MUST be associated with exactly one active (HOT) channel at any time after the first tune operation. Before the first tune, the device has no active channel.

### INV-DEVICE-HOT-PRODUCER-001

A channel in HOT state for any device MUST have an active Producer (AIR session running, frames being generated). If the Producer fails, the channel MUST transition to COLD and the system MUST attempt recovery or report failure to the device.

### INV-DEVICE-WARM-ALIGNMENT-001

A channel in WARM state MUST be time-aligned with MasterClock. If a device switches to a WARM channel, the first delivered frame MUST correspond to the correct schedule position at the moment of the switch — not to a stale or buffered position.

### INV-DEVICE-SWITCH-CLOCK-PRESERVATION-001

Channel switching MUST preserve correct playback offset relative to MasterClock. After a tune operation, the new channel MUST begin delivering content at the MasterClock-correct position for that channel's schedule. The switch MUST NOT cause the new channel to start from the beginning of the current block or from a cached position.

### INV-DEVICE-WARM-NO-DRIFT-001

Prewarmed channels MUST NOT drift from schedule alignment while in WARM state. A WARM channel that has been running for T seconds MUST be at the same schedule position as a channel that was started fresh T seconds ago. Frame-level drift within the tolerance defined by `LAW-CLOCK` is acceptable.

### INV-DEVICE-WARM-LIMIT-001

The total number of WARM channels across all device sessions MUST NOT exceed the configured `max_global_warm` limit. When the limit is reached and a new WARM channel is requested, the least-recently-relevant existing WARM channel MUST be demoted to COLD.

### INV-DEVICE-WARM-PER-DEVICE-LIMIT-001

The number of WARM channels for a single device session MUST NOT exceed the configured `max_warm_per_device` limit.

### INV-DEVICE-ATTACH-LATENCY-001

When switching to a WARM-STREAMING channel, the system MUST deliver the first decodable video frame (IDR/keyframe) to the device's transport within the configured attach latency target (default: 300ms). Measurement: from the moment the tune command is received by the DeviceSessionManager to the moment the first MPEG-TS packet containing a decodable IDR frame is written to the device's transport socket. "First byte" or "first TS packet" is insufficient — the frame must be decodable by the client without waiting for a subsequent keyframe.

Only channels in WARM-STREAMING state are eligible for this guarantee. WARM-ENCODING and WARM-PRIMED channels have higher attach latency and are NOT bound by this invariant (see tier definitions).

If the attach latency target is exceeded for a WARM-STREAMING channel, the event MUST be logged as a latency violation with the measured duration. The target is configurable per deployment via `warm_attach_latency_target_ms`.

### INV-DEVICE-QUALITY-PROMOTION-001

When a device attaches to a WARM-ENCODING channel, the encoder MUST promote from reduced quality to the channel's target output profile within the configured `quality_promotion_timeout_ms` (default: 3000ms). The promotion MUST be seamless — no visible glitch, frame skip, or audio discontinuity at the transition point. If promotion fails, the channel MUST continue delivering at reduced quality rather than interrupting playback.

### INV-DEVICE-REATTACH-CONSISTENCY-001

Reattaching to a previously viewed channel MUST resume at the MasterClock-correct position with no temporal discontinuity beyond normal clock progression. If a device tunes from channel A to B and back to A within any timeframe, the content on A MUST reflect the elapsed wall-clock time — not the position A was at when the device left, and not the beginning of the current block. This applies regardless of whether A was WARM (continuous pipeline) or COLD (restarted pipeline). The schedule position is determined by MasterClock, not by device viewing history.

### INV-DEVICE-FUNCTIONAL-WITHOUT-PREWARM-001

The system MUST remain fully functional without prewarming. If WARM channels are unavailable (limits exceeded, resource pressure, configuration disabled), the device MUST fall back to COLD start behavior. Correctness MUST NOT depend on prewarming — only perceived latency is affected.

---

## Device Tuning Rules

### tune(device_id, channel_id)

A tune operation MUST:

1. Validate that `device_id` corresponds to an active DeviceSession.
2. Validate that `channel_id` corresponds to a known, programmed channel.
3. Update `current_channel` to `channel_id`.
4. Set `last_channel` to the previous `current_channel` (if any).
5. Transition the previous channel from HOT to WARM (if within limits and prewarm-on-depart is configured) or COLD (if limits exceeded or not configured).
6. Transition the target channel to HOT:
   - If target was WARM: attach to existing Producer. Latency target: sub-300ms.
   - If target was COLD: initiate cold start. Deliver content as soon as first keyframe is available.
7. Update the prewarm window: compute new WARM candidates based on the new current channel and the prewarming strategy. Demote channels no longer in the window.

A tune operation MUST NOT:

- Leave the device with zero active channels (unless the tune explicitly powers off).
- Alter the schedule, episode progression, or block identity on any channel.
- Cause other devices' HOT channels to be affected.

### channel_up(device_id) / channel_down(device_id)

Equivalent to `tune(device_id, next_channel)` / `tune(device_id, prev_channel)` where next/prev is determined by the channel list ordering.

### last_channel(device_id)

Equivalent to `tune(device_id, session.last_channel)`. If `last_channel` is None (no previous tune), the operation is a no-op.

### UX Overlay Timing Rule

Optional UX effects (static burst, channel number overlay, audio click) MUST NOT delay the actual stream attach. These effects MUST be rendered as overlays on the device side, concurrent with the stream attach — not as blocking steps that precede content delivery.

Specifically:

- The stream attach (IDR frame delivery) MUST begin immediately on tune, independent of any UX overlay timing.
- A static burst of N ms MUST NOT add N ms to the attach latency. The burst is a visual effect layered on top of or interleaved with the incoming stream — it does not gate the stream.
- The attach latency measurement (INV-DEVICE-ATTACH-LATENCY-001) measures stream delivery, not perceived visual transition. UX effects are outside the measurement boundary.
- If UX effects are implemented as server-side injected frames (e.g., static frames inserted into the MPEG-TS stream), those frames MUST be counted as delivered content, not as attach delay. The IDR frame of actual channel content must follow within the latency target measured from tune command receipt.

---

## Prewarming Rules

### Prewarm Window Computation

When a device is tuned to channel N with last_channel L, the prewarm window is:

- `{N-1, N+1, L}` (adjacent channels + last channel), subject to `max_warm_per_device`.

Priority when the window exceeds `max_warm_per_device`: last_channel takes precedence over adjacency. If only 2 WARM slots are available, prefer `{L, N+1}` over `{N-1, N+1}` (last-channel recall is the most common surfing pattern after sequential).

Channels in the prewarm window that are not already WARM or HOT MUST be transitioned to WARM (subject to global limits).

Channels previously in the prewarm window but no longer relevant (e.g., after a channel switch changed the window) MUST be scheduled for TTL expiration. They are not immediately demoted — the TTL allows for rapid back-and-forth surfing without thrashing.

### WARM TTL Expiration

A WARM channel that is not in any active device's prewarm window MUST be demoted to COLD after `warm_ttl_seconds` have elapsed since it was last relevant. "Last relevant" is the later of:

- The time the channel left the prewarm window.
- The last time the channel was in HOT state for any device.

### Shared WARM State

If multiple devices have overlapping prewarm windows (e.g., device A on channel 5, device B on channel 7 — both want channel 6 WARM), the WARM channel is shared. It counts as one channel against the global limit. Demotion occurs only when no device's prewarm window includes it.

---

## Promotion Rules

When a device attaches to a channel that is not at WARM-STREAMING tier, the system MUST promote the channel's pipeline to full output quality. Promotion behavior depends on the source tier:

### WARM-ENCODING → FULL (Quality Promotion)

On attach, the WARM-ENCODING stream is delivered immediately at reduced quality. The encoder MUST begin promoting to the channel's target output profile (full bitrate, full resolution, standard GOP structure). Promotion MUST complete within the configured `quality_promotion_timeout_ms` (default: 3000ms / 3 seconds).

During promotion:

- The viewer sees content at reduced quality. This is acceptable — content is correct and time-aligned.
- The transition from reduced to full quality MUST NOT produce a visible glitch, frame skip, or audio discontinuity. The promotion MUST be seamless — a gradual bitrate ramp or a clean keyframe boundary switch.
- If promotion fails (encoder error, resource exhaustion), the channel MUST continue delivering at reduced quality rather than interrupting playback. The failure MUST be logged.

### WARM-PRIMED → FULL (Encode Spin-Up)

On attach, the encoder starts from the current decoded frame position. The system MUST produce the first IDR frame as quickly as possible. Until the first IDR is emitted, the device receives no video (black or static, depending on configuration).

- The spin-up period is NOT bound by the 300ms attach latency target. Typical: 500ms-2s.
- Once the first IDR is emitted, the stream is immediately at full quality (no promotion phase needed — the encoder started at full quality).

### HOT (No Promotion Needed)

A channel already in HOT state (e.g., re-tuning to the same channel) requires no promotion. The existing full-quality stream continues.

---

## Failure Handling

### WARM Channel Unavailable

If a device tunes to a channel that was expected to be WARM but is not (Producer crashed, resource reclaimed, TTL expired between prewarm computation and tune):

- The system MUST fall back to COLD start behavior for that channel.
- The system MUST NOT block, retry indefinitely, or return an error to the device.
- The system MUST log the miss for observability.

### Producer Failure on HOT Channel

If the active Producer for a device's HOT channel fails:

- The channel transitions to COLD.
- The system MUST attempt automatic recovery (restart AIR session, re-seed from current schedule position).
- During recovery, the device receives no content (black/silence or static, depending on configuration).
- If recovery fails after the configured retry limit, the system MUST report the failure to the device.

### Device Session Timeout

If a device session has no activity (tune, keepalive) for the configured idle timeout:

- All WARM channels for the device are demoted to COLD.
- The HOT channel is demoted to WARM (with TTL) or COLD (if no other device needs it).
- The session enters Idle state.
- A subsequent command from the device reactivates the session.

---

## Observability

The system MUST expose the following for operational monitoring:

### Per-Device Metrics

- `device_current_channel` — the currently tuned channel slug.
- `device_warm_channels` — set of channel slugs in WARM state for this device.
- `device_session_state` — Created, Active, Idle, Terminated.
- `device_last_tune_at` — timestamp of the last tune operation.

### Per-Channel Metrics

- `channel_state` — HOT, WARM, or COLD (per device, and aggregate across all devices).
- `channel_warm_device_count` — number of devices for which this channel is WARM.
- `channel_warm_since` — timestamp when the channel entered WARM state.

### System Metrics

- `global_warm_count` — total WARM channels across all devices.
- `global_warm_limit` — configured maximum.
- `warm_hit_rate` — fraction of tune operations that found the target channel in WARM state.
- `warm_miss_rate` — fraction that fell back to COLD start.
- `prewarm_decisions` — log of prewarm window computations and resulting state transitions.

---

## Required Tests

The following tests MUST be implemented when this feature is built. They are listed here to lock the behavioral contract.

| Test | Invariant | Scenario |
|------|-----------|----------|
| `test_device_session_single_active_channel` | INV-DEVICE-SINGLE-ACTIVE-001 | After tune(A) then tune(B), device has exactly one HOT channel (B). A is not HOT. |
| `test_channel_switch_preserves_master_clock_offset` | INV-DEVICE-SWITCH-CLOCK-PRESERVATION-001 | Tune to channel B. Verify first delivered frame corresponds to MasterClock-correct schedule position, not block start. |
| `test_warm_streaming_attach_latency_within_target` | INV-DEVICE-ATTACH-LATENCY-001 | Switch to a WARM-STREAMING channel. Measure time from tune command to first decodable IDR frame on transport. Assert <= configured target (300ms default). |
| `test_warm_encoding_not_eligible_for_latency_guarantee` | INV-DEVICE-ATTACH-LATENCY-001 | Switch to a WARM-ENCODING channel. Verify the attach latency invariant is NOT asserted for this tier. Content is delivered (at reduced quality) but latency may exceed 300ms. |
| `test_warm_encoding_quality_promotion` | INV-DEVICE-QUALITY-PROMOTION-001 | Attach to WARM-ENCODING channel. Verify encoder promotes to full quality within 3s. Verify no visible glitch or audio discontinuity at transition. |
| `test_warm_encoding_promotion_failure_continues_reduced` | INV-DEVICE-QUALITY-PROMOTION-001 | Attach to WARM-ENCODING. Simulate promotion failure. Verify reduced-quality stream continues without interruption. |
| `test_prewarm_adjacent_and_last_channel` | (prewarming rules) | Tune to N after being on L. Verify L, N-1, N+1 are WARM candidates (subject to limits). Verify L takes priority over N-1 when limit is 2. |
| `test_warm_channel_time_alignment` | INV-DEVICE-WARM-ALIGNMENT-001 | WARM channel runs for 60 seconds. Verify its schedule position matches what a fresh start at the same moment would produce. |
| `test_warm_channel_ttl_expiration` | (prewarming rules) | Place channel in WARM. Wait beyond TTL. Verify channel transitions to COLD. |
| `test_last_channel_remains_warm` | (prewarming rules) | Tune A → B → C. Verify B (last_channel) is WARM. Tune C → D. Verify C (new last_channel) replaces B in WARM window. |
| `test_rapid_flip_reattach_consistency` | INV-DEVICE-REATTACH-CONSISTENCY-001 | Tune A → B → A rapidly. Verify A resumes at MasterClock-correct position (wall-clock elapsed since last view), not at the position A was at when device left. |
| `test_reattach_cold_channel_still_clock_correct` | INV-DEVICE-REATTACH-CONSISTENCY-001 | Tune A → B. Wait for A to go COLD. Tune B → A. Verify A starts at MasterClock-correct position, not at beginning of block. |
| `test_static_burst_does_not_delay_stream_attach` | (UX overlay timing) | Enable static burst (200ms). Tune to WARM-STREAMING channel. Verify IDR frame delivery begins within 300ms of tune command, regardless of burst duration. |
| `test_fallback_to_cold_start_when_not_prewarmed` | INV-DEVICE-FUNCTIONAL-WITHOUT-PREWARM-001 | Tune to a COLD channel. Verify content is delivered (with higher latency). No error. |
| `test_global_warm_channel_limit_enforced` | INV-DEVICE-WARM-LIMIT-001 | Exceed global WARM limit. Verify least-recently-relevant WARM channel is demoted. Total WARM count does not exceed limit. |

---

## Enforcement Evidence

TODO — tests not yet implemented. This contract is draft status pending feature implementation.
