# Phase 8.2 — Segment Control → Frame-Accurate Start & Stop (LIBAV)

_Related: [Phase Model](../../contracts/PHASE_MODEL.md) · [Phase 8 Overview](Phase8-Overview.md) · [Phase 8.1 Air Owns MPEG-TS](Phase8-1-AirOwnsMpegTs.md) · [Phase 8.1.5 FileProducer Internal Refactor](Phase8-1-5-FileProducerInternalRefactor.md) · [Phase8-3 Preview/SwitchToLive](Phase8-3-PreviewSwitchToLive.md) · [Phase 6A Overview](Phase6A-Overview.md)_

**Principle:** Connect the existing segment logic (Phases 3–6) to frame-level emission control inside FileProducer. Join-in-progress and hard stops are enforced at the decoded-frame level; no switching yet. No ffmpeg executable; libav is the engine.

Shared invariants (segment authority: start_offset_ms and hard_stop_time_ms from Python/Phase 4, enforced by Air) are in the [Overview](Phase8-Overview.md).

## Document Role

This document is a **Coordination Contract**, refining higher-level laws. It does not override laws defined in this directory (see [PlayoutInvariants-BroadcastGradeGuarantees.md](../PlayoutInvariants-BroadcastGradeGuarantees.md)).

## Purpose

Apply **segment start/stop policy to an already-decoded frame stream**. Air does not “tell ffmpeg where to seek and when to stop.” FileProducer owns decode and enforces segment boundaries during decode/emission—frame admission control, not container seek.

- **start_offset_ms** → first frame **emitted** is the first whose presentation time satisfies the segment start; frames before that are decoded but discarded.
- **hard_stop_time_ms** → wall-clock deadline; emission ceases when MasterClock reaches it; last emitted frame must satisfy the derived media-time end boundary (see below).

Python is unchanged; it still reads opaque bytes and serves HTTP. This is where Phases 3–6 pay off in the TS path.

## Contract

### Air

Air **MUST**:

1. **Decode from the beginning of the asset** (no container-level seek). Decode proceeds in decode order; segment boundaries are enforced on **emitted** frames. *Note:* Performance optimizations (keyframe seek + decode-to-exact-frame) are deferred; Phase 8.2 requires correctness-first behavior.
2. **Discard decoded frames** until `frame.pts_ms >= start_offset_ms`.
3. **Begin emission** on the first frame whose `frame.pts_ms` satisfies the segment start.
4. **Continue emitting frames** in order (monotonic PTS).
5. **Cease emission** once `MasterClock.now_utc_ms() >= hard_stop_time_ms` (wall-clock deadline). The last emitted frame must have `frame.pts_ms < segment_end_pts_ms`, where `segment_end_pts_ms = start_offset_ms + (hard_stop_time_ms - segment_start_wallclock_ms)` (see “Derived segment end” below).
6. **Guarantee** no frame beyond the derived segment end is emitted—even partially.

**Time domains**

- **start_offset_ms:** media time in ms (asset timeline).
- **frame.pts_ms:** media time in ms.
- **hard_stop_time_ms:** wall-clock epoch ms.
- **MasterClock.now_utc_ms:** authoritative wall-clock for enforcement.

**Derived segment end**

When a segment becomes live, Air records `segment_start_wallclock_ms = MasterClock.now_utc_ms()`. Define `segment_duration_ms = hard_stop_time_ms - segment_start_wallclock_ms`. Define `segment_end_pts_ms = start_offset_ms + segment_duration_ms`. Emit frames while `frame.pts_ms < segment_end_pts_ms`. Stop producing once the next frame would violate the boundary. This makes “frame accurate” testable.

Air passes **start_offset_ms** and **hard_stop_time_ms** into **FileProducerConfig**. FileProducer enforces segment boundaries during decode/emission. No container seek, no keyframe-only seek, no CLI behavior.

- **Stops writing TS** at the hard stop; closes or drains the stream cleanly.
- **No switching yet:** one segment per channel at a time; at boundary, a new LoadPreview/Producer instance can be used, but 8.2 does not require seamless SwitchToLive in the TS (that is 8.3).

### Python

- **Unchanged:** still creates transport, passes write end to Air, serves `GET /channels/{id}.ts` as opaque bytes. Segment choice and parameters are decided by Python/Phase 4 and sent via LoadPreview (or equivalent) to Air.

## Execution

- ChannelManager (or test) decides “current segment” from plan/clock (Phase 3/4). It sends:
  - asset_path (or asset_uri)
  - start_offset_ms (e.g. 120_000 for +2 min)
  - hard_stop_time_ms (e.g. grid end in epoch ms)
- Air passes these into **FileProducerConfig**. FileProducer decodes in-process via libav and enforces segment boundaries during decode/emission. TS is written to the stream FD from the emitted frame stream; Python serves it.

## Tests

Assertions must be **frame-accurate**, not approximately correct:

- **No emitted frames after** `MasterClock.now_utc_ms() >= hard_stop_time_ms`.
- **Last emitted frame** satisfies `frame.pts_ms < segment_end_pts_ms` (derived boundary).
- **First emitted frame** satisfies `frame.pts_ms >= start_offset_ms`.
- **Monotonicity:** `frame.pts_ms` strictly increasing for emitted video frames (display order).
- **Frame count** exactly matches expected duration ± codec rounding (single frame tolerance acceptable for boundary rounding only).

Scenario coverage:

- **Tune in at +2 min** → first emitted frame at or after 2 min in asset time; no earlier frames.
- **Tune in at +17 min** → correct offset (e.g. 17 min into program segment); same strict PTS guarantees.
- **Tune in at filler** → filler segment plays (correct asset and offset).
- **Hard stop:** advance clock past hard_stop_time_ms; assert no frame (and no TS bytes) after that time; assert last emitted frame has `frame.pts_ms < segment_end_pts_ms`.
- **No drift over one block:** over a single grid block, offsets and stop time remain aligned (no accumulating error).

This is where the system separates itself from “ffmpeg-based” playout: guarantees are on **decoded-frame admission**, not on CLI seek/stop.

## Explicitly out of scope (8.2)

- No preview/live switching; no seamless SwitchToLive in the TS path (8.3).
- No fan-out or last-viewer teardown semantics (8.5)—single viewer sufficient for 8.2.
- No VLC requirement for 8.2 (manual observation OK); strict PTS/frame-count assertions in tests define correctness.

## Exit criteria

- **Join-in-progress works** (start_offset_ms enforced at frame level; first emitted frame satisfies `frame.pts_ms >= start_offset_ms`).
- **Hard stops respected** (no frame after `MasterClock.now_utc_ms() >= hard_stop_time_ms`; last emitted frame satisfies `frame.pts_ms < segment_end_pts_ms`).
- **No drift over one block** (single grid block; offsets and stop times consistent).
- **Frame-admission semantics** and derived segment end documented and tested; no reliance on ffmpeg seek or subprocess stop.
