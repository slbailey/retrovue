# Phase 8.2 — Segment Control → ffmpeg Seek + Stop

_Related: [Phase Model](../../contracts/PHASE_MODEL.md) · [Phase 8 Overview](Phase8-Overview.md) · [Phase8-1 Air Owns MPEG-TS](Phase8-1-AirOwnsMpegTs.md) · [Phase8-3 Preview/SwitchToLive](Phase8-3-PreviewSwitchToLive.md) · [Phase 6A Overview](Phase6A-Overview.md)_

**Principle:** Connect the existing segment logic (Phases 3–6) to ffmpeg execution. Join-in-progress and hard stops are enforced; no switching yet.

Shared invariants (segment authority: start_offset_ms and hard_stop_time_ms from Python/Phase 4, enforced by Air) are in the [Overview](Phase8-Overview.md).

## Purpose

Drive **ffmpeg** with:
- **start_offset_ms** → input seek (e.g. `-ss` before `-i` or equivalent) so tune-in at +2 min or +17 min gives the correct offset.
- **hard_stop_time_ms** → stop writing TS at or before that wall-clock time (duration or wall-clock check).

Python is unchanged; it still reads opaque bytes and serves HTTP. This is where Phases 3–6 pay off in the TS path.

## Contract

### Air

- **Uses segment parameters** when launching or controlling ffmpeg:
  - **start_offset_ms** → applied as seek (e.g. `-ss` in seconds, or equivalent) so that the first byte of TS corresponds to that offset in the asset.
  - **hard_stop_time_ms** → enforced by:
    - either supplying a **duration** so ffmpeg stops at the right point, or
    - monitoring wall-clock and **stopping the write path** at or before hard_stop_time_ms (no bytes past that time).
- **Stops writing TS** at the hard stop; closes or drains the stream cleanly.
- **No switching yet:** one segment per channel at a time; at boundary, a new LoadPreview/ffmpeg instance can be used, but 8.2 does not require seamless SwitchToLive in the TS (that is 8.3).

### Python

- **Unchanged:** still creates transport, passes write end to Air, serves `GET /channels/{id}.ts` as opaque bytes. Segment choice and parameters are decided by Python/Phase 4 and sent via LoadPreview (or equivalent) to Air.

## Execution

- ChannelManager (or test) decides “current segment” from plan/clock (Phase 3/4). It sends:
  - asset_path
  - start_offset_ms (e.g. 120_000 for +2 min)
  - hard_stop_time_ms (e.g. grid end in epoch ms)
- Air starts ffmpeg with `-ss <start_offset_ms/1000>` (or equivalent) and enforces hard stop (duration or wall-clock). TS is written to the stream FD; Python serves it.

## Tests

- **Tune in at +2 min** → video starts approximately 2 min into the asset (probe or VLC observation).
- **Tune in at +17 min** → correct offset (e.g. 17 min into program segment).
- **Tune in at filler** → filler segment plays (correct asset and offset).
- **Hard stop:** advance clock past hard_stop_time_ms; assert no TS bytes (or stream ends) after that time.
- **No drift over one block:** over a single grid block, offsets and stop time remain aligned (no accumulating error).

## Explicitly out of scope (8.2)

- No preview/live switching; no seamless SwitchToLive in the TS path (8.3).
- No fan-out or last-viewer teardown semantics (8.4)—single viewer sufficient for 8.2.

## Exit criteria

- **Join-in-progress works** (start_offset_ms maps correctly to ffmpeg seek).
- **Hard stops respected** (no output past hard_stop_time_ms).
- **No drift over one block** (single grid block; offsets and stop times consistent).
