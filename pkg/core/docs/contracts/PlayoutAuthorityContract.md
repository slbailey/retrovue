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
legacy `Phase8AirProducer` (LoadPreview/SwitchToLive) is retained for
reference but blocked from execution.

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
| `Phase8AirProducer` | Retained, blocked | `start()` raises `RuntimeError` |
| `LoadPreview` / `SwitchToLive` | Retained in gRPC | Not invoked by BlockPlan path |
| `NormalProducer` | Stub, unused | No guardrail needed |
| `EmergencyProducer` | Stub, unused | No guardrail needed |
| `GuideProducer` | Stub, unused | No guardrail needed |

Legacy code is not deleted.  It is frozen and guarded to prevent
accidental invocation.  Future cleanup may remove it once the BlockPlan
path has sufficient operational history.

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
