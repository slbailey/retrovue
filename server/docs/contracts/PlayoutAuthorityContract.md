# Playout Authority Contract

**Status**: Active
**Effective**: 2025-02
**Enforced by**: `PLAYOUT_AUTHORITY` constant in `channel_manager.py`

---

## Authority

The **BlockPlan playout path** is the sole authoritative path for live
channel playout in RetroVue.

```
PLAYOUT_AUTHORITY = "blockplan"
```

When this constant is set, no other playout path may be invoked for live
channels.  Attempts to do so will raise a `RuntimeError` with a
descriptive message referencing `INV-PLAYOUT-AUTHORITY`.

---

## Ownership Boundaries

| Concern | Owner | Must NOT cross to |
|---------|-------|-------------------|
| Scheduling, lifecycle, viewer management | Core | AIR |
| Timing, cadence, frame pacing | AIR | Core |
| Encoding, muxing, TS output | AIR | Core |
| Block generation, feeding | Core | AIR (no mid-block) |
| Block execution, fence detection | AIR | Core |

---

## Invariants

### INV-PLAYOUT-AUTHORITY
Only `BlockPlanProducer` may be constructed for live channels.  The
legacy per-segment producer path is retained for reference but blocked
from execution. See [Phase8DecommissionContract](../../../../docs/contracts/architecture/Phase8DecommissionContract.md).

### INV-ONE-ENCODER-PER-SESSION
AIR creates exactly one `EncoderPipeline` per playout session.  The
encoder is opened at session start and closed at session end.  Block
boundaries do not reset, flush, or reinitialize the encoder.

### INV-ONE-PLAYOUT-PATH-PER-CHANNEL
A channel has exactly one active `Producer` at any time.  There is no
fallback or automatic mode switching between BlockPlan and legacy paths.

### INV-NO-MID-BLOCK-CONTROL
Core does not send RPCs to AIR during block execution.  The only
control-plane events at block boundaries are:
- `BlockCompleted` (AIR → Core): block reached its fence
- `SessionEnded` (AIR → Core): session terminated
- `FeedBlockPlan` (Core → AIR): next block supplied

### INV-SERIAL-BLOCK-EXECUTION
Blocks execute sequentially.  Block N must complete before Block N+1
begins.  There is no overlapping execution.

---

## Telemetry

Each session emits a one-time architectural telemetry log on both sides:

**Core** (Python, at session start):
```
INV-PLAYOUT-AUTHORITY: Channel <id> session started |
  playout_path=blockplan |
  encoder_scope=session |
  execution_model=serial_block |
  block_duration_ms=<ms> |
  authority=blockplan
```

**AIR** (C++, at encoder open):
```
[INV-PLAYOUT-AUTHORITY] channel_id=<id> |
  playout_path=blockplan |
  encoder_scope=session |
  execution_model=serial_block |
  format=<W>x<H>@<fps>
```

---

## Legacy Path Status

| Component | Status | Guardrail |
|-----------|--------|-----------|
| Legacy per-segment producer | Retained, blocked | `start()` raises `RuntimeError` |
| Legacy per-segment RPCs (gRPC) | Retained in proto | Not invoked by BlockPlan path |

*Removed semantics (per-segment producer, RPC names, playlist path): [Phase8DecommissionContract](../../../../docs/contracts/architecture/Phase8DecommissionContract.md).*
| `NormalProducer` | Stub, unused | No guardrail needed |
| `EmergencyProducer` | Stub, unused | No guardrail needed |
| `GuideProducer` | Stub, unused | No guardrail needed |

Legacy code is not deleted.  It is frozen and guarded to prevent
accidental invocation.  Future cleanup may remove it once the BlockPlan
path has sufficient operational history.

---

## CONTINUOUS_OUTPUT Execution Mode (P3.0 + P3.1a + P3.1b)

The `kContinuousOutput` mode emits a continuous frame stream at fixed cadence.
Unlike SERIAL_BLOCK, frames are emitted even when no block content is available
(pad frames fill the gap).

### Differences from SERIAL_BLOCK

| Aspect | SERIAL_BLOCK | CONTINUOUS_OUTPUT |
|--------|--------------|-------------------|
| Output between blocks | No frames | Pad frames |
| Frame timing | Per-block deadline | Session-global OutputClock |
| PTS source | CT-based (reset per block) | Session-frame-index (N * 3000) |
| Encoder lifecycle | Session-long | Session-long |
| Frame count per block | floor(duration / frame_dur) | ceil(duration / frame_dur) |
| Deterministic fence | CT >= block_duration | ticks >= frames_per_block |

### Tick Ownership & BlockSource

- **Engine owns time**: `source_ticks_` counter incremented per tick in the main loop
- **BlockSource reacts**: EMPTY → READY (AssignBlock), decodes on demand, READY → EMPTY (Reset)
- **Fence is engine-side**: `source_ticks_ >= FramesPerBlock()` → block complete
- Decode failure → pad frame, tick still counts toward fence

### AssignBlock Constraint

`AssignBlock()` is synchronous and may stall (probe + open + seek).
`TryLoadActiveBlock()` (which calls `AssignBlock()`) is only invoked when the
source is EMPTY — outside the clock-wait/frame-emission path.  It must never
be moved into the clock wait section, the frame emission path, or any code
that assumes it completes before the next tick.

### Preserved Guarantees

- INV-ONE-ENCODER-PER-SESSION: Encoder opened once, closed once
- Monotonic PTS: PTS(N) = N * frame_duration_90k
- Session-wide audio PTS: samples_emitted * 90000 / 48000

### P3.1b: A/B Source Swap with Background Preloading

P3.1b extends the ContinuousOutput engine with a `SourcePreloader` and `next_source_`
to enable gapless block transitions.

#### Design

- **SourcePreloader**: Background thread that creates a `BlockSource` and calls
  `AssignBlock()` off the tick thread. Produces a fully READY source that the
  engine can adopt via pointer swap.
- **next_source_**: A pre-loaded `BlockSource` held by the engine. At the block
  fence, if `next_source_` is READY, the engine swaps it into `active_source_`
  without stalling the tick loop.
- **Fence swap algorithm**: At `source_ticks_ >= FramesPerBlock()`:
  1. Fire `on_block_completed` callback
  2. Check `next_source_` — if READY, swap to active (source_swap_count++)
  3. If not, check `preloader_->TakeSource()` — if READY, swap
  4. If neither available, reset active to EMPTY, enter pad mode (`past_fence = true`)
  5. Kick off preload for following block

#### Safety Rules

1. `AssignBlock()` is NEVER called from the tick window — only from `SourcePreloader::Worker()`
   (background thread) or `TryLoadActiveBlock()` (outside tick window, fallback path)
2. `SourcePreloader` is cancel-safe: `Cancel()` joins the worker thread and discards result
3. `Stop()` cancels the preloader before joining the engine thread (no deadlock)
4. `next_source_` is only accessed from the engine thread (no cross-thread contention)

#### Metrics (P3.1b)

| Metric | Type | Description |
|--------|------|-------------|
| `air_continuous_source_swap_count` | counter | Source swaps at block fence |
| `air_continuous_next_preload_started_total` | counter | Preloads kicked off |
| `air_continuous_next_preload_ready_total` | counter | Preloads ready at consumption |
| `air_continuous_next_preload_failed_total` | counter | Preloads failed or not ready |
| `air_continuous_fence_pad_frames_total` | counter | Pad frames after fence (next not ready) |

#### Contract Tests (P3.1b)

| Test ID | Description |
|---------|-------------|
| CONT-SWAP-001 | Source swap count increments for back-to-back blocks |
| CONT-SWAP-002 | No deadlock when Stop() called during preload |
| CONT-SWAP-003 | Delayed preload does not stall engine (delay hook test) |
| CONT-SWAP-004 | AssignBlock runs on background thread (not tick thread) |
| CONT-SWAP-005 | PTS monotonic across source swaps (regression check) |

---

## Why SERIAL_BLOCK Exists

The `SERIAL_BLOCK` execution mode (`PlayoutExecutionMode::kSerialBlock`)
is the baseline and only implemented execution model.  It is frozen as
the known-correct foundation before any future mode is introduced.

### What SERIAL_BLOCK Guarantees

| Guarantee | Description |
|-----------|-------------|
| One encoder per session | `EncoderPipeline` is opened once at session start and closed at session end.  Block boundaries do not touch the encoder lifecycle. |
| Sequential execution | Block N must complete (reach its fence) before Block N+1 begins.  There is no overlapping, pipelined, or speculative execution. |
| CT resets per block | Content Time (CT) resets to 0 at each block boundary.  PTS is session-monotonic via accumulated offset. |
| No orphan frames | No frames are emitted before the first block, between blocks, or after the last block. |
| Deterministic frame count | Given identical `block_duration_ms` and `kFrameDurationMs`, the frame count per block is constant: `floor(duration / frame_duration)`. |

### Why This Mode Is Frozen

1. **Known correct**: Serial block execution has been validated end-to-end
   with real MPEG-TS output, VLC playback, and PTS continuity verification.
2. **Baseline for comparison**: Any future mode (e.g., `CONTINUOUS_OUTPUT`)
   must demonstrate improvements over this baseline without breaking the
   guarantees above.
3. **Contract test coverage**: The `SerialBlockBaselineContractTests` suite
   locks these guarantees.  These tests must always pass regardless of what
   future execution modes are added.

### Enum Declaration (AIR)

```cpp
// BlockPlanTypes.hpp
enum class PlayoutExecutionMode {
  kSerialBlock,        // Implemented, frozen
  kContinuousOutput,   // Future placeholder (not implemented)
};
```

### Telemetry

The `execution_model` field in the architectural telemetry log is derived
from the enum via `PlayoutExecutionModeToString()`, ensuring the log
value always matches the code constant.

### Future: CONTINUOUS_OUTPUT

The `kContinuousOutput` placeholder exists in the enum but has no
implementation, no branching behavior, and no test coverage.  When
implemented, it will require:
- Its own contract test suite
- A design document (`docs/architecture/proposals/ContinuousOutputDesign.md`)
- Explicit opt-in (no silent mode switching)
- All `SERIAL_BLOCK` baseline tests must continue to pass

---

## Execution Engine Selection

Execution engines are selected by `PlayoutExecutionMode` at session
start time.  This is a structural seam — the engine interface exists
to allow future modes without modifying the gRPC service layer.

### Interface

```cpp
// IPlayoutExecutionEngine.hpp
class IPlayoutExecutionEngine {
 public:
  virtual ~IPlayoutExecutionEngine() = default;
  virtual void Start() = 0;  // Spawn execution thread
  virtual void Stop() = 0;   // Signal and join (idempotent)
};
```

The interface does NOT expose timing, clocks, or content logic.

### Engine Selection Logic

At `StartBlockPlanSession`, the execution mode determines which
engine is constructed:

```cpp
if (execution_mode == kSerialBlock) {
  engine = std::make_unique<SerialBlockExecutionEngine>(...);
} else {
  // NOT IMPLEMENTED — reject session with error
}
```

### Current State

| Execution Mode | Engine Class | Status |
|----------------|-------------|--------|
| `kSerialBlock` | `SerialBlockExecutionEngine` | Active, tested |
| `kContinuousOutput` | (none) | Rejected at startup |

### SerialBlockExecutionEngine

A mechanical extraction of the former `BlockPlanExecutionThread` into
a standalone engine class.  No logic changes from the original.

**Owns:**
- The execution thread
- The session-long `EncoderPipeline`
- The block execution loop

**Shares (via `BlockPlanSessionContext*`):**
- Block queue (written by `FeedBlockPlan`, read by engine)
- Stop flag (written by `Stop()`, checked by loop)
- Result fields (`final_ct_ms`, `blocks_executed`)

**Delegates (via callbacks):**
- `on_block_completed` → `EmitBlockCompleted` (gRPC event emission)
- `on_session_ended` → `EmitSessionEnded` (gRPC event emission)

### Shared Types

| Type | Location | Purpose |
|------|----------|---------|
| `FedBlock` | `BlockPlanSessionTypes.hpp` | Block as received from Core |
| `BlockPlanSessionContext` | `BlockPlanSessionTypes.hpp` | Engine-visible session state (no gRPC) |
| `FedBlockToBlockPlan()` | `BlockPlanSessionTypes.hpp` | Convert to executor type |

`BlockPlanSessionState` (in `playout_service.h`) inherits from
`BlockPlanSessionContext` and adds gRPC-specific fields (event
subscribers).  This inheritance preserves all field access patterns.

### Guardrail Tests

The `ExecutionEngineGuardrailTests` suite verifies:
- `kSerialBlock` selects `SerialBlockExecutionEngine`
- `kContinuousOutput` is declared but has no engine
- Engine `Start()`/`Stop()` lifecycle is correct and idempotent
- No execution occurs without an engine
- Engine respects shared `stop_requested` flag
- Engine emits `session_ended` callback on exit
- `FedBlockToBlockPlan` preserves all fields

---

## Mid-Asset Seek Strategy

Blocks may start mid-asset based on schedule time (e.g., "start this block
3 minutes into the movie").  The `asset_start_offset_ms` field in each
segment controls where decoding begins within the asset.

### Seek Mechanism

1. `SeekToMs()` calls `av_seek_frame()` with `AVSEEK_FLAG_BACKWARD`, which
   lands on the nearest **keyframe before** the target position.
2. `SeekPreciseToMs()` wraps `SeekToMs()` with **decoder preroll**: it
   decodes and discards frames between the keyframe and the target until
   the first frame with PTS >= target is found.
3. The first frame emitted to the encoder corresponds to the requested
   asset offset, within one frame of accuracy.

### Audio During Preroll

Audio frames decoded during preroll are flushed (not emitted).  Audio
emission resumes from the first on-target video frame.

### Frame Count Determinism

Frame count is CT-based: `floor(block_duration_ms / kFrameDurationMs)`.
The number of preroll frames discarded does not affect the emitted frame
count.  A block of the same duration produces the same number of frames
regardless of `asset_start_offset_ms`.

### Instrumentation

Each precise seek logs:
```
[METRIC] seek_precise_us=<microseconds> preroll_frames=<count> target_ms=<offset>
```

### Contract Tests

The `MidAssetSeekContractTests` suite verifies:
- Offset 0 matches baseline behavior (TEST-SEEK-001)
- Mid-asset first frame has correct offset (TEST-SEEK-002)
- Different offsets produce different first frames (TEST-SEEK-003)
- Frame count is deterministic regardless of offset (TEST-SEEK-004)
- Offset near asset end causes underrun with pad frames (TEST-SEEK-005)
- Validator rejects offset >= asset_duration (TEST-SEEK-006)
- Multi-segment per-segment offsets propagate correctly (TEST-SEEK-007)

---

## SerialBlock Baseline Metrics

The `SerialBlockExecutionEngine` exposes passive observability metrics via
the `/metrics` Prometheus endpoint.  These metrics do NOT affect execution,
timing, or control flow.  They exist to lock in the baseline behavior of
the `SERIAL_BLOCK` execution mode.

### Metric Prefix

All serial block metrics use the `air_serial_block_` prefix.

### Metrics Inventory

| Metric | Type | Description |
|--------|------|-------------|
| `air_serial_block_session_duration_ms` | gauge | Total session duration |
| `air_serial_block_session_active` | gauge | 1 if session running, 0 otherwise |
| `air_serial_block_blocks_executed_total` | counter | Blocks executed in session |
| `air_serial_block_frames_emitted_total` | counter | Frames emitted in session |
| `air_serial_block_max_inter_frame_gap_us` | gauge | Worst inter-frame gap (microseconds) |
| `air_serial_block_mean_inter_frame_gap_us` | gauge | Mean inter-frame gap (microseconds) |
| `air_serial_block_frame_gaps_over_40ms_total` | counter | Gaps exceeding 40ms (~1.2x frame period) |
| `air_serial_block_max_boundary_gap_ms` | gauge | Worst block-to-block transition gap |
| `air_serial_block_mean_boundary_gap_ms` | gauge | Mean block-to-block transition gap |
| `air_serial_block_max_asset_probe_ms` | gauge | Worst per-block asset probe time |
| `air_serial_block_assets_probed_total` | counter | Total assets probed across all blocks |
| `air_serial_block_encoder_open_count` | counter | Encoder opens (must be 1) |
| `air_serial_block_encoder_close_count` | counter | Encoder closes (must be 1) |
| `air_serial_block_encoder_open_ms` | gauge | Time to open encoder |
| `air_serial_block_time_to_first_ts_ms` | gauge | Time from session start to first TS packet |

### Implementation

Metrics are accumulated in `SerialBlockMetrics` (header-only struct) within
the engine, protected by a mutex for thread-safe reads.  The engine exposes
`GenerateMetricsText()` which produces Prometheus text exposition format.

The metrics are wired to `/metrics` via `MetricsExporter::RegisterCustomMetricsProvider()`
at `StartBlockPlanSession` and unregistered at `StopBlockPlanSession`.

### Frame Cadence Measurement

Per-block frame cadence is captured inside `RealTimeBlockExecutor::Execute()` via
the `FrameCadenceMetrics` sub-struct in `Result`.  Each block's cadence metrics
(frames emitted, max/sum inter-frame gap, gaps over 40ms) are accumulated into
the session-level `SerialBlockMetrics` after block completion.

### Guardrail Tests

The `SerialBlockMetricsTests` suite verifies:
- All metric fields initialize to zero
- Prometheus text uses `air_serial_block_` prefix with correct TYPE/HELP
- Prometheus text reflects accumulated values correctly
- Mean inter-frame gap computed correctly (and zero-safe)
- Engine metrics are zero before `Start()`
- `GenerateMetricsText()` is thread-safe under concurrent access
- Encoder open/close counts are both 1 (INV-ONE-ENCODER-PER-SESSION)
- `session_active` gauge reflects running/stopped state
- `FrameCadenceMetrics` default-constructs to zero in `Result`

---

## P2 – Serial Block Preloading

### Purpose

Reduce block-boundary stalls by preloading the next block's heavy resources
(asset probe + decoder open + seek) while the current block is executing.

This is **stall reduction**, not stall elimination. The execution model
remains SERIAL_BLOCK. This phase is a stepping stone toward
ContinuousOutput.

### What Stalls Are Reduced

| Stall Source | Typical Cost | Preloaded? |
|---|---|---|
| Asset probe (avformat_open_input + find_stream_info) | 8–16ms | Yes |
| Redundant executor-level re-probe | 5–8ms | Yes |
| Decoder open (FFmpegDecoder::Open) | 5–6ms | Yes |
| SeekPreciseToMs (preroll to offset) | 0–42ms | Yes |
| Block validation + join computation | <1ms | No (CPU-only, trivial) |
| Encoder lifecycle | 0ms | N/A (session-long, unchanged) |

### What Is NOT Changed

- **CT resets per block** — unchanged
- **Frame count** — deterministic from block_duration, unaffected by preload
- **PTS continuity** — CT-based, unaffected
- **Encoder lifecycle** — session-long, one open/close per session
- **Execution model** — Block N completes entirely before Block N+1 begins
- **Pad frame behavior** — no pad frames introduced by preloading

### Design

**BlockPreloadContext**: Lightweight struct holding pre-probed assets and
optionally a pre-opened, pre-seeked decoder. No timing logic, no encoder
references.

**BlockPreloader**: Background thread that probes assets and optionally
opens a decoder for the next block. Runs during the current block's
~5-second execution, so it has ample time. Cancel-safe via atomic flag
checked between heavy operations.

**Integration**: The engine peeks at the next block in the queue before
calling `Execute()`. If a preload result is available and matches the
current block_id, it is consumed. Otherwise, the engine falls back to
the synchronous probe/open behavior.

**Decoder handoff**: The preloaded decoder is installed in the sink via
`InstallPreloadedDecoder()`. If the asset URI or seek offset don't match
the first frame, the sink's existing logic detects the mismatch and
re-seeks (graceful fallback).

### Safety Rules

1. Preload must respect `Stop()` immediately (cancel_requested_ atomic)
2. Decoder ownership transfers via `std::unique_ptr` — no leaks, no double-close
3. No shared mutable decoder across blocks
4. Encoder is unchanged and remains session-long
5. Stale preloads (wrong block_id) are discarded, not used

### Instrumentation

| Metric | Type | Description |
|---|---|---|
| `preload_attempted_total` | counter | Times preload was started |
| `preload_ready_at_boundary_total` | counter | Times preload was ready when needed |
| `preload_fallback_total` | counter | Times fell back to sync probe |
| `preload_probe_max_us` | gauge | Worst preload asset probe time |
| `preload_probe_mean_us` | gauge | Mean preload asset probe time |
| `preload_decoder_open_max_us` | gauge | Worst preload decoder open time |
| `preload_seek_max_us` | gauge | Worst preload seek time |

Per-block log line: `[METRIC] preload_hit block_id=... probe_us=... decoder_ready=...`

### Contract Tests (BlockPreloadContractTests.cpp)

| Test ID | Description |
|---|---|
| PRELOAD-001 | Cancel without Start is safe |
| PRELOAD-002 | TakeIfReady returns nullptr when no preload started |
| PRELOAD-003 | Cancel interrupts in-progress preload |
| PRELOAD-004 | Destructor cleans up without hanging |
| PRELOAD-005 | StartPreload cancels previous preload |
| PRELOAD-006 | Stale preload context is discarded |
| PRELOAD-007 | Default BlockPreloadContext state is safe |
| PRELOAD-008 | Engine Stop cancels preloader (no hang) |
| PRELOAD-009 | Preload metrics initialized to zero |
| PRELOAD-010 | Frame count deterministic (baseline) |
| PRELOAD-011 | Frame count identical with mid-asset offset |
| PRELOAD-012 | Frame count identical for different assets |
| PRELOAD-013 | Prometheus text includes preload metrics |

---

## P3.2 — Seam Proof: Real-Media Boundary Verification

P3.2 adds verification infrastructure to **prove** seamless block transitions
by fingerprinting frames at the encode boundary and asserting zero-pad gaps.

### Design

**FrameFingerprint**: Per-frame record emitted via optional `on_frame_emitted`
callback in `ContinuousOutputExecutionEngine::Callbacks`. Contains:
- `session_frame_index`: Global frame counter
- `is_pad`: Whether this was a pad frame
- `active_block_id`: Block ID active at emission time
- `asset_uri` / `asset_offset_ms`: Source metadata (from BlockSource::FrameData)
- `y_crc32`: CRC32 of the first 4096 bytes of the Y plane

**BoundaryReport**: Captures the last 5 frames of block A and first 5 frames
of block B around a fence transition. Reports `pad_frames_in_window` — the
count of pad frames in the 10-frame window around the boundary.

**CRC32YPlane**: Uses zlib `crc32()` on the first `kFingerprintYBytes` (4096)
bytes of Y plane data. Returns 0 for null/empty data (pad frames).

### BlockSource FrameData Extension

`BlockSource::FrameData` carries `asset_uri` and `block_ct_ms` fields populated
in `TryGetFrame()`. The `block_ct_ms` value is captured before the internal
position advance, representing the content time at the start of the frame.

### Engine Integration

- `on_frame_emitted` callback fires after every frame (real or pad), zero cost
  when not wired
- `SetPreloaderDelayHook()` forwards to `SourcePreloader::SetDelayHook()` for
  test injection of preload delays
- Fingerprint emission occurs at the encode boundary, after the frame is
  encoded but before fence check

### Standalone Verify Harness

`retrovue_air_seam_verify` is a standalone executable that accepts two blocks
via CLI args, runs them through `ContinuousOutputExecutionEngine`, collects
fingerprints, builds a `BoundaryReport`, and asserts seamless transitions.

### Contract Tests (SeamProofContractTests.cpp)

| Test ID | Description |
|---------|-------------|
| SEAM-PROOF-001 | PreloadSuccessZeroFencePad — instant preload yields zero fence pad |
| SEAM-PROOF-002 | PreloadDelayerCausesFencePad — 2s delay hook causes fence pad > 0 |
| SEAM-PROOF-003 | FingerprintCallbackFiresEveryFrame — callback count matches metric |
| SEAM-PROOF-004 | FrameDataCarriesMetadata — FrameData has asset_uri/block_ct_ms |
| SEAM-PROOF-005 | RealMediaBoundarySeamless — GTEST_SKIP if assets missing |
| SEAM-PROOF-006 | BoundaryReportGeneration — unit test on BuildBoundaryReport |

---

## P3.3 — Execution Trace & Proof Logs

P3.3 adds deterministic, low-volume, per-block playback summary logs that prove
what content was actually played. These logs reflect actual execution, not
scheduled intent.

### Design

This phase is **observability only** — no behavioral changes. Summary and seam
data is aggregated from frame-level metadata already available in the tick loop.

### BlockPlaybackSummary

Aggregated per-block execution record finalized when the block reaches its fence.

| Field | Type | Description |
|-------|------|-------------|
| `block_id` | string | Block identity |
| `asset_uris` | vector | Unique asset URIs observed, in order |
| `first_block_ct_ms` | int64 | CT of first real frame (-1 if all pad) |
| `last_block_ct_ms` | int64 | CT of last real frame (-1 if all pad) |
| `frames_emitted` | int64 | Total frames (real + pad) |
| `pad_frames` | int64 | Pad frame count |
| `first_session_frame_index` | int64 | Global session frame at block start |
| `last_session_frame_index` | int64 | Global session frame at block end |

### Log Format

Per-block summary (emitted at fence):
```
[CONTINUOUS-PLAYBACK-SUMMARY] block_id=... asset=... asset_range=0-4950ms frames=152 pad_frames=0 session_frames=0-151
```

Seam transition (emitted at source swap or new block load):
```
[CONTINUOUS-SEAM] from=BLOCK-A to=BLOCK-B fence_frame=151 pad_frames_at_fence=0 status=SEAMLESS
```

### SeamTransitionLog

| Field | Type | Description |
|-------|------|-------------|
| `from_block_id` | string | Completed block |
| `to_block_id` | string | New active block |
| `fence_frame` | int64 | Session frame at fence |
| `pad_frames_at_fence` | int64 | Pad frames between blocks |
| `seamless` | bool | True if pad_frames_at_fence == 0 |

### Engine Callbacks (P3.3)

| Callback | Description |
|----------|-------------|
| `on_block_summary` | Optional. Fired before `on_block_completed` at fence. |
| `on_seam_transition` | Optional. Fired at source swap or new block load after fence. |

### Contract Tests (PlaybackTraceContractTests.cpp)

| Test ID | Description |
|---------|-------------|
| TRACE-001 | SummaryProducedPerBlock — one summary per completed block |
| TRACE-002 | SummaryFrameCountMatchesMetrics — frames_emitted == FramesPerBlock |
| TRACE-003 | SummaryPadCountAccurate — all-pad block has pad_frames == frames_emitted |
| TRACE-004 | SummarySessionFrameRange — contiguous, non-overlapping session frames |
| TRACE-005 | SeamTransitionLogProduced — seam log emitted for back-to-back blocks |
| TRACE-006 | SeamlessTransitionStatus — instant preload produces SEAMLESS status |
| TRACE-007 | PaddedTransitionStatus — delayed preload produces PADDED status |
| TRACE-008 | FormatPlaybackSummaryOutput — format string matches contract |
| TRACE-009 | FormatSeamTransitionOutput — format string matches contract |
| TRACE-010 | RealMediaSummaryWithAssetIdentity — GTEST_SKIP if assets missing |
| TRACE-011 | BlockAccumulatorUnitTest — direct unit test on aggregation logic |

---

## P3.3b — Playback Proof: Wanted vs Showed

P3.3b extends the execution trace with a **proof layer** that pairs editorial
intent (from `FedBlock`) with actual execution (from `BlockPlaybackSummary`) and
renders a WANTED/SHOWED/VERDICT comparison per block.

### Design

At each block fence, the engine:
1. Extracts **intent** from the active `FedBlock` (asset URIs, duration, expected frames)
2. Pairs it with the **actual** `BlockPlaybackSummary` from the accumulator
3. Determines a **verdict** by comparing the two
4. Emits a `BlockPlaybackProof` via the `on_playback_proof` callback

### BlockPlaybackIntent

| Field | Type | Description |
|-------|------|-------------|
| `block_id` | string | Block identity |
| `expected_asset_uris` | vector | Asset URIs from FedBlock segments |
| `expected_duration_ms` | int64 | end_utc_ms - start_utc_ms |
| `expected_frames` | int64 | ceil(duration / frame_duration) |
| `expected_start_offset_ms` | int64 | First segment's asset_start_offset_ms |

### PlaybackProofVerdict

| Verdict | Meaning |
|---------|---------|
| `FAITHFUL` | Correct asset(s), zero pad frames |
| `PARTIAL_PAD` | Correct asset(s), some pad frames |
| `ALL_PAD` | No real frames emitted (decoder never produced output) |
| `ASSET_MISMATCH` | Observed asset URI not in expected set |

### Log Format

```
[CONTINUOUS-PLAYBACK-PROOF] block_id=...
  WANTED: asset=/foo.mp4 offset=0ms duration=5000ms frames=152
  SHOWED: asset=/foo.mp4 range=0-4950ms frames=152 pad=0
  VERDICT: FAITHFUL
```

### Engine Callback (P3.3b)

| Callback | Description |
|----------|-------------|
| `on_playback_proof` | Optional. Fired at fence, after `on_block_summary`. |

### Contract Tests (PlaybackTraceContractTests.cpp — P3.3b)

| Test ID | Description |
|---------|-------------|
| PROOF-001 | ProofEmittedPerBlock — one proof per completed block |
| PROOF-002 | AllPadVerdictForSyntheticBlock — unresolvable asset yields ALL_PAD |
| PROOF-003 | IntentMatchesFedBlock — BuildIntent extracts correct fields |
| PROOF-004 | DetermineVerdictLogic — all four verdict paths covered |
| PROOF-005 | FormatPlaybackProofOutput — format contains WANTED/SHOWED/VERDICT |
| PROOF-006 | ProofWantedFramesMatchesFence — wanted frames == showed frames |
| PROOF-007 | RealMediaFaithfulVerdict — GTEST_SKIP if assets missing |
