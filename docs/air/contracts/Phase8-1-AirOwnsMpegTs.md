# Phase 8.1 — Air Owns MPEG-TS (single segment, no switching)

_Related: [Phase Model](../../contracts/PHASE_MODEL.md) · [Phase 8 Overview](Phase8-Overview.md) · [Phase8-0 Transport](Phase8-0-Transport.md) · [Phase8-2 Segment Control](Phase8-2-SegmentControl.md)_

**Principle:** Prove that ffmpeg → Air → socket → Python → HTTP works for **one file**, no switching, no timeline. This is the first time VLC appears.

Shared invariants (Python does not run ffmpeg, one logical stream per channel) are in the [Overview](Phase8-Overview.md).

## Purpose

Replace the 8.0 dummy byte source with **real MPEG-TS** produced by **Air** (via ffmpeg). Python continues to treat the stream as opaque bytes and only serves HTTP. Viewer validation is via VLC (manual) and automated TS packet checks.

## Contract

### Air

- **Spawns ffmpeg** (or equivalent) to produce MPEG-TS.
- **Outputs valid MPEG-TS** to the stream FD provided by Python (same transport as 8.0).
- **Writes TS bytes** to that FD until the file ends or stop is requested.
- **Uses** (or equivalent):
  ```text
  ffmpeg -re -i samplecontent.mp4 -f mpegts pipe:1
  ```
- No segment logic yet (no start_offset_ms / hard_stop_time_ms); single contiguous file.

### Python

- **Still treats the stream as opaque bytes** (no TS parsing, no demux).
- **Still only serves HTTP:** `GET /channels/{id}.ts` returns 200 and streams bytes; `Content-Type: video/mp2t`.
- Transport and FD handoff unchanged from 8.0.

## Execution

- Reuse 8.0 transport: Python creates read/write pair, passes write end to Air via `AttachStream` (or equivalent). Air, instead of writing `"HELLO\n"`, runs ffmpeg with output to the write end.
- Ensure ffmpeg stdout is connected to the stream FD; Air reads (or does not block on) ffmpeg; bytes flow to Python and then to HTTP.

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

- **VLC plays** samplecontent.mp4 from the HTTP URL.
- **No Python ffmpeg**; no decoding in Python.
- **Clean shutdown** (StopChannel / last viewer close; no zombie ffmpeg, no leaked FDs).
