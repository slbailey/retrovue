# Device-Centric Channel Surfing with Predictive Prewarming

Status: Wishlist
Priority: Future Enhancement
Depends On: `LAW-CLOCK`, `LAW-LIVENESS`, `LAW-SWITCHING`

---

## Overview

RetroVue currently delivers channels through a channel-centric model: each channel is an independent stream endpoint, and clients (Plex, HDHR, web) connect to a specific channel URI. This model is correct for IPTV-style consumption but does not support the defining interaction of broadcast television — channel surfing.

This enhancement introduces a device-centric delivery layer that enables channel surfing (channel up/down, numeric entry, last channel) with near-instant switching. The mechanism is predictive prewarming: channels adjacent to the currently viewed channel are kept in a time-aligned ready state so that switching requires only a stream attach, not a full cold start.

The existing channel-centric delivery model is preserved unchanged. Device delivery is an additional layer built on top of the existing Broadcast Core.

---

## Problem Statement

The current architecture has no concept of a persistent TV device. Each viewer connection is an anonymous HTTP stream to a channel endpoint. When a viewer wants to change channels, the client must:

1. Disconnect from the current stream.
2. Connect to the new channel's stream endpoint.
3. Wait for the new channel's AIR session to start (if no other viewer is on that channel).
4. Wait for the encoder to produce the first keyframe.
5. Begin playback.

Steps 3-4 introduce 3-10 seconds of latency depending on channel state. This is acceptable for IPTV guide-based selection but incompatible with the rapid, reflexive channel surfing behavior that defines the linear TV experience RetroVue simulates.

---

## Design Goals

- **Sub-300ms perceived channel switching time** when switching to a prewarmed (WARM-FULL) channel. This is an enforced invariant (INV-DEVICE-ATTACH-LATENCY-001), not just a goal. The target is configurable per deployment.
- **MasterClock-aligned playback** on every channel, whether HOT, WARM, or COLD. A viewer joining a channel at any moment sees the correct content at the correct offset.
- **Preserve existing channel-centric delivery model.** Device delivery is additive. Anonymous stream endpoints continue to work unchanged.
- **Avoid always-on execution for all channels.** Only channels that are relevant to active device sessions consume compute.
- **Support multiple independent device sessions.** Each device has its own tuning state, prewarm window, and lifecycle.

---

## Non-Goals

- No requirement for continuous single-stream multiplexing of all channels into one transport. Each channel remains an independent playout pipeline.
- No requirement to keep all channels hot at all times. Only channels within the prewarm window of active devices are warmed.
- No UI implementation details. The remote command interface is defined; the physical remote, on-screen display, and client rendering are out of scope.

---

## Proposed Architecture

### Layer 1: Broadcast Core (unchanged)

The existing Broadcast Core is unmodified:

- **MasterClock** — wall-clock time authority.
- **ScheduleService** — schedule compilation, episode progression, block resolution.
- **ChannelManager** — block feed, AIR session lifecycle, producer switching.
- **Producer / Fanout** — MPEG-TS generation, viewer multiplexing.

### Layer 2: Channel Delivery (existing)

Direct channel streaming endpoints remain unchanged:

- `GET /channel/{slug}.ts` — anonymous MPEG-TS stream.
- M3U playlist generation.
- Viewer lifecycle (join/leave/fanout).

### Layer 3: Device Delivery (new)

A new orchestration layer manages persistent device sessions:

- **DeviceSession** — persistent state for a single TV device (current channel, last channel, session lifecycle).
- **DeviceSessionManager** — manages all active device sessions, enforces global resource limits, coordinates prewarming.
- **RemoteCommand** — interface for tune operations (channel up, channel down, numeric entry, last channel, power on/off).

Layer 3 consumes Layer 1 (ChannelManager) and Layer 2 (stream endpoints) but does not modify them. It adds orchestration above the existing delivery model.

---

## Device Session Model

### DeviceSession

| Field | Type | Description |
|-------|------|-------------|
| `device_id` | str | Unique identifier for the physical or virtual device. |
| `current_channel` | str | Channel slug currently tuned. |
| `last_channel` | str or None | Previously tuned channel (for "last channel" recall). |
| `warm_channels` | set[str] | Channels currently in WARM state for this device. |
| `created_at` | datetime | Session creation time. |
| `last_activity_at` | datetime | Last tune or keepalive event. |

### Session Lifecycle

1. **Created** — device connects and identifies itself. No channel tuned yet.
2. **Active** — device is tuned to a channel. Prewarm window is maintained.
3. **Idle** — device has not sent a command within the idle timeout. WARM channels are released. HOT channel may be demoted.
4. **Terminated** — device disconnects or session expires. All channel states for this device are released.

---

## Channel State Model

Each channel, relative to a specific device session, exists in one of three states:

### HOT

The channel is actively being viewed by the device. An AIR session is running. MPEG-TS bytes are being delivered to the device's stream consumer.

- Producer is active.
- Fanout is delivering to at least this device.
- Full resource allocation.

### WARM

The channel is prewarmed — an AIR session is running and producing frames, but the output is not being delivered to any viewer on this device. The channel is ready for instant attach.

- Producer is active (may be shared with other devices or anonymous viewers).
- Output is buffered or discarded (not delivered to this device).
- Time-aligned with MasterClock — if the device switches to this channel, playback begins at the correct schedule position.

#### WARM Execution Tiers

Not all WARM channels need to run at full quality. Three execution tiers trade off attach latency against resource cost:

| Tier | Pipeline | Attach Latency | Latency Guarantee | Resource Cost | Description |
|------|----------|---------------|-------------------|---------------|-------------|
| **WARM-STREAMING** | Decode + Encode + Mux | ~50ms | Eligible for 300ms guarantee | Highest | Full MPEG-TS pipeline. IDR frame ready to deliver on attach. |
| **WARM-ENCODING** | Decode + Reduced Encode | ~100-500ms | NOT eligible | Medium | Lower bitrate / resolution. Delivers immediately at reduced quality, promotes to full within 3s. |
| **WARM-PRIMED** | Decode + Timing only | ~500ms-2s | NOT eligible | Lowest | No encode running. Encoder must spin up on attach. Decoder primed and frame-current. Last resort — still much better than COLD (3-10s). |

The default tier is WARM-STREAMING. Deployments with constrained hardware (e.g., Raspberry Pi) may configure WARM-ENCODING or WARM-PRIMED to reduce CPU usage at the cost of higher attach latency. All tiers maintain MasterClock alignment.

Only WARM-STREAMING is eligible for the sub-300ms attach latency guarantee (INV-DEVICE-ATTACH-LATENCY-001). WARM-ENCODING provides immediate-but-low-quality content with seamless promotion. WARM-PRIMED provides a significant improvement over COLD start but cannot guarantee fast switching.

#### Promotion on Attach

When a device attaches to a WARM-ENCODING channel, the reduced-quality stream is delivered immediately. The encoder then promotes to full quality within 3 seconds. The transition must be seamless — no visible glitch, frame skip, or audio discontinuity. If promotion fails, reduced quality continues (no interruption).

### COLD

The channel is not running for this device. Switching to a COLD channel requires a full cold start (AIR session creation, decoder priming, first keyframe).

- No producer allocated for this device.
- Switching latency: 3-10 seconds (current behavior).

---

## Predictive Prewarming

### Initial Strategy

When a device is tuned to channel N with last_channel L:

| Channel | State | Rationale |
|---------|-------|-----------|
| N | HOT | Currently viewed. |
| L (last channel) | WARM | Most common recall pattern — people bounce between two channels. |
| N+1 | WARM | Sequential channel-up. |
| N-1 | WARM (if within limits) | Sequential channel-down. |
| All others | COLD | |

Last-channel takes priority over adjacency when `max_warm_per_device` is constrained. With a limit of 2 WARM channels, the window is `{L, N+1}` — last-channel recall is more frequent than channel-down in real viewing behavior.

### Future Expansion

- **Recently viewed channels** — channels visited in the last M minutes are kept WARM.
- **Favorites** — operator-defined or device-learned favorite channels are prewarmed.
- **Behavioral prediction** — ML-based prediction of likely next channel based on viewing history, time of day, and content type.
- **Guide-aware prewarming** — when the device is browsing the EPG guide, channels highlighted by the cursor are prewarmed.

---

## Transition Behavior

### Channel Switch (tune operation)

When a device tunes from channel A to channel B:

1. **Detach from A** — stop delivering A's stream to this device. A transitions from HOT to WARM (if within another device's prewarm window or if prewarm-on-depart is configured) or COLD (if no other device needs it).
2. **Attach to B** — if B is WARM, immediately begin delivering B's stream to the device. B transitions from WARM to HOT. If B is COLD, initiate cold start; deliver content as soon as the first keyframe is available.
3. **Update prewarm window** — B-1 and B+1 become WARM candidates. A-1 and A+1 are released if no longer relevant.

### Optional UX Effects

To simulate the physical television experience, the device delivery layer may inject:

- **Static burst** — a brief (100-300ms) burst of static/snow during channel switch, simulating analog tuner behavior.
- **Channel number overlay** — on-screen display of the new channel number, fading after 2-3 seconds.
- **Audio click** — a brief audio artifact simulating relay switching.

These effects are optional, configurable per device, and implemented at the delivery layer — not in the Broadcast Core.

---

## Resource Constraints

### Per-Device Limits

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_warm_per_device` | 2 | Maximum WARM channels per device session. |
| `warm_ttl_seconds` | 120 | Time before an unused WARM channel is demoted to COLD. |

### Global Limits

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_global_warm` | 6 | Maximum total WARM channels across all devices. |
| `max_concurrent_devices` | 4 | Maximum simultaneous device sessions. |

When limits are exceeded, the least-recently-relevant WARM channel is demoted to COLD. Priority: channels in the current device's prewarm window take precedence over channels in other devices' windows.

---

## Risks and Tradeoffs

- **Increased CPU and memory usage.** Each WARM channel runs a full AIR session (decoder, encoder, muxer). With 2 WARM channels per device and 4 devices, up to 8 additional AIR sessions may be running. On the target hardware (Raspberry Pi 4 or equivalent), this may require hardware encoding or reduced output quality for WARM channels.
- **Orchestration complexity.** The DeviceSessionManager must coordinate channel state transitions across multiple devices, enforce global limits, handle race conditions (two devices switching to the same channel simultaneously), and manage graceful degradation.
- **Lifecycle management.** WARM channels that are no longer relevant must be released promptly. TTL expiration, idle detection, and limit enforcement must be correct to prevent resource leaks.
- **Cold start fallback.** The system must remain fully functional without prewarming. If WARM channels are unavailable (limits exceeded, resource pressure, startup), the device falls back to cold start behavior with no loss of correctness — only increased latency.

---

## Future Extensions

- **Advanced prediction models** — use viewing history, time-of-day patterns, and content metadata to predict likely channel switches beyond simple adjacency.
- **Guide integration** — when a device browses the EPG, prewarm channels as the cursor moves. This turns the guide into a prediction signal.
- **Multi-device synchronization** — shared household viewing where multiple devices can share WARM channel state (e.g., living room TV and kitchen TV both benefit from the same prewarmed channels).
- **Persistent device profiles** — device preferences, channel ordering, favorites, and viewing history survive across sessions and inform prewarming strategy.
- **Quality tiering** — WARM channels may run at reduced quality (lower bitrate, fewer B-frames) to reduce resource consumption, with quality promotion to full on attach.
- **Network-level prewarming** — for remote devices, prewarm at the network edge to reduce first-frame latency.
