<!-- ⚠️ Historical document. Superseded by: [PlayoutEngineContract](../../contracts/architecture/PlayoutEngineContract.md) -->

# Phase 6A.3 — ProgrammaticProducer (test pattern)

_Related: [Phase Model](../../contracts/PHASE_MODEL.md) · [Phase 6A Overview](Phase6A-Overview.md) · [Phase6A-1 ExecutionProducer](Phase6A-1-ExecutionProducer.md) · [Phase6A-2 FileBackedProducer](Phase6A-2-FileBackedProducer.md)

**Principle:** Air must be correct before it is fast. Performance guarantees are explicitly deferred until correctness is contractually proven.

Shared invariants are in the [Overview](Phase6A-Overview.md). This producer does not perform file decode or use ffmpeg; it generates synthetic frames only.

## Purpose

Implement a **programmatic producer** that **generates synthetic frames** (e.g. test pattern, colour bars, or constant frame). Proves **heterogeneous producers** work alongside FileBackedProducer: same slot/switch lifecycle, no decoding.

## Contract

**ProgrammaticProducer:**

- **No decode:** Does not read files or call ffmpeg. Generates frames programmatically (e.g. test pattern, solid colour, or time-based pattern).
- **Same interface:** Fits ExecutionProducer lifecycle (Start/Stop) and slot model (can be loaded into preview, promoted to live via SwitchToLive).
- **Frame contract:** Produces frames in the same shape as the rest of the pipeline expects (e.g. resolution, format, PTS progression) so that the engine can treat preview/live uniformly. Exact format may be minimal (e.g. fixed resolution, stub metadata).
- **Segment params:** May accept start_offset_ms and hard_stop_time_ms for consistency; PTS or timing is derived from wall clock or synthetic timeline so that stop at or before hard_stop_time_ms is honored.
- **Minimal timing (6A.3):** ProgrammaticProducer uses **monotonic** frame timestamps (e.g. starting at 0 for preview). On **SwitchToLive**, either continue with a continuous timeline for live output or reset timestamps; for 6A.3 **reset is permitted** because TS/Renderer is deferred and the output contract is not yet enforced.

## Execution

- Implement ProgrammaticProducer that generates synthetic frames (e.g. test pattern); plug into the same preview/live slot path as FileBackedProducer.
- Tests: LoadPreview with programmatic “asset” (or segment type), then SwitchToLive; assert no decode, and that frames (or a placeholder) are produced and switching works. Optional: run a sequence FileBackedSegment → ProgrammaticSegment to prove alternation.

## Tests

- ProgrammaticProducer can be loaded into preview and switched to live; no file or ffmpeg involved.
- Engine can switch from FileBackedProducer to ProgrammaticProducer (or vice versa) using the same LoadPreview + SwitchToLive flow.
- Stop at hard_stop_time_ms (or StopChannel) stops the programmatic producer; no frames after stop.
- Heterogeneity: both producer types coexist in the same build and same control flow.

## Out of scope (6A.3)

- Real codec or quality of test pattern; only “synthetic frames exist and lifecycle matches”.
- MPEG-TS serving, Renderer placement, performance.

## Exit criteria

- ProgrammaticProducer implemented; generates synthetic frames; same lifecycle as ExecutionProducer.
- Heterogeneous producers (file-backed + programmatic) both work with LoadPreview/SwitchToLive.
- Automated tests pass without any decoding (no ffmpeg for programmatic path).
