# HLS Delivery — Domain Contract

Status: Contract
Authority Level: Runtime
Derived From: `LAW-LIVENESS`, `LAW-CLOCK`, `LAW-DECODABILITY`, `LAW-IMMUTABILITY`, `LAW-DERIVATION`, `LAW-RUNTIME-AUTHORITY`

---

## Overview

HLS delivery is the distribution layer that converts a channel's continuous playout stream into discrete, client-retrievable segments and a sliding playlist. It is the last mile between the runtime playout engine and viewers.

HLS delivery does not define the channel timeline. The channel timeline is defined by the schedule (planning authority) and materialized by the playout engine (runtime authority). HLS delivery represents that timeline in a protocol-specific format that clients can consume and correctly interpret as live television.

This contract governs how that representation is produced, stored, served, and retired. It does not govern what content airs, when it airs, or how it is encoded — those guarantees belong to the scheduling, playout, and encoding contracts respectively.

### Authority Boundary

This contract owns:
- Segment production from playout output (keyframe detection, segment boundaries, duration tracking)
- Segment metadata assignment (wall-clock timestamps, discontinuity flags, index assignment)
- Segment storage and lifecycle (bounded window, eviction, availability)
- Manifest generation (playlist construction, live signaling, timeline anchoring)
- HLS endpoint behavior (HTTP semantics, response formats, caching)
- HLS viewer presence tracking (session lifecycle, timeout, count integration)
- Coexistence with raw TS delivery (shared producer, unified viewer count)

This contract does NOT own:
- Content selection or scheduling (`episode_progression.md`, `schedule_block_program_reference.md`)
- Block construction or segment assembly (`traffic_manager.md`, `break_structure.md`)
- Real-time encoding, muxing, or frame timing (AIR playout contracts)
- BlockPlan generation or JIP calculation (playout pipeline contracts)
- Raw TS delivery semantics (`INV-RAW-TS-TRANSPORT-001`)

---

## Terminology

### Segment

A bounded, immutable byte sequence of MPEG-TS data representing a fixed slice of the channel's continuous broadcast output. A segment spans a wall-clock time range and is identified by a channel-scoped integer index.

### Segment Window

The bounded set of most-recently-completed segments retained in memory for client retrieval. The window slides forward as new segments complete and old segments are evicted.

### Manifest

An HLS media playlist (RFC 8216) that describes the current segment window. The manifest is generated on demand from the segment window's current state. It is not a stored file.

### Live Edge

The most recent completed segment in the window. Clients joining the channel begin playback near the live edge. The live edge lags the channel's true "now" by at most one segment duration plus encoding latency.

### Viewer Session

A logical record of an HLS client's presence on a channel, identified by a session token and refreshed by HTTP request activity. Sessions expire after inactivity and are reaped periodically.

### Eviction Grace

The difference between segment window capacity and manifest window size. Grace segments remain retrievable after leaving the manifest, preventing the race where a client receives a manifest listing a segment that is evicted before the client can fetch it.

---

## 1. HLS Segment Contract

Segments are the atomic unit of HLS delivery. Each segment is a self-contained, immutable representation of a slice of the channel's editorial timeline.

### INV-HLS-SEGMENT-IDENTITY-001 — Channel-scoped monotonic identity

Every completed segment receives a channel-scoped integer index. Indices MUST be strictly monotonically increasing with no gaps during a continuous producer session. No two segments within the same channel may share an index. Segment identity is `(channel_id, index)` — no viewer session, connection time, or client identity participates in segment identity. The index counter MUST persist across producer restarts within a single channel activation. Two references to the same `(channel_id, index)` MUST always denote the same segment.

### INV-HLS-SEGMENT-IMMUTABLE-001 — Completed segments are frozen

Once a segment transitions to complete, its byte payload, duration, wall-clock timestamp, index, and discontinuity flag MUST NOT be modified, appended to, or rewritten. Any read of a completed segment MUST return identical data regardless of when the read occurs or which client performs it. No client-specific transformation, watermarking, or mutation may occur at any point in the delivery path.

### INV-HLS-SEGMENT-KEYFRAME-001 — Keyframe-aligned boundaries

Every segment MUST begin with a keyframe (IDR frame). No segment may begin mid-GOP. A client that receives only a single segment MUST be able to decode it from its first frame without reference to any prior segment. Segment duration may vary from the target duration by up to one GOP interval due to keyframe alignment.

### INV-HLS-SEGMENT-SELFCONTAINED-001 — Structurally decodable

Every completed segment MUST be a valid MPEG-TS byte sequence containing PAT and PMT tables. A compliant TS demuxer MUST be able to identify the program structure from the segment alone without reference to prior segments or external metadata. Every segment MUST contain at least one complete video frame and its corresponding audio samples. Zero-byte or video-absent segments MUST NOT be produced.

### INV-HLS-SEGMENT-WALLCLOCK-001 — Editorial timeline truth

Each segment MUST carry a wall-clock start timestamp derived from the channel's BlockPlan schedule, which originates from MasterClock. The timestamp represents the editorial broadcast time of the segment's first frame. Timestamps MUST NOT be derived from the system clock at the moment of segmentation. The timestamp MUST fall within the time range of a BlockPlan block that was active during that segment's production.

### INV-HLS-SEGMENT-PTS-CONTINUITY-001 — PTS continuity between segments

Within a continuous producer session, the first PTS of segment N+1 MUST equal the last PTS of segment N plus one frame duration (within frame-time tolerance). PTS breaks between consecutive segments MUST be detected and the subsequent segment MUST be marked as discontinuous before entering the segment window. On producer restart, the PTS tracker MUST reset. PTS continuity checks MUST use integer arithmetic.

### INV-HLS-SEGMENT-DURATION-BOUNDS-001 — Duration within tolerance

Every completed segment's duration MUST fall within `[target_duration - max_gop_interval, target_duration + max_gop_interval]`. Segments outside this range indicate a boundary detection failure. Zero-duration or negative-duration segments MUST be rejected and MUST NOT enter the segment window. Duration MUST be computed from PTS values, not from byte count or wall-clock elapsed time.

### INV-HLS-SEGMENT-INDEX-GUARD-001 — Index counter integrity

The segment index counter MUST advance by exactly 1 per completed segment. An index value MUST NOT be reused, skipped, or decreased. If index drift is detected, the counter MUST be force-corrected to `max(next_index, previous_index + 1)` and the correction MUST be logged. The counter MUST NOT be decremented under any circumstance.

---

## 2. Segment Window Contract

The segment window is a bounded, ordered collection of completed segments. It represents the most recent slice of the channel's broadcast output that is available for client retrieval.

### INV-HLS-RING-BOUNDED-001 — Bounded capacity with FIFO eviction

The segment window MUST hold at most `capacity` completed segments at any time. When a new segment is added and the window is at capacity, the oldest segment (lowest index) MUST be evicted before or atomically with the addition. Eviction MUST follow strict index order — it MUST NOT skip a segment or evict out of order. Once evicted, a segment index MUST return absence on retrieval permanently within the current channel activation.

### INV-HLS-RING-OBSERVATION-001 — Consistent observation

A snapshot of the segment window taken at a single point in time MUST be internally consistent: segments are contiguous, ordered by index, and each segment's data matches its metadata. A reader MUST NOT observe a partially-written segment or a torn window. A segment MUST be available for retrieval immediately after the operation that added it completes. Before any segment is produced, the window MUST be empty and all retrievals MUST return absence.

### INV-HLS-RING-PUSH-ATOMIC-001 — Atomic insertion

The insertion of a new segment and eviction of the oldest (if required) MUST be atomic with respect to readers. No reader may observe a state where the new segment is present but the evicted segment has not yet been removed, or vice versa.

### INV-HLS-RING-WINDOW-VALID-001 — Post-insertion consistency

After every insertion, the window's internal state MUST satisfy: `newest_index - oldest_index + 1 == segment_count <= capacity`. If this check fails, the window MUST self-repair by rebuilding its index range from the actual segment keys, and MUST log the correction.

### INV-HLS-RING-EVICTION-GRACE-001 — Grace margin prevents fetch race

The segment window capacity MUST be strictly greater than the manifest window size plus one. This grace margin ensures that a segment remains retrievable for at least one manifest advancement cycle after it leaves the manifest. If the capacity is configured at or below the manifest window size plus one, the system MUST reject the configuration at startup.

### INV-HLS-NO-DISK-IO-001 — In-memory storage

Segment and playlist data MUST be stored in and served from memory. No filesystem I/O MUST occur on the segment feed, serve, or playlist generation paths. Segments are ephemeral — they represent aired content and MUST NOT persist beyond the window's retention.

---

## 3. Manifest Contract

The manifest is a live HLS media playlist that represents the current state of the segment window. It is a read-only, deterministic view — not a stored artifact.

### INV-HLS-MANIFEST-LIVE-001 — Live stream signaling

The manifest MUST NOT contain `#EXT-X-ENDLIST`. Its absence is the normative HLS signal that the stream is live. The manifest MUST contain `#EXT-X-TARGETDURATION` with a value (integer seconds, rounded up) greater than or equal to the actual duration of every segment in the window. Every manifest MUST be a valid HLS media playlist per RFC 8216.

### INV-HLS-MANIFEST-SEQUENCE-001 — Media sequence correctness

`#EXT-X-MEDIA-SEQUENCE` MUST equal the segment index of the oldest segment in the current window. Across successive manifest responses for the same channel, this value MUST NOT decrease. Segments MUST be listed in the manifest in ascending index order matching the temporal order of the channel timeline. The URI for a given segment index MUST NOT change across manifest responses.

### INV-HLS-MANIFEST-PDT-001 — Program date-time anchoring

The manifest MUST contain at least one `#EXT-X-PROGRAM-DATE-TIME` tag, appearing immediately before the first segment entry. Its value MUST be the wall-clock start timestamp of that segment, formatted as ISO 8601 with UTC timezone designator (Z suffix) and millisecond precision. The timestamp MUST originate from the segment's stored wall-clock metadata (which itself is BlockPlan-derived per `INV-HLS-SEGMENT-WALLCLOCK-001`), not from the server's system clock at manifest generation time. Each segment entry MUST be preceded by an `#EXTINF` tag whose value matches the segment's actual presentation duration.

### INV-HLS-MANIFEST-CHANNEL-SCOPED-001 — No per-client manifests

The manifest content for a channel at a given instant MUST be identical for all clients requesting it. No client-specific, session-specific, or request-specific data may appear in the manifest body. The manifest is a function of the channel's segment window state and nothing else. Every segment listed in the manifest MUST be present in the segment window at the time of generation.

### INV-HLS-MANIFEST-DETERMINISTIC-001 — Pure generation

Given the same segment window state, the manifest generator MUST produce byte-identical output regardless of which client requested it, how many times it is called, or the server's current system time. The generation process MUST NOT read any state other than the segment window snapshot. System clock functions MUST NOT be called during manifest construction.

### INV-HLS-MANIFEST-VALID-PLAYLIST-001 — Structural validity

Every generated manifest MUST contain `#EXTM3U` as its first line, exactly one `#EXT-X-TARGETDURATION` tag, exactly one `#EXT-X-MEDIA-SEQUENCE` tag, and at least one `#EXTINF` + segment URI pair when segments are available. If the manifest would be structurally invalid, the system MUST NOT serve it — it MUST return an error response instead.

### INV-HLS-MANIFEST-SEQUENCE-MONOTONIC-001 — Sequence never reverses

The `EXT-X-MEDIA-SEQUENCE` value MUST never decrease across successive generations for the same channel. If a decrease is detected, the value MUST be clamped to the maximum of the current and last-emitted values, and the correction MUST be logged.

### INV-HLS-MANIFEST-WINDOW-RING-ALIGNMENT-001 — Manifest matches window

The manifest MUST be generated from a single atomic snapshot of the segment window. The manifest MUST NOT be composed from multiple non-atomic reads. If the snapshot is empty, the system MUST NOT generate a manifest — it MUST signal unavailability instead.

### INV-HLS-MANIFEST-PDT-CLOCK-SOURCE-001 — No system clock in timeline

The `EXT-X-PROGRAM-DATE-TIME` value MUST be formatted exclusively from the segment's stored `wall_clock_start_utc_ms` field. No system clock function may be called in the code path that produces this value. The formatted timestamp MUST use ISO 8601 with UTC timezone designator and millisecond precision.

### INV-HLS-DISCONTINUITY-MARKER-001 — Discontinuity propagation

When a segment in the window carries a discontinuity flag, the manifest MUST emit `#EXT-X-DISCONTINUITY` immediately before that segment's `#EXTINF` tag. Discontinuity tags MUST be emitted if and only if the segment's discontinuity flag is true. The manifest MUST NOT infer or suppress discontinuities independently of the segment metadata.

---

## 4. HLS Delivery Contract

HLS delivery exposes two HTTP endpoints: a manifest endpoint and a segment endpoint. Together they allow HLS clients to consume the channel as live television.

### INV-HLS-ENDPOINT-COEXIST-001 — Protocol coexistence

HLS endpoints and the legacy raw TS endpoint for the same channel MUST share the same playout producer and encoder output. A second encoder MUST NOT be started for the HLS path. Viewers on both endpoints MUST count toward the same channel viewer population. Neither endpoint's behavior MUST be degraded by the other's activity.

### INV-HLS-LIFECYCLE-SEGMENT-READY-001 — Startup availability

When the channel is starting and no segments are yet available, the manifest endpoint MUST return HTTP 503 with a `Retry-After` header. The manifest endpoint MUST NOT return an empty playlist or a playlist with zero segment entries. A viewer joining an active channel with available segments MUST be able to immediately retrieve the current manifest and all segments in the window. Additional viewers joining an active channel MUST NOT affect the production pipeline.

### INV-HLS-SERVE-BYTE-IDENTITY-001 — Segment fidelity

The segment endpoint MUST serve the exact bytes stored in the segment window for the requested index. No transformation, transcoding, re-muxing, or modification may occur between storage and HTTP response. The response `Content-Length` MUST equal the stored segment's byte count. If the requested segment index does not exist in the window (evicted, not yet produced, or never produced), the endpoint MUST return HTTP 404.

### INV-HLS-ENDPOINT-SESSION-TOUCH-001 — Touch on success only

Every successful (HTTP 200) manifest or segment response MUST refresh the viewer session's last-activity timestamp. Failed responses (4xx, 5xx) MUST NOT refresh the timestamp. This prevents phantom sessions from persisting due to error-loop requests. A request with no session identifier MUST create a new session.

### INV-HLS-QUIET-POLLING-001 — Polling noise suppression

HLS client polling MUST NOT produce per-request log output at INFO level or above. Manifest and segment requests are high-frequency, low-information events. Lifecycle events (startup, stop, errors) MUST remain at INFO level or above.

Manifest endpoint responses MUST carry `Content-Type: application/vnd.apple.mpegurl` and `Cache-Control: no-cache, max-age=0`. Segment endpoint responses MUST carry `Content-Type: video/mp2t` and `Cache-Control: public` with a positive `max-age`. The legacy raw TS endpoint MUST carry `Content-Type: video/mpeg` per `INV-RAW-TS-TRANSPORT-001`.

---

## 5. Viewer Presence Contract

HLS clients have no persistent connection. Viewer presence MUST be inferred from request activity rather than TCP connection state.

### INV-HLS-VIEWER-PRESENCE-001 — Request-based detection

A viewer MUST be considered present when an HTTP request with a valid session identifier has been received within the configured timeout window. The first request from an unknown session identifier MUST create a new viewer session for that channel. Each subsequent request from a known session MUST refresh its last-activity timestamp. Sessions whose last-activity timestamp exceeds the timeout threshold MUST be reaped. A session identifier MUST be scoped to a single channel — the same identifier used for different channels constitutes independent sessions.

### INV-HLS-VIEWER-COUNT-ACCURATE-001 — Count matches state

The reported viewer count for a channel MUST equal the number of non-expired sessions at all times. Session creation and the viewer count increment MUST be atomic — no window may exist where the session is present but the count has not incremented. Session reaping and the viewer count decrement MUST be atomic. Concurrent session mutations for the same channel MUST be serialized.

### INV-HLS-SESSION-REAP-BOUNDED-001 — Bounded reap timing

The reap interval MUST be at most half the timeout threshold. Reaping MUST run on a fixed periodic schedule regardless of request activity — it MUST NOT be triggered by client requests. The reap sweep MUST examine all sessions for the channel. The reap task MUST be cancelled on channel teardown to prevent orphaned timers.

### INV-HLS-SESSION-FIRST-VIEWER-ONCE-001 — First/last viewer atomicity

The first-viewer lifecycle transition (0 to 1 viewers) MUST fire exactly once, even when multiple sessions are created concurrently. The transition check and the session insertion MUST occur within the same serialized operation. The same pattern applies to the last-viewer transition (1 to 0): only the operation that decrements to zero MUST trigger teardown. The first-viewer handler MUST be idempotent.

### INV-HLS-PHANTOM-CLEANUP-001 — Failed startup cleanup

When channel startup fails (no segment production begins), the phantom session MUST be removed. Failed (non-200) responses MUST NOT update the session activity timestamp, preventing phantom sessions from persisting indefinitely through error-loop requests.

---

## 6. Raw TS Coexistence Contract

HLS delivery and raw TS delivery are parallel representations of the same broadcast channel. Both MUST coexist without interference.

### INV-HLS-ENDPOINT-COEXIST-001 — Shared infrastructure

Both delivery paths MUST consume the output of the same playout producer. There MUST be one encoding per channel, regardless of how many delivery protocols are active. Both paths MUST share the same upstream byte source (the playout engine's output). No delivery path may starve, throttle, or interfere with the other's byte consumption.

### Unified viewer population

Viewers connected via raw TS (`viewer_join`/`viewer_leave` on TCP connection lifecycle) and viewers tracked via HLS sessions (touch/reap) MUST count toward the same channel viewer population. The first-viewer and last-viewer lifecycle transitions MUST be governed by the unified count. A channel with one raw TS viewer and one HLS viewer has a viewer count of 2. Neither viewer type is privileged.

### Independent delivery semantics

Each delivery protocol MUST maintain its own transport semantics:
- Raw TS: infinite byte stream, `Connection: close`, no `Content-Length`, per `INV-RAW-TS-TRANSPORT-001`
- HLS: discrete segments + sliding manifest, per this contract

Protocol-specific behavior (segment boundaries, manifest windows, playlist tags) MUST NOT leak into the other protocol's delivery path. A change to HLS manifest generation MUST NOT affect raw TS byte delivery. A change to raw TS chunking MUST NOT affect segment boundaries.

### Timeline equivalence

Both delivery paths MUST represent the same editorial timeline at the same wall-clock instant. A viewer watching via raw TS and a viewer watching via HLS MUST see the same content at the same moment (within transport-latency differences inherent to each protocol). The difference in observed position between the two protocols MUST be bounded by the sum of segment duration and client buffer depth.

---

## 7. Failure Contracts

Failures in the delivery layer MUST be contained. They MUST NOT produce invalid manifests, corrupt segments, or break the editorial timeline.

### INV-HLS-RESTART-DISCONTINUITY-001 — Producer restart continuity

When a playout producer restarts (after failure recovery or viewer departure and return), the first segment produced after restart MUST carry a discontinuity flag. The PTS tracker MUST reset to "no prior segment" state. Segment indices MUST continue from the channel's counter, not reset to zero. If the channel activation persists across restart, the counter MUST survive. If the channel activation was destroyed, the indices start fresh and the manifest MUST carry an incremented `EXT-X-DISCONTINUITY-SEQUENCE`.

### INV-HLS-PRODUCER-SEGMENT-FLOW-001 — Stall detection

While a producer is active and the upstream byte source is delivering data, segments MUST be produced at approximately real-time rate. If no segment has been completed within twice the target segment duration while bytes are flowing, the system MUST log a warning. If the stall persists for four times the target segment duration, the system MUST attempt segmenter recovery without restarting the producer. If the producer itself has failed (upstream byte source reports EOF), this invariant does not apply — producer recovery is governed by `INV-CHANNEL-LIVENESS-RECOVERY-001`.

### INV-HLS-NO-ORPHAN-PRODUCER-001 — No abandoned producers

A producer MUST NOT remain running after the linger period expires with zero viewers. If a producer is found running with zero viewers and no active linger timer, the system MUST initiate immediate teardown and log the violation. The linger timer MUST be cancelled if a viewer arrives during the linger period.

### INV-HLS-MANIFEST-VALID-PLAYLIST-001 — No malformed manifests

If the manifest generation process produces a structurally invalid playlist (missing required tags, TARGETDURATION less than any EXTINF value), the system MUST NOT serve it. An error response MUST be returned instead. Invalid manifests MUST NOT reach clients under any failure condition.

### INV-HLS-LIFECYCLE-SEGMENT-READY-001 — Graceful startup

During the bounded startup period after producer start (before the first segment completes), the manifest endpoint MUST return HTTP 503 with `Retry-After`, not an empty or malformed playlist. Clients MUST receive a clear signal to wait and retry. The transition from 503 to 200 MUST occur only when at least one completed segment is available.

---

## 8. Timeline Authority Contract

HLS delivery represents the channel's editorial timeline but MUST NOT define or modify it. All timeline truth flows from MasterClock through the scheduling and playout layers into delivery metadata.

### INV-HLS-SEGMENT-WALLCLOCK-001 — MasterClock-derived timestamps

Every segment's wall-clock timestamp MUST be derived from the BlockPlan schedule, which itself is derived from MasterClock. The timestamp MUST NOT be derived from the server's system clock at the moment of segmentation. The timestamp represents the editorial broadcast time of the segment's first frame — the time at which the schedule declared this content would air.

### INV-HLS-SEGMENT-WALLCLOCK-AUDIT-001 — Timeline audit

At segment completion, the system MUST verify that the segment's wall-clock timestamp falls within the active BlockPlan block's `[start_utc_ms, end_utc_ms)` range. If the check fails, the system MUST log a warning. The segment MUST NOT be dropped on audit failure — it represents real playout output and remains valid for delivery. The warning enables operator diagnosis of timeline drift.

### INV-HLS-MANIFEST-PDT-CLOCK-SOURCE-001 — System clock prohibition

The `EXT-X-PROGRAM-DATE-TIME` value in the manifest MUST be formatted from the segment's stored wall-clock timestamp and no other source. The manifest generation process MUST NOT call any system clock function in the code path that produces this value. The delivery layer MUST NOT invent, adjust, or reinterpret timeline values.

### Timeline derivation chain

Wall-clock truth flows through a single derivation chain:

    MasterClock → schedule compilation → BlockPlan start_utc_ms
    → segment wall_clock_start_utc_ms → manifest EXT-X-PROGRAM-DATE-TIME

Each layer in this chain specializes or formats the upstream value. No layer may contradict, recompute, or independently derive the timestamp. The delivery layer is the terminal consumer — it formats and publishes, it does not author.

---

## Invariant Summary

### Segment Production
| ID | Title |
|----|-------|
| INV-HLS-SEGMENT-IDENTITY-001 | Channel-scoped monotonic identity |
| INV-HLS-SEGMENT-IMMUTABLE-001 | Completed segments are frozen |
| INV-HLS-SEGMENT-KEYFRAME-001 | Keyframe-aligned boundaries |
| INV-HLS-SEGMENT-SELFCONTAINED-001 | Structurally decodable |
| INV-HLS-SEGMENT-WALLCLOCK-001 | Editorial timeline truth |
| INV-HLS-SEGMENT-PTS-CONTINUITY-001 | PTS continuity between segments |
| INV-HLS-SEGMENT-DURATION-BOUNDS-001 | Duration within tolerance |
| INV-HLS-SEGMENT-INDEX-GUARD-001 | Index counter integrity |

### Segment Window
| ID | Title |
|----|-------|
| INV-HLS-RING-BOUNDED-001 | Bounded capacity with FIFO eviction |
| INV-HLS-RING-OBSERVATION-001 | Consistent observation |
| INV-HLS-RING-PUSH-ATOMIC-001 | Atomic insertion |
| INV-HLS-RING-WINDOW-VALID-001 | Post-insertion consistency |
| INV-HLS-RING-EVICTION-GRACE-001 | Grace margin prevents fetch race |
| INV-HLS-NO-DISK-IO-001 | In-memory storage |

### Manifest
| ID | Title |
|----|-------|
| INV-HLS-MANIFEST-LIVE-001 | Live stream signaling |
| INV-HLS-MANIFEST-SEQUENCE-001 | Media sequence correctness |
| INV-HLS-MANIFEST-PDT-001 | Program date-time anchoring |
| INV-HLS-MANIFEST-CHANNEL-SCOPED-001 | No per-client manifests |
| INV-HLS-MANIFEST-DETERMINISTIC-001 | Pure generation |
| INV-HLS-MANIFEST-VALID-PLAYLIST-001 | Structural validity |
| INV-HLS-MANIFEST-SEQUENCE-MONOTONIC-001 | Sequence never reverses |
| INV-HLS-MANIFEST-WINDOW-RING-ALIGNMENT-001 | Manifest matches window |
| INV-HLS-MANIFEST-PDT-CLOCK-SOURCE-001 | No system clock in timeline |
| INV-HLS-DISCONTINUITY-MARKER-001 | Discontinuity propagation |

### Delivery Endpoints
| ID | Title |
|----|-------|
| INV-HLS-ENDPOINT-COEXIST-001 | Protocol coexistence |
| INV-HLS-LIFECYCLE-SEGMENT-READY-001 | Startup availability |
| INV-HLS-SERVE-BYTE-IDENTITY-001 | Segment fidelity |
| INV-HLS-ENDPOINT-SESSION-TOUCH-001 | Touch on success only |
| INV-HLS-QUIET-POLLING-001 | Polling noise suppression |

### Viewer Presence
| ID | Title |
|----|-------|
| INV-HLS-VIEWER-PRESENCE-001 | Request-based detection |
| INV-HLS-VIEWER-COUNT-ACCURATE-001 | Count matches state |
| INV-HLS-SESSION-REAP-BOUNDED-001 | Bounded reap timing |
| INV-HLS-SESSION-FIRST-VIEWER-ONCE-001 | First/last viewer atomicity |
| INV-HLS-PHANTOM-CLEANUP-001 | Failed startup cleanup |

### Failure Handling
| ID | Title |
|----|-------|
| INV-HLS-RESTART-DISCONTINUITY-001 | Producer restart continuity |
| INV-HLS-PRODUCER-SEGMENT-FLOW-001 | Stall detection |
| INV-HLS-NO-ORPHAN-PRODUCER-001 | No abandoned producers |

### Timeline Authority
| ID | Title |
|----|-------|
| INV-HLS-SEGMENT-WALLCLOCK-AUDIT-001 | Timeline audit |

---

## Required Tests

- `server/tests/contracts/runtime/test_inv_hls_segment_production.py`
- `server/tests/contracts/runtime/test_inv_hls_segment_timeline.py`
- `server/tests/contracts/runtime/test_inv_hls_segment_ring.py`
- `server/tests/contracts/runtime/test_inv_hls_ring_integrity.py`
- `server/tests/contracts/runtime/test_inv_hls_manifest.py`
- `server/tests/contracts/runtime/test_inv_hls_manifest_consistency.py`
- `server/tests/contracts/runtime/test_inv_hls_viewer_presence.py`
- `server/tests/contracts/runtime/test_inv_hls_viewer_count.py`
- `server/tests/contracts/runtime/test_inv_hls_lifecycle.py`
- `server/tests/contracts/runtime/test_inv_hls_channel_runtime.py`
- `server/tests/contracts/runtime/test_inv_hls_endpoint_coexist.py`
- `server/tests/contracts/runtime/test_inv_hls_delivery_path.py`
- `server/tests/contracts/runtime/test_inv_hls_no_disk_io.py`
- `server/tests/contracts/runtime/test_inv_hls_discontinuity_marker.py`
- `server/tests/contracts/runtime/test_inv_hls_phantom_cleanup.py`
- `tests/contracts/hls_delivery/test_segment_production.py`
- `tests/contracts/hls_delivery/test_segment_ring.py`
- `tests/contracts/hls_delivery/test_manifest.py`
- `tests/contracts/hls_delivery/test_viewer_presence.py`
- `tests/contracts/hls_delivery/test_channel_lifecycle.py`
- `tests/contracts/hls_delivery/test_delivery_endpoints.py`
