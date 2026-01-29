<!-- ⚠️ Historical document. Superseded by: [FileProducerDomainContract](../../contracts/architecture/FileProducerDomainContract.md) -->

# Phase 6A.2 — FileBackedProducer (minimal)

_Related: [Phase Model](../../contracts/PHASE_MODEL.md) · [Phase 6A Overview](Phase6A-Overview.md) · [Phase6A-1 ExecutionProducer](Phase6A-1-ExecutionProducer.md)_

**Principle:** Air must be correct before it is fast. Performance guarantees are explicitly deferred until correctness is contractually proven.

Shared invariants (including hard_stop_time_ms authoritative) are in the [Overview](Phase6A-Overview.md). Use of ffmpeg or libav is an implementation detail; the contract is “file in, frames (or sink) out.”

## Purpose

Implement a **minimal file-backed producer** that uses the **ffmpeg executable** (or equivalent), with **hard-coded output** (null sink or file). It must **honor** `start_offset_ms` and `hard_stop_time_ms`. Proves real decode path without TS or Renderer.

## Contract

**FileBackedProducer:**

- **Input:** Segment params from LoadPreview: `asset_path`, `start_offset_ms`, `hard_stop_time_ms` (wall-clock epoch ms).
- **Decode:** Uses ffmpeg (or a single external decode path) to read the file and produce decoded output. Implementation may be “ffmpeg process” or libav; contract is “file in, frames (or sink) out”. Choice of ffmpeg vs libav is an implementation detail, not an architectural requirement.
- **Output (6A.2):** **Hard-coded** — e.g. null sink, or write to a known test file. No MPEG-TS serving, no Renderer placement, no configurable output format.
- **Seek:** Starts at `start_offset_ms` (media-relative). Join-in-progress: decode must seek to a position **at or before** `start_offset_ms` (codec/GOP may prevent frame-exact seek); the contract is “no playback earlier than intended,” not that the first decoded frame’s timestamp equals `start_offset_ms` exactly.
- **Stop:** Stops **at or before** `hard_stop_time_ms`. Engine must not play past this time (encoder latency, PTS rounding, or real hardware may cause stop slightly before; never after). Air may enforce the hard stop by converting `(hard_stop_time_ms − now_ms)` into a duration limit for ffmpeg (e.g. `-t`) and/or by supervising wall clock and terminating the producer; the **observable guarantee** is the same: never exceed hard stop.
- **Lifecycle:** Integrates with ExecutionProducer interface; Start(segment) and Stop(); teardown releases resources.

## Execution

- Implement FileBackedProducer that:
  - Accepts segment (asset_path, start_offset_ms, hard_stop_time_ms).
  - Invokes ffmpeg (or single decode path) with start offset and duration/stop derived from hard_stop_time_ms.
  - Writes to null sink or a fixed test file.
- Tests use a **short, known-duration test asset** committed to the repo (or generated once), with **verified duration metadata**. Assert that output exists and that playback respects start and does not exceed hard_stop_time_ms (e.g. by duration or by wall-clock check).

## Tests

- Given a test file and segment (start_offset_ms=0, hard_stop_time_ms=T+30s): producer runs and stops by T+30s; no frames (or bytes) after that time.
- Given start_offset_ms=60_000 (1 min): validate seek by **reported timestamps** (e.g. ffprobe output or ffmpeg stderr), not by assuming the first decoded frame is exact; seek must be at or before 60s, within a bounded tolerance, and must not start earlier than `(start_offset_ms − tolerance)`.
- StopChannel (or segment stop) causes producer to stop and release resources; no orphan ffmpeg processes.
- Invalid path or unreadable file yields defined error (e.g. LoadPreviewResponse.success=false or equivalent).

## Out of scope (6A.2)

- MPEG-TS output and serving.
- Renderer placement and frame format contracts (beyond “decode runs”).
- Performance or latency targets; buffer depth; PTS continuity across switches (can be basic).

## Exit criteria

- FileBackedProducer uses ffmpeg (or single decode path), honors start_offset_ms and hard_stop_time_ms.
- Output is hard-coded (null or file); no TS or Renderer dependency.
- Automated tests pass with a real test asset.
