# ⚠️ RETIRED — Superseded by BlockPlan Architecture

**See:** [Phase8DecommissionContract.md](../../../../docs/contracts/architecture/Phase8DecommissionContract.md)

This document describes legacy playlist/Phase8 execution and is no longer active.

---

# Phase 8.1 — Air Owns MPEG-TS (single segment, no switching)

_Related: [Phase Model](../PHASE_MODEL.md) · [Phase 8 Overview](Phase8-Overview.md) · [Phase8-0 Transport](Phase8-0-Transport.md) · [Phase8-2 Segment Control](Phase8-2-SegmentControl.md)_

**Principle:** Prove that ffmpeg → Air → socket → Python → HTTP works for **one file**, no switching, no timeline. This is the first time VLC appears.

**Invariant (Phase 8):** AttachStream is **transport-only**. It MUST NOT carry asset_path, offsets, plan handles, or any content selection fields. Content selection is done only via LoadPreview/SwitchToLive.

Shared invariants (Python does not run ffmpeg, one logical stream per channel) are in the [Overview](Phase8-Overview.md).

## Document Role

This document is a **Coordination Contract**, refining higher-level laws. It does not override laws defined in this directory (see [PlayoutInvariants-BroadcastGradeGuarantees.md](../laws/PlayoutInvariants-BroadcastGradeGuarantees.md)).

## Purpose

Replace the 8.0 dummy byte source with **real MPEG-TS** produced by **Air** (via ffmpeg). Python continues to treat the stream as opaque bytes and only serves HTTP. Viewer validation is via VLC (manual) and automated TS packet checks.

## Contract

### Air

- **Spawns ffmpeg** to produce MPEG-TS for the **currently-live segment**.
- Air MUST select the media source from the **live slot** populated via:
  1. **StartChannel** (channel state only)
  2. **LoadPreview**(channel_id, asset_path, start_offset_ms, hard_stop_time_ms)
  3. **AttachStream**(channel_id, transport, endpoint, …) — **transport only**
  4. **SwitchToLive**(channel_id)
- Air MUST route ffmpeg MPEG-TS output into the attached stream endpoint (e.g. connect ffmpeg stdout to the stream FD via dup2, or equivalent).
- Example (concept): `ffmpeg -re -i <live.asset_path> -f mpegts pipe:1` with stdout connected to the stream FD.
- **Segment control messages are used**, but Phase 8.1 does **not** require enforcement of start_offset_ms or hard_stop_time_ms (that is Phase 8.2). For 8.1, tests use start_offset_ms=0 and hard_stop_time_ms=0 (or omitted/ignored by Air).
- In 8.1, ChannelManager (or the test harness) always calls LoadPreview with start_offset_ms=0 and hard_stop_time_ms=0 (or omitted/ignored). Air may ignore offsets/deadlines in 8.1, but MUST accept the LoadPreview/SwitchToLive flow.

### Python

- **Still treats the stream as opaque bytes** (no TS parsing, no demux).
- **Still only serves HTTP:** `GET /channels/{id}.ts` returns 200 and streams bytes; `Content-Type: video/mp2t`.
- Transport and FD handoff unchanged from 8.0.

## Ordering requirement (8.1)

- **StartChannel** creates channel state only. No media output yet.
- **Media output begins only after both:**
  - a stream is attached (**AttachStream** success), and
  - a live segment exists (**SwitchToLive** success).
- This prevents “StartChannel starts ffmpeg” implementations.

## Content selection for 8.1

- The test harness will issue **LoadPreview** with asset_path = samplecontent.mp4 (or equivalent).
- 8.1 validates that this single live segment can be streamed to VLC.
- No switching is performed within the segment.

## Execution

- Reuse 8.0 transport: Python creates UDS server; Air connects via AttachStream (transport only). After SwitchToLive, Air runs ffmpeg for the live segment and routes its output to the attached stream FD (e.g. dup2 to stream FD; bytes flow to Python and then to HTTP).

## Forbidden in 8.1

- **Adding asset_path (or any content fields) to AttachStream**
- **Starting ffmpeg based on StartChannel.plan_handle**
- **Python spawning ffmpeg or parsing TS**

## Tests

### Automated

- **HTTP 200** for `GET /channels/{channel_id}.ts`.
- **Content-Type: video/mp2t** (or equivalent).
- **At least N TS packets received** (e.g. count 0x47 sync bytes or validate minimal TS structure over the first N bytes).

### Manual (allowed for 8.1)

- Open **VLC**.
- Play **http://localhost:8000/channels/mock.ts** (or chosen channel).
- **Video plays** (samplecontent.mp4 content visible/audible).

## Explicitly out of scope (8.1)

- No Python ffmpeg (Air only).
- No decoding in Python.
- No join-in-progress, no segment switching, no timeline—single file start-to-finish.

## Exit criteria

- **VLC plays** samplecontent.mp4 from the HTTP URL (content selected via LoadPreview + SwitchToLive, not AttachStream).
- **No Python ffmpeg**; no decoding in Python.
- **Clean shutdown** (StopChannel / last viewer close; no zombie ffmpeg, no leaked FDs).
