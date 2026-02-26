# RetroVue AIR System Invariants

**Status:** Active Consolidated Reference  
**Date:** 2026-02-23  
**Purpose:** Single authoritative document for all system invariants

This document consolidates all INV-* invariant files from the RetroVue AIR codebase.
Individual INV-* files have been archived; this is the canonical reference.

---

## Table of Contents

1. [Coordination Layer Invariants](#coordination-layer-invariants)
2. [Semantic Layer Invariants](#semantic-layer-invariants)
3. [Execution Layer Invariants](#execution-layer-invariants)
4. [Broadcast-Grade Guarantees](#broadcast-grade-guarantees)

---

## Coordination Layer Invariants

### INV-BLOCK-WALLCLOCK-FENCE-001: Deterministic Block Fence from Rational Timebase

**Owner:** PipelineManager  
**Depends on:** INV-TICK-GUARANTEED-OUTPUT, LAW-OUTPUT-LIVENESS

Block transitions in a BlockPlan session MUST be driven by a precomputed fence tick derived from the block's UTC schedule and the session's rational output frame rate. The fence tick is an absolute session frame index, computed once at block-load time and immutable thereafter.

**Canonical Fence Formula:**
```
delta_ms   = end_utc_ms - session_epoch_utc_ms
fence_tick = (delta_ms * fps_num + fps_den * 1000 - 1) / (fps_den * 1000)
```

**Fence Tick Swap Semantics (INV-BLOCK-WALLFENCE-004):**

The fence tick is an absolute session frame index representing the first tick of block B.

**Ownership Rule:**
- Ticks `[0, fence_tick - 1]`: Block A owns frame emission, budget, and attribution
- Ticks `[fence_tick, ∞)`: Block B owns frame emission, budget, and attribution

**Swap Condition MUST:**
- Evaluate `session_frame_index >= fence_tick` before frame source selection
- Use snapshot of session_frame_index (no mid-tick increment)
- Treat `session_frame_index = fence_tick` as first tick of B (inclusive lower bound)

**B Not Ready at Fence Tick MUST:**
- NOT delay swap (fence is immutable)
- Emit fallback (freeze A's last committed frame OR pad)
- Attribute fallback to Block B with metadata:
  - `block_id = B.block_id`
  - `segment_uuid = null`
  - `asset_uuid = null`
  - `segment_type = PAD` or `FALLBACK`
  - `is_pad = true`
- Decrement B's `remaining_block_frames`

**Fence Immutability MUST:**
- Compute fence_tick once at block load: `fence_tick = (delta_ms * fps_num + fps_den * 1000 - 1) / (fps_den * 1000)`
- NEVER recompute based on decode latency, buffer state, or runtime conditions
- NEVER adjust for B readiness (fallback allowed)

**Non-Timing Consequences:**
- `BlockCompleted(A)` emitted after A's last frame output (consequence, not gate)
- Content time, decoder EOF, runtime clock reads: NEVER timing authority for fence
- B readiness does NOT influence fence value (priming is latency optimization only)


**Fence Swap Atomic Sequencing:**

When `session_frame_index >= fence_tick`, the following outcomes MUST be achieved atomically:

**MUST:**
1. **Ownership Snapshot:** Determine active owner for this tick (A or B) based on fence comparison
2. **Source Selection:** Select frame source from active owner's buffers
3. **Frame Emission:** Emit exactly one frame attributed to active owner
4. **Budget Accounting:** Decrement active owner's budget (if owner exists)
5. **Index Advancement:** Increment `session_frame_index` atomically with budget decrement
6. **Ownership Transition:** When B becomes active owner (at or after fence), `BlockStarted(B)` MUST be emitted exactly once

**MUST NOT:**
- Use session_frame_index value that changes mid-tick (snapshot required)
- Decrement budget of non-active block
- Skip frame emission for any tick
- Emit BlockStarted multiple times for same block
- Delay fence evaluation based on B readiness

**Observable Invariants:**
- At tick N where `N >= fence_tick`: active owner = B
- At tick N where `N < fence_tick`: active owner = A
- **Active owner is defined solely by** `session_frame_index >= fence_tick` (not by B's load completion). Thus in the fallback fence path (sync drain: pop, AssignBlock, install B), B is already active owner for that tick; emitting BlockStarted(B) during that tick is correct.
- Budget decremented for active owner only
- BlockStarted(B) emitted between tick where `N = fence_tick` and `N = fence_tick + 1`

---

### INV-BLOCK-FRAME-BUDGET-AUTHORITY: Frame Budget as Counting Authority

**Owner:** PipelineManager / TickProducer  
**Depends on:** INV-BLOCK-WALLFENCE-001

The block frame budget MUST be computed as:
```
remaining_block_frames = fence_tick - block_start_tick
```

**Stale Block Handling:**

If block is stale (`end_utc_ms <= now_utc_ms` or computed `fence_tick <= session_frame_index`):

**MUST:**
- NOT fatal (preserve output continuity)
- NOT emit that stale block's content
- Advance to next block whose `fence_tick` is in the future
- Log VIOLATION with diagnostic details (block_id, end_utc_ms, session_epoch, fence_tick, session_frame_index)

**Recovery Outcome:**
System continues with next valid block or emits fallback (freeze/pad) until valid block available.

**NON-NORMATIVE GUIDANCE (Implementation Options):**

Recommended: Option A (skip) for normal operation, Option B (clamp) for JIP.

**Core Input Contract (non-enforced):**
Core SHOULD never feed blocks with `end_utc_ms <= session_epoch_utc_ms + (session_frame_index * fps_den * 1000 / fps_num)`. PipelineManager handles violations defensively.

**Key Rules:**
**Key Rules:**

1. **Budget is Counting Authority ONLY:** Counts frames emitted; does NOT determine block duration

2. **Budget Formula:** `remaining_block_frames = fence_tick - session_frame_index`

3. **Decrement Rule:** One frame emitted = one decrement (includes freeze/pad/black frames)

4. **Budget Zero at Fence (Normal):** By construction, `remaining_block_frames = 0` when `session_frame_index = fence_tick`

5. **Budget Non-Zero at Fence (VIOLATION):**
   - **Detection:** `remaining_block_frames != 0` when `session_frame_index >= fence_tick`
   - **Handling:** Log VIOLATION, force swap (fence wins), recompute budget for new block
   - **Recovery:** `new_block.remaining_block_frames = new_block.fence_tick - session_frame_index`
   - **Non-Fatal:** Budget mismatch does NOT halt output (fence is timing authority)

6. **Budget Does Not Gate Output:** System emits frames regardless of budget value

7. **Budget Diagnostic:** Budget convergence verification; mismatch indicates accounting error, not timing error

**Budget Initialization Invariants:**

When a block becomes active owner at tick N, the following MUST be true:

**State Invariants:**
- Block's `fence_tick` is immutable (computed once, never recomputed)
- Block's initial `remaining_block_frames = fence_tick - N` (where N = `session_frame_index` when block becomes active)
- Budget MUST be positive: `remaining_block_frames > 0` at initialization
- Budget MUST be initialized before any decrement occurs for ticks where this block is active owner

**Per-Tick Invariants:**
- Budget decrements if and only if block is active owner for that tick
- Budget never decrements for block that is not active owner
- Budget and index update atomically (no partial state)

**Convergence Invariant:**
- At all times: `remaining_block_frames = fence_tick - session_frame_index` (for active block)
- At fence tick: `remaining_block_frames = 0` exactly

**Off-By-One Prevention:**
Budget mismatch at fence indicates violation of initialization or atomicity → recovery per Finding 1.2 (fence wins, recompute budget).

**Contract test:** `pkg/air/tests/contracts/test_block_frame_budget.py` — existing tests enforce budget formula and convergence (INV-FRAME-BUDGET-002, INV-FRAME-BUDGET-003).

**NON-NORMATIVE EXPLANATION (Off-By-One Prevention Table):**

| Event | session_frame_index | remaining_block_frames | Notes |
|-------|---------------------|------------------------|-------|
| Block assigned | N | fence_tick - N | Initialization |
| First frame emit | N | fence_tick - N | Before decrement |
| After first emit | N+1 | fence_tick - (N+1) | After decrement + index increment |
| ... | ... | ... | Invariant holds |
| Last frame emit | fence_tick - 1 | 1 | Before decrement |
| After last emit | fence_tick | 0 | Budget exhausted |
| Swap check | fence_tick | 0 | `>= fence_tick` → swap |

**Budget Convergence Proof (Mathematical):**

**Invariant Identity:**


**Proof of Exact Convergence:**

**Given:**
- `fence_tick`: Immutable absolute session frame index (integer, ≥ 0)
- `session_frame_index(0)`: Initial session frame index when block assigned (integer, ≥ 0)
- `remaining_block_frames(0) = fence_tick - session_frame_index(0)`: Initial budget

**Per-Tick Update Rules:**


**Proof by Induction:**

**Base case (t=0):**

The identity holds at initialization.

**Inductive hypothesis:**
Assume `remaining_block_frames(t) = fence_tick - session_frame_index(t)` holds at tick t.

**Inductive step:**
Prove the identity holds at tick t+1:



**Conclusion:**
The identity `remaining_block_frames(t) = fence_tick - session_frame_index(t)` holds for all t ≥ 0 by mathematical induction.

**Fence Tick Convergence:**

At the tick where `session_frame_index = fence_tick`:


**Off-By-One Impossibility:**

Budget can NEVER be -1, +1, or any value other than 0 at fence because:

1. **Atomic Updates:** Decrement and index increment are atomic per tick
2. **Consistent Initial State:** Budget initialized as `fence_tick - session_frame_index(0)`
3. **Synchronous Advancement:** Both advance by exactly 1 per tick (no drift, no skip)
4. **No External Modification:** No other code path modifies budget or index
5. **Fence Immutable:** `fence_tick` never changes after initialization

**Failure Modes (all prevented):**
- Budget = -1 at fence: Impossible (would require decrement without index increment → violates atomicity)
- Budget = +1 at fence: Impossible (would require index increment without decrement → violates atomicity)
- Budget != 0 at fence: Indicates violation of initialization or atomicity → handled per Finding 1.2 (recovery, not fatal)

**Diagnostic Use:**
If `remaining_block_frames != 0` when `session_frame_index >= fence_tick`:
- Log VIOLATION (initialization error, atomicity bug, or accounting drift)
- Force swap (fence wins)
- Recompute budget for new block (defensive recovery)
- Continue output (non-fatal per Finding 1.2)
---

### INV-BLOCK-LOOKAHEAD-PRIMING: Look-Ahead Priming at Block Boundaries

The first video frame and its audio MUST be decoded and buffered before the producer signals readiness. Priming is a latency mitigation technique; it does NOT affect fence timing, cadence computation, or block duration.

**Key Rules:**

1. **Latency Authority ONLY:** Priming reduces decode latency; does NOT influence timing or counting

2. **Decoder Ready Before Fence:** First frame decoded and buffered before `session_frame_index >= fence_tick`

3. **Zero Deadline Work:** At fence tick, frame retrieved from memory (no decode syscall in critical path)

4. **No Fence Influence:** Priming failure does NOT delay fence; fence fires at precomputed tick regardless

5. **Consume Primed Frame Exactly Once:** First pop after fence consumes primed frame; subsequent pops from live decode

6. **Fallback on Priming Failure:** If priming incomplete at fence, system falls through to:
   - Live decode (if decode fast enough)
   - Freeze (previous block's last frame)
   - Pad (black + silence)

**MUST NOT:**
- Delay fence tick based on priming state
- Recompute cadence based on primed frame properties
- Skip fence if priming incomplete
---

### INV-LOOKAHEAD-BUFFER-AUTHORITY: Lookahead Buffer Decode Authority

**Owner:** PipelineManager, VideoLookaheadBuffer, AudioLookaheadBuffer  

AIR MUST decouple all decode operations from the tick emission thread. Decode runs on dedicated background fill threads.

**Video Lookahead Rules:**
- Tick thread MUST NOT call decode APIs after fill thread starts
- Fill thread maintains target depth; waits on condition variable when full
- `TryPopFrame()` returns false on underflow; NEVER injects substitute data
- Fence transitions: StopFilling(flush), StartFilling(consume primed frame)

**Audio Lookahead Rules:**
- Audio decode is side-effect of video decode (FrameData contains audio)
- `TryPopSamples()` returns false on insufficient samples
- No silence injection by the buffer itself
- Audio buffer NOT flushed at fence (preserves continuity)

---

### INV-FENCE-FALLBACK-SYNC-001: Mandatory Synchronous Queue Drain at Fence

**Owner:** PipelineManager  
**Depends on:** OUT-BLOCK-005, INV-BLOCK-WALLFENCE-001, INV-RUNWAY-MIN-001

**Fence Tick Fallback Ownership:**

When `session_frame_index >= fence_tick`:

1. **Ownership:** Block B owns all frames at `fence_tick` and beyond, regardless of readiness

2. **B Not Ready, Queue Non-Empty:**
   - Pop block from queue (synchronous, no async preload)
   - Emit `BlockStarted` event (credit to Core)
   - Call `AssignBlock()` (synchronous load, may take >1 tick)
   - Install as live producer in slot B
   - Start buffer filling (async, background thread)
   - If still not ready after load: emit fallback attributed to B

3. **B Not Ready, Queue Empty:**
   - Emit fallback (freeze A's last committed frame OR pad)
   - Attribution: `block_id = B.block_id` (or null if B slot empty)
   - Budget: B's `remaining_block_frames` decrements (if B exists)

4. **Fallback Frame Metadata:**
   - `block_id`: B's block_id (or null if B slot empty)
   - `segment_uuid`: null (fallback has no segment identity)
   - `asset_uuid`: null (fallback has no asset)
   - `segment_type`: PAD or FALLBACK
   - `is_pad`: true

**Synchronous Queue Drain MUST:**
- Occur within tick deadline budget (pop + load + install)
- NOT delay subsequent ticks (late tick still emits fallback)
- NOT skip fence comparison (fence always evaluates)

**Unconditional Path:** Queue drain is unconditional (no feature flag, no config gate).
---

### INV-FENCE-TAKE-READY-001: Fence Take Readiness and DEGRADED_TAKE_MODE

**Owner:** PipelineManager  
**Layer:** Coordination / Broadcast-grade take

At fence tick, if next block's first segment is CONTENT, system must satisfy:
1. Preview buffer primed to threshold, OR
2. DEGRADED_TAKE_MODE active (hold last committed A frame + silence)

**DEGRADED_TAKE_MODE:**
- Video: hold last committed A frame
- Audio: silence
- Ticks continue normally (no skip)
- Exit when B primed and pop succeeds
- After HOLD_MAX_MS (5s), escalate to standby (pad/slate)

**Contract test:** `pkg/air/tests/contracts/BlockPlan/DegradedTakeModeContractTests.cpp` — existing tests enforce fence take readiness and DEGRADED_TAKE_MODE.

---

### INV-PREROLL-OWNERSHIP-AUTHORITY: Preroll Arming and Fence Swap Coherence

**Owner:** PipelineManager  
**Depends on:** INV-BLOCK-WALLFENCE-001, INV-BLOCK-LOOKAHEAD-PRIMING

Preroll arming authority MUST align with "next block" authority that fence swap uses. The committed successor block is the block in the B slot at TAKE time.

**Key Rules:**
- Committed successor = single source of truth for "which block is next"
- Set when preloaded result taken into preview slot (TakeBlockResult)
- NOT set when block popped from queue and submitted to preloader
- Fail closed on mismatch: log violation, continue with correct session block

---

### INV-DETERMINISTIC-UNDERFLOW-AND-TICK-OBSERVABILITY: Underflow Policy and Tick Lateness

**Owner:** PipelineManager, VideoLookaheadBuffer  
**Depends on:** INV-LOOKAHEAD-BUFFER-AUTHORITY, INV-TICK-DEADLINE-DISCIPLINE-001

When lookahead buffer cannot supply a frame, system MUST behave deterministically: emit freeze/pad using deterministic policy. Underflow is controlled state transition with enriched observability.

**Key Rules:**
- Deterministic underflow behavior (freeze or PADDED_GAP, no random stall spiral)
- Enriched underflow log includes: low_water, target, depth_at_event, lateness_ms
- Tick lateness observable (per-tick deadline/start/end, lateness_ms, p95/p99 metrics)
- No nondeterministic sleeps in underflow path

---

### INV-P10-PIPELINE-FLOW-CONTROL

**Owner:** All Producers, PipelineManager, VideoLookaheadBuffer, AudioLookaheadBuffer  
**Status:** IMPLEMENTED

**Cardinal Rule (DOCTRINE):**
> "Slot-based flow control eliminates sawtooth stuttering.  
> Hysteresis with low-water drain is the pattern that causes bursty delivery."

**Core Requirements:**
1. **Realtime throughput:** Output matches target FPS ± 1%; no cumulative drift
2. **Symmetric backpressure:** Audio and video throttled together
3. **Slot-based decode gate:** Block at capacity, unblock when one slot frees (no hysteresis)
4. **Producer throttle:** Decode rate governed by consumer capacity
5. **Frame drop policy:** Drops forbidden unless explicit conditions met
6. **Buffer equilibrium:** Depth oscillates around target, not unbounded growth

**Producer Contract:**
- Flow control gate BEFORE packet read/frame generation
- Backpressure symmetric in time-equivalent units
- No hidden queues between decode and push
- Video through TimelineController; audio uses sample clock
- Muxer uses producer-provided CT (no local CT counters)
- PCR-paced mux (time-driven, not availability-driven)
- No silence injection once PCR pacing starts
- Frame-indexed execution (not time-based)

---

## Semantic Layer Invariants

### Time Concepts (AIR): media_ct_ms vs Tick Grid Time

AIR uses two distinct time concepts. They MUST NOT be conflated.

**media_ct_ms (Media Content Time):**
- **Definition:** "How far into the current segment's content we are," in milliseconds.
- **Source:** Derived from the decoded frame PTS (or best-effort timestamp), rescaled to milliseconds and normalized to the segment start.
- **Canonical form:** media_ct_ms = floor(rescale_q(frame_pts, time_base, ms)) - media_origin_ms. PTS time_base is stream-specific (MPEG-TS, MP4, MKV, and FFmpeg stream time_base all vary); the invariant remains structurally true for arbitrary time_base. Implementations that currently receive PTS in µs use the special case time_base = 1/1000000.
- **Use:** Exhaustion detection, content progress, diagnostics ("we are 12.3s into the ad").

**Tick grid time (tick_time_us, tick_ct_ms):**
- **Definition:** The output session's emission grid time derived from output tick index and session RationalFps.
- **Use:** Emission schedule, fences, budgets, output PTS, mux pacing, and all "when do we emit" decisions.

**Hard rule (MUST):**
- media_ct_ms MUST be derived from decoder PTS (or best-effort timestamp).
- media_ct_ms MUST NOT be computed from output FPS, output frame index, or any tick-grid function.

**NON-NORMATIVE WHY:**  
Output FPS and tick index define when we emit frames. They do not define where we are in the source media. DROP / CADENCE / repeat decisions must not redefine content position.

---

### INV-AIR-MEDIA-TIME: Media Time Authority Contract

**Owner:** TickProducer  
**Depends on:** Time Concepts (AIR), INV-BLOCK-WALLCLOCK-FENCE-001, INV-FPS-TICK-PTS

Block execution and segment transitions MUST be governed by decoded media time (media_ct_ms), not by output cadence, guessed frame durations, or rounded FPS math.

**Media time derivation (MUST):**
1. media_ct_ms MUST be derived from decoder PTS (or best-effort timestamp), rescaled to ms and normalized to segment start.
2. media_ct_ms MUST NOT be computed from output FPS, output frame index, or tick-grid time (tick_time_us, tick_ct_ms).

**Cadence independence (MUST):**
3. DROP / CADENCE / repeats determine which decoded frame is shown on a tick; they do NOT define media time.
4. media_ct_ms for an emitted content frame MUST equal the chosen frame's decoded PTS-derived time (normalized).
5. On repeat / hold / fallback (same frame emitted again or synthetic frame), media_ct_ms MUST NOT advance.

**Core rules:**
6. **Fence is timing authority:** Block ownership and swaps are determined solely by fence_tick on the tick grid (INV-BLOCK-WALLCLOCK-FENCE-001). media_ct_ms MUST NOT influence fence timing.
7. **Exhaustion uses media_ct_ms:** Content exhaustion and "how far into content" decisions MUST use media_ct_ms derived from decoded PTS, not tick-grid time.
8. **Fence before exhaustion (allowed truncation):** Fence swap occurs at precomputed fence_tick; remaining content may be truncated. Diagnostic quality issue only.
9. **Exhaustion before fence (allowed padding):** If content exhausts before fence, system emits fallback (freeze/pad) until fence fires. Attribution remains with current active block until fence.
10. **No cumulative media-time drift (diagnostic):** Media-time reported via media_ct_ms MUST remain consistent with decoded PTS to within an epsilon bounded by one output tick window under normal operation.

**Authority precedence:**
- Fence / tick grid time controls when ownership changes and when frames are emitted.
- media_ct_ms controls content position and exhaustion only; it MUST NOT control fence timing or output PTS.

**Guardrail (diagnostic):**
- When the decoder reports EOF, if media_ct_ms is less than 80% of the current segment's probed duration, the implementation MUST log a VIOLATION under INV-AIR-MEDIA-TIME. This signature catches "CT derived from output fps / frame index" bugs (e.g. early segment exhaustion / "half duration" symptoms).

---

### INV-FPS-RATIONAL-001: Rational FPS as Single Authoritative Timebase

**Status:** Broadcast-grade invariant

RationalFps is the ONLY authoritative representation of frame rate in the playout pipeline. Floating-point arithmetic is FORBIDDEN in any timing or scheduling path.

**Hard Rules:**
1. **Canonical Rational:** All FPS stored as irreducible `(num, den)` pairs
2. **No Floating-Point Timing:** No float/double in: DROP detection, cadence, frame duration, fence, budget, tick scheduling
3. **Integer Arithmetic:** Use 64-bit minimum; `__int128` for cross-multiplication
4. **Output FPS Rational:** Channel output FPS stored/transported as rational end-to-end
5. **Cadence Integer-Based:** No floating accumulators
6. **Tick Grid Authority:** Session tick grid derives from RationalFps only

**Forbidden Patterns:**
- `double fps`, `float fps`
- `1.0 / fps`
- `ceil(delta_ms / FrameDurationMs())` (use canonical helpers)
- Tolerance comparisons (`abs(a - b) < 0.001`)
- `ToDouble()` in hot paths
- Any floating literal in hot-path code (`1.0`, `1e6`, `1000.0`)

**Contract tests:** `pkg/air/tests/contracts/BlockPlan/MediaTimeContractTests.cpp`; `pkg/air/tests/contracts/test_inv_fps_resample_drift.cpp` — existing tests enforce rational FPS and timebase.

---

### INV-FPS-MAPPING: Source→Output Frame Authority

**Owner:** TickProducer, VideoLookaheadBuffer  
**Related:** INV-FPS-RESAMPLE, INV-FPS-TICK-PTS

For any segment where `input_fps ≠ output_fps`, engine MUST select source frames using exactly one of: OFF, DROP, or CADENCE. Mode MUST be determined by rational comparison only.

**Required Mappings:**
- 30→30: OFF (equality)
- 60→30: DROP (step=2)
- 120→30: DROP (step=4)
- 23.976→30: CADENCE (non-integer ratio)

**DROP Duration Invariant:** Returned output frame duration = output tick duration (1/output_fps), NOT input frame duration.

**DROP Audio:** All `step` input frames must contribute decoded audio. Audio production MUST NOT be reduced in DROP mode.

**Rational Detection:**
```
if (in_num * out_den == out_num * in_den) → OFF
else if ((in_num * out_den) % (out_num * in_den) == 0) → DROP
else → CADENCE
```

**Contract tests:** `pkg/air/tests/contracts/BlockPlan/MediaTimeContractTests.cpp` (INV-FPS-MAPPING, INV-FPS-TICK-PTS); `pkg/air/tests/contracts/test_inv_fps_resample_drift.cpp` — existing tests enforce source→output frame authority.

---

### INV-FPS-RESAMPLE: FPS Resample Authority Contract

**Owner:** TickProducer, OutputClock, PipelineManager  
**Related:** Time Concepts (AIR), INV-AIR-MEDIA-TIME, INV-FPS-TICK-PTS  
**Status:** Broadcast-grade invariant

**Preamble (MUST):**  
Media time MUST NOT be defined from output FPS, output frame index, or tick-grid functions.

**Tick grid time (authoritative for emission)**

**Output tick time:**
- tick_time_us(n) = floor(n * 1_000_000 * fps_den / fps_num)

**Tick CT (grid diagnostic / convenience only):**
- tick_ct_ms(n) = floor(n * 1000 * fps_den / fps_num)

**Hard rule:** Tick grid time is NOT media time. It MUST NOT be used to represent "how far into content" or to drive exhaustion.

**Media time (authoritative for content position)**

**Media CT definition (MUST):**
- media_ct_ms = floor(rescale_q(frame_pts, time_base, ms)) - media_origin_ms

Where:
- frame_pts is the decoded frame PTS (or best-effort timestamp)
- time_base is the decoder/stream time base for that PTS
- media_origin_ms is the normalized segment start time (e.g., first chosen frame's PTS-derived ms)

**Hard rules:**
- media_ct_ms MUST be derived from decoded PTS (or best-effort timestamp).
- media_ct_ms MUST NOT be computed from output frame index, output FPS, tick_time_us, or tick_ct_ms.

**Resample rule (unchanged principle):**
- For output tick n, choose the source frame covering tick_time_us(n) (selection rule).
- Output video PTS = tick-grid time (INV-FPS-TICK-PTS), NOT source PTS.
- media_ct_ms for the emitted content frame is taken from the chosen frame's decoded PTS, not from n.

**Outlawed patterns (expanded)**

The following are FORBIDDEN for media time (media_ct_ms) computation:
- media_ct_ms = floor(k * 1000 * fps_den / fps_num) where k is output frame index or any tick counter
- any function of output FPS or output frame index used as media/content time
- accumulated approximations such as media_ct_ms += frame_duration_ms or media_ct_ms += interval_us
- any float/double timing in media time derivation

**NON-NORMATIVE WHY:**  
Exhaustion and "how far into content" must reflect decoded content. Output FPS and tick index vary by channel and emission policy; DROP/CADENCE must not redefine content position.

---

### INV-FPS-TICK-PTS: Output PTS Owned by Tick Grid

**Owner:** TickProducer, PipelineManager

In all modes (OFF, DROP, CADENCE), output video PTS MUST advance by exactly one output tick per returned frame.

**Key Rules:**
- Each returned frame has video.metadata.pts = output tick PTS for that frame index
- PTS delta = tick duration (NOT input frame duration in DROP)
- Muxer uses OutputClock::FrameIndexToPts90k (not returned frame metadata.pts for pacing)
- In DROP: TickProducer overwrites decoder PTS with output tick PTS before return

---

### INV-AUDIO-PTS-HOUSE-CLOCK-001: Audio PTS Owned by House Sample Clock

**Owner:** PipelineManager, MpegTSOutputSink, EncoderPipeline  
**Depends on:** Clock Law (Layer 0), LAW-OUTPUT-LIVENESS, INV-FPS-TICK-PTS  
**Related:** INV-AUDIO-LIVENESS (audio servicing; this invariant governs PTS source only)  
**Status:** Active

Audio PTS used for encoding and transport MUST be derived from the session's **house sample clock**, not from decoder/content PTS.

**Core Rule:**
- Audio encode PTS is a pure function of **samples emitted**, anchored to an origin:

  `audio_pts_90k = floor((audio_samples_emitted - origin_audio_samples) * 90000 / house_sample_rate)`

- `house_sample_rate` is the channel house audio sample rate (e.g., 48 kHz).

**Hard Rules:**
1. **Single authority:** No output path may use `AudioFrame.pts_us` (or any decoder/container PTS) as the transport PTS.
2. **Monotonicity:** Audio PTS MUST be strictly increasing for successive encoded audio frames that contain samples. Zero-sample frames MUST NOT be encoded.
3. **Alignment:** The audio sample-clock origin MUST be aligned to the session epoch used by video PTS derivation. Audio and video PTS MUST converge to the same transport timeline.
4. **Resample-safe:** DROP/CADENCE and segment seams MUST NOT change audio PTS authority or pacing.
5. **Diagnostic-only content PTS:** Decoder/content PTS may be retained for observability only; it MUST NOT affect mux timing.

**Why:** Decoder/content PTS is not stable under resample, truncation, pad insertion, fence swaps, and segment seams. Using it as transport timing creates dual-clock drift, PCR instability, stutter, and perceived slow-motion under mixed-FPS content.

**What this invariant forces:** MpegTSOutputSink MUST NOT use `audio_frame.pts_us` as encode PTS. Both output paths (PipelineManager and MpegTSOutputSink) MUST use the same house sample-clock timing model. This invariant ensures deterministic audio timing across all output paths and resample modes.

---

### INV-AIR-SEGMENT-IDENTITY-AUTHORITY: UUID-Based Segment Identity

**Owner:** PipelineManager / EvidenceEmitter / AsRunReconciler  

Segment identity MUST be carried by UUID assigned at block feed time. `segment_index` is display-order only and MUST NOT be used as identity key.

**Key Rules:**
1. Segment UUID is execution identity (assigned at block feed, immutable)
2. Asset UUID explicit for CONTENT/FILLER; null for PAD
3. Reporting is UUID-driven (no positional lookup fallback)
4. JIP does not change identity (UUID/asset unchanged; index may change)
5. Event completeness (every SEG_START/AIRED has block_id, segment_uuid, segment_type, asset_uuid)

**Forbidden:** `segments[segment_index]` as identity, DB index lookup, adjacency inference.

---

### INV-AUDIO-LIVENESS: Audio Servicing Decoupled From Video Backpressure

**Owner:** FileProducer, VideoLookaheadBuffer, AudioLookaheadBuffer

**INV-AUDIO-LIVENESS-001:**  
During CONTENT playback with audio enabled, video queue backpressure MUST NOT prevent ongoing audio servicing.

Video saturation may block video enqueues but MUST NOT halt:
- Demux servicing for audio packets
- Audio decoder draining
- Audio frame production

**INV-AUDIO-LIVENESS-002:**  
AUDIO_UNDERFLOW_SILENCE is transitional, NOT steady-state. Continuous silence injection across sustained CONTENT playback indicates liveness violation.

**Contract tests:** `pkg/air/tests/contracts/BlockPlan/LookaheadBufferContractTests.cpp` (INV_AUDIO_LIVENESS_001_AudioServicedWhenVideoFull); `pkg/air/tests/contracts/BlockPlan/P6_AudioLivenessNotBlockedByVideoBackpressure.cpp` — existing tests enforce INV-AUDIO-LIVENESS-001.

---

### INV-AUDIO-PRIME-002: Prime Frame Must Carry Audio

**Owner:** TickProducer, VideoLookaheadBuffer

If asset has audio stream, after PrimeFirstTick completes, the first frame (primed frame) MUST include at least one audio packet, or system must not treat buffer as ready until audio present.

Prevents "primed video but audio_count=0" false-ready condition that causes AUDIO_UNDERFLOW_SILENCE at cold start.

---

### INV-SEAM-AUDIO-GATE: Segment Seam Audio Gating

**Scope:** Segment seam transition when `take_segment=true` before `SEGMENT_TAKE_COMMIT`

**INV-SEAM-AUDIO-001:**  
Tick loop MUST NOT consume from Segment-B audio buffer until `SEGMENT_TAKE_COMMIT` succeeds.

**INV-SEAM-GATE-001:**  
Gate measurements taken on buffer not being drained by live consumer unless commit occurred.

**Contract tests:** `pkg/air/tests/contracts/BlockPlan/SeamContinuityEngineContractTests.cpp`; `pkg/air/tests/contracts/BlockPlan/SegmentSeamRaceConditionFixTests.cpp` — existing tests enforce INV-SEAM-AUDIO-001 (tick loop does not consume Segment-B audio until commit).

---

### INV-SEG-SWAP-001: PerformSegmentSwap Requires Live A Armed

**Owner:** PipelineManager  
**Classification:** CONTRACT (broadcast-grade)

Segment seam take MUST only be scheduled/executed when live A is armed: `video_buffer_ && audio_buffer_ && live_`. Otherwise treat as startup / pad-only / degraded: the tick loop keeps emitting pad/freeze, but seam orchestration MUST NOT run and segment index MUST NOT advance.

**Enforcement:** Immediately before Step 2 (move outgoing A), if any of `video_buffer_`, `audio_buffer_`, or `live_` is null, log once with `Logger::Error` as `SEGMENT_SWAP_WITHOUT_LIVE_A` with full state dump: `tick`, `from_segment`, `to_segment`, `to_type`, `swap_reason`, `video_buffer_null`, `audio_buffer_null`, `live_null`, `block_id`, `segment_b_video`, `pad_b_video`. Then return without mutating any buffer or producer slots. Step 2 MUST be null-safe (only move and call `StopFillingAsync` when `video_buffer_` is non-null); only enqueue ReapJob when there was an outgoing buffer.

**No double-take / re-entrancy:** At most one segment swap per tick. Record `last_seam_take_tick_` when a take is committed (after the live-A gate). If `session_frame_index == last_seam_take_tick_` at entry, log `SEGMENT_SWAP_REFUSED reason=double_take_same_tick` and return. Reset `last_seam_take_tick_ = -1` on block activation (new block) so the first segment seam of the new block is allowed. This prevents catch-up thrash when lateness or rebase would otherwise allow a second take in the same tick.

**Why:** Calling `outgoing_video_buffer->StopFillingAsync()` when `video_buffer_` was null (e.g. moved out by an earlier path or seam fired before A was armed) is undefined behavior and causes SIG11. This is a coordination/state invariant bug: the seam trigger assumed "live A exists" but the state machine allows a seam event when A is not armed. Hard-gating and null-safe Step 2 give deterministic behavior and a log proving the upstream violation. Double-take can occur under lateness (rebase still allows same-tick re-entry); the guard prevents it.

---

## Execution Layer Invariants

### INV-TICK-GUARANTEED-OUTPUT: Every Tick Emits Exactly One Frame

**Owner:** MpegTSOutputSink / MuxLoop  
**Priority:** ABOVE all other invariants

**Per-Tick Execution Sequence:**

Each output tick MUST execute the following atomic sequence:

**Step 1: Source Selection**
- Evaluate fence swap condition (`session_frame_index >= fence_tick`)
- Determine active block (A or B)
- Select frame source priority: REAL → FREEZE → BLACK
- Selection MUST occur before buffer access

**Step 2: Frame Retrieval**
- REAL: Pop from video buffer (if available)
- FREEZE: Copy `last_committed_frame` (from memory)
- BLACK: Use preallocated black frame
- Retrieval is deterministic (no failure path)

**Step 3: Commitment**
- Update `last_committed_frame = retrieved_frame`
- Enables FREEZE fallback for next tick

**Step 4: Atomic State Update**
- If active block exists: `active_block->remaining_block_frames--`
- `session_frame_index++`
- Both MUST update together (no partial state)

**Step 5: Sink Handoff**
- Hand off frame to sink for muxing/emission
- Handoff is unconditional (guaranteed output)
- No success/failure semantics (sink MUST accept)

**Atomicity Guarantee:**
Steps 1-5 execute atomically per tick. No interleaving with other ticks. No failure path that skips sink handoff.

**MUST NOT:**
- Select source after buffer access (TOCTOU race)
- Skip commitment step (breaks FREEZE fallback)
- Partially update budget/index (atomic violation)
- Condition sink handoff on any check (violates guaranteed output)
- Treat sink handoff as having failure path

**NON-NORMATIVE EXAMPLE:**

**Contract tests:** `pkg/air/tests/contracts/Phase9OutputBootstrapTests.cpp`; `pkg/air/tests/contracts/PrimitiveInvariants/PacingInvariantContractTests.cpp` — existing tests enforce every tick emits exactly one frame.

---

### INV-TICK-DEADLINE-DISCIPLINE-001: Hard Deadline Discipline for Output Ticks

**Owner:** PipelineManager  
**Depends on:** INV-TICK-GUARANTEED-OUTPUT, LAW-OUTPUT-LIVENESS

Each output tick N is a hard scheduled deadline:
```
spt(N) = session_epoch_utc + N * fps_den / fps_num
```

**Requirements:**
1. One tick per frame period (no slip)
2. Late ticks MUST still emit (fallback allowed)
3. No catch-up bursts
4. Fence checks remain tick-index authoritative even when late
5. Drift-proof anchoring (slow tick does NOT shift future tick deadlines)

*Clarification:* Output emission MUST be paced to the session tick grid and MUST NOT be availability-driven or burst-driven. (This is implied by the requirements above; stated here for documentation clarity.)

---

### INV-SINK-NONBLOCKING-HANDOFF-001: Tick Thread Must Not Block on Sink I/O

**Owner:** PipelineManager / SocketSink / MpegTSOutputSink  
**Depends on:** INV-TICK-DEADLINE-DISCIPLINE-001, LAW-OUTPUT-LIVENESS

**Rule:** In continuous_output, the per-tick execution thread MUST NOT block on any sink write operation. Sink handoff must be O(1) and non-blocking (enqueue/copy only). Any blocking I/O must occur on a separate egress worker thread.

**Supports:**
- INV-TICK-DEADLINE-DISCIPLINE-001 (no tick slip from I/O stalls)
- LAW-OUTPUT-LIVENESS (relay slowness is a sink problem, not a clock problem)

**Implementation:**
- AVIO write callback only copies bytes into a bounded egress queue (byte-bounded, not chunk-bounded).
- A dedicated egress writer thread drains the queue and performs send()/write() to the socket.
- If the queue exceeds capacity: detach the sink (slow-consumer detach); session continues with output dropped (INV-SINK-LOSS-NONFATAL-001).

**MUST NOT:** Block the tick thread in the AVIO callback (e.g. waiting on buffer space). Use non-blocking enqueue only; overflow triggers detach.

---

### INV-SINK-LOSS-NONFATAL-001: Sink Loss Must Not End Session

**Owner:** PipelineManager / SocketSink / AVIO write callback  
**Depends on:** INV-SINK-NONBLOCKING-HANDOFF-001

**Rule:** Sink loss (detach, closed fd, EPIPE, buffer overflow) must NOT end the session. It only ends delivery to that sink. The tick loop MUST continue; the AVIO write callback MUST drop bytes (act as NullSink) instead of returning AVERROR(EPIPE) or otherwise causing FFmpeg/session to treat the failure as fatal.

**Implementation:**
- Detach callback MUST NOT set `stop_requested` (or otherwise cause Run() to exit).
- AVIO write callback: when sink is detached or closed, or when TryConsumeBytes fails (overflow), return `buf_size` (drop bytes); MUST NOT return AVERROR(EPIPE).
- Tick loop MUST NOT exit on `output_detached`; it continues, and subsequent writes are dropped.

**MUST NOT:** Treat detach, EPIPE, or sink full as a session-fatal condition. Session ends only on explicit StopBlockPlanSession / stop_requested from control path.

---

### INV-TICK-MONOTONIC-UTC-ANCHOR-001: Monotonic Deadline Enforcement

**Owner:** PipelineManager  
**Depends on:** Clock Law, INV-TICK-DEADLINE-DISCIPLINE-001

Tick deadlines anchored to session UTC epoch, but implemented using monotonic clock to avoid NTP step breakage.

At session start, capture:
- `session_epoch_utc_ms` (UTC wall-clock authority)
- `session_epoch_mono_ns` (monotonic anchor)

Monotonic deadline:
```
deadline_mono_ns(N) = session_epoch_mono_ns + round_rational(N * 1e9 * fps_den / fps_num)
```

Late if: `now_mono_ns >= deadline_mono_ns(N)`

---

### INV-EXECUTION-CONTINUOUS-OUTPUT-001: Continuous Output Execution Model

**Owner:** PipelineManager  

When execution_model=continuous_output, the session MUST satisfy:

1. Session runs in continuous_output
2. Tick deadlines anchored to session epoch + rational output FPS
3. No segment/block/decoder lifecycle event may shift tick schedule
4. Underflow handling may repeat/black; tick schedule remains fixed
5. Tick cadence (grid) fixed by session RationalFps; frame-selection cadence may refresh

---

### INV-FILL-THREAD-LIFECYCLE-001: Fill Thread Must Be Stopped Exactly Once Per Start

**Owner:** PipelineManager, VideoLookaheadBuffer  
**Depends on:** INV-LOOKAHEAD-BUFFER-AUTHORITY

For every `StartFilling` call:

1. **Exactly one** `StopFilling` or `StopFillingAsync` MUST occur (before or when the buffer is discarded or rotated out).
2. If `StopFillingAsync` is used, `DetachedFill.thread` MUST be joined within bounded time (e.g. via reaper or explicit join before producer/buffer destruction).
3. No fill thread may outlive its owning `VideoLookaheadBuffer` instance. The buffer destructor calls `StopFilling(false)`; any path that moves or destroys the buffer MUST ensure the fill thread has been stopped (sync or async) and any detached thread joined before the producer or other resources used by that thread are destroyed.

**MUST NOT:** Leave a fill thread running after the buffer is moved or reset without calling StopFilling/StopFillingAsync, or fail to join a detached thread indefinitely.

**Contract tests:** `pkg/air/tests/contracts/BlockPlan/LookaheadBufferContractTests.cpp` (lifecycle, fill thread stop/join); `pkg/air/tests/contracts/test_block_lookahead_priming.py` — existing tests enforce this invariant.

---

### INV-BUFFER-INSTANCE-SINGULARITY: One Active Fill Thread Per Logical Slot

**Owner:** PipelineManager  
**Depends on:** INV-FILL-THREAD-LIFECYCLE-001

At any time:

1. At most one active fill thread per logical buffer slot (A, B, preview). No slot may have two buffers each running a fill thread.
2. No buffer instance may exist unreachable (e.g. moved out, replaced, or orphaned) while still running a fill thread. Once a buffer is no longer the active slot (e.g. after B→A rotation or teardown), its fill thread MUST have been stopped before or as part of that transition.

**MUST NOT:** Retain a pointer or ownership of a VideoLookaheadBuffer that is not the current slot and still has `IsFilling() == true` without that thread being in the process of stopping or already handed off for join.

---

### INV-FILL-THREAD-LIFECYCLE-001: Fill Thread Lifecycle Authority (Stabilization)

**Owner:** VideoLookaheadBuffer, PipelineManager  
**Purpose:** Hard lifecycle guards and violation logging for fill thread audit.

For every call to `VideoLookaheadBuffer::StartFilling()`:

- **Exactly one** of the following MUST occur:
  - `StopFilling()`, or
  - `StopFillingAsync()` followed by a guaranteed join of the returned thread.
- No fill thread may outlive its owning `VideoLookaheadBuffer` instance.
- A buffer MUST NOT call `StartFilling()` if `fill_running_ == true`.
- When a buffer is destroyed, `fill_running_` MUST be false.

**Violation:** Log `FILL_THREAD_LIFECYCLE_VIOLATION` with reason and `this` pointer.

**Contract tests:** (same as above) `pkg/air/tests/contracts/BlockPlan/LookaheadBufferContractTests.cpp`; `pkg/air/tests/contracts/test_block_lookahead_priming.py` — existing tests enforce fill thread lifecycle authority.

---

### INV-BUFFER-INSTANCE-SINGULARITY-001: At Most One Active Fill Per Slot (Stabilization)

**Owner:** PipelineManager, VideoLookaheadBuffer  
**Purpose:** Hard guards for buffer instance and fill thread cardinality.

At any time:

- There MUST be at most one active fill thread per logical slot (A, B, preview).
- A buffer instance must not become unreachable while `fill_running_ == true`.

**Violation:** Log `BUFFER_INSTANCE_ORPHANED`.

---

### INV-BOUNDED-MEMORY-GROWTH: Buffer Depths and RSS Must Converge

**Owner:** VideoLookaheadBuffer, AudioLookaheadBuffer, PipelineManager  
**Depends on:** INV-P10-PIPELINE-FLOW-CONTROL, INV-VIDEO-BOUNDED (hard cap)

Under steady state:

1. Sum of all buffer depths (video + audio, across all active slots) MUST converge. Depth may oscillate within bounds but MUST NOT grow without bound.
2. Process RSS MUST plateau after warmup. Sustained growth in RSS indicates a violation (e.g. frames or buffers leaking).
3. Growth beyond N frames without consumption (e.g. fill thread pushing while consumer is not popping, or unreachable buffer still filling) is a violation. Enforcement: hard cap on container size (INV-VIDEO-BOUNDED), slot-based gating so fill thread parks when depth ≥ target, and no orphaned fill threads (INV-FILL-THREAD-LIFECYCLE-001, INV-BUFFER-INSTANCE-SINGULARITY).

**Detection:** Log or metric when depth exceeds target + margin for extended period; monitor RSS over long runs; treat unbounded depth or RSS growth as invariant violation.

---

### INV-BOOT-IMMEDIATE-DECODABLE-OUTPUT: Decodable Output Within 500ms

**Owner:** MpegTSOutputSink / ProgramOutput  

After `AttachStream` succeeds, AIR MUST emit decodable MPEG-TS within 500ms, using fallback video/audio if real content not yet available.

**Layers:**
1. **ProgramOutput:** Wait up to 500ms for first real content; emit pad if expires
2. **MuxLoop:** Wait up to 500ms for first frame to initialize timing; initialize synthetically if expires

---

### INV-SINK-NO-IMPLICIT-EOF: Continuous Output Until Explicit Stop

**Owner:** MpegTSOutputSink / MuxLoop

After `AttachStream` succeeds, sink MUST continue emitting TS packets until:
1. StopChannel RPC
2. DetachStream RPC
3. Slow-consumer detach
4. Fatal socket error

**Forbidden Termination Causes:**
- Producer EOF
- Empty queues
- Decode errors
- Segment boundaries
- Content deficit

**Contract tests:** `pkg/air/tests/contracts/Phase9SteadyStateSilenceTests.cpp`; `pkg/air/tests/contracts/PrimitiveInvariants/SinkLivenessContractTests.cpp` — existing tests enforce continuous output until explicit stop.

---

### INV-PAD-PRODUCER: Pad as First-Class TAKE-Selectable Source

**Owner:** PipelineManager  
**Depends on:** INV-TICK-GUARANTEED-OUTPUT, INV-BLOCK-WALLFENCE-001

PadProducer is first-class source participating in TAKE source selection. Produces black video (ITU-R BT.601: Y=16, Cb=Cr=128) and silent audio in session program format, unconditionally.

**Key Rules:**
1. **Unconditional availability:** Always ready, no exhaustion, zero latency
2. **Session-format conformance:** Matches program format exactly
3. **Deterministic content:** Fixed black+silence (ITU-R BT.601)
4. **Timestamp from session frame index:** `pts = session_frame_index * frame_duration`
5. **TAKE-selectable with recorded identity:** commit_slot='P', is_pad=true, asset_uri sentinel
6. **TAKE priority:** Content first, then freeze, then PadProducer
7. **Content-before-pad gate:** No pad until first real frame committed
8. **Session lifetime:** Not block-affiliated, exists session-lifetime
9. **Zero-cost transition:** Select/deselect within single tick

**Audio-only exception (FENCE_AUDIO_PAD):** At fence tick, if incoming audio buffer not primed, PipelineManager MAY inject silence for that tick's audio only. Does not affect video source selection.

---

### INV-PAD-SEAM-AUDIO-READY: PAD Segment Audio Source and Fence Readiness

**Status:** Big Boy Broadcast Ready — must never be weakened in future refactors.  
**Owner:** PipelineManager  
**Depends on:** INV-PAD-PRODUCER, fence/emit path semantics  

When the **active segment type** is **PAD**, the audio source for that tick **MUST**:

1. **Be non-null** — effective audio source pointer MUST NOT be null.
2. **Be routable to a concrete AudioBuffer** — MUST resolve to a real AudioLookaheadBuffer used for emission (e.g. live buffer after segment swap).
3. **Have at least one tick-worth of silence available before fence evaluation** — PAD silence MUST be pushed into the emission buffer before the fence/emit path evaluates.
4. **Not rely on IsPrimed() when PAD silence was injected that tick** — if silence was pushed in the same tick (e.g. segment-swap-to-PAD), the emit path MUST NOT require IsPrimed(); treat “PAD segment + silence pushed this tick” as sufficient.
5. **Never trigger FENCE_AUDIO_PAD during segment-swap-to-PAD** — the branch that logs `WARNING FENCE_AUDIO_PAD: audio not primed` MUST NOT be taken when the active segment is PAD.

**Authority:** Segment type (active segment for the tick) is the authority for “this tick is PAD”; MUST NOT rely solely on the decision classifier (e.g. `decision == kPad`), which may lag at the seam.

**Scope:** Applies to segment swaps (CONTENT→PAD, CONTENT→CONTENT→PAD, multi-slot), slot A/B activation, shadow decode promotion, any PerformSegmentSwap path, 30fps and 60fps. Does NOT apply to decoder starvation, intentional underflow tests, or audio-disable modes.

**Failure signature:** Any occurrence of `WARNING FENCE_AUDIO_PAD: audio not primed`; any tick in a PAD segment where `a_src == nullptr`; any PAD segment window where silence is not pushed before fence evaluation.

**Contract test:** `pkg/air/tests/contracts/BlockPlan/PipelineManagerSegmentSwapPadFenceContractTests.cpp` — `SegmentSwapToPad_NoFenceAudioPad` enforces this invariant.

---

### INV-NO-FLOAT-FPS-TIMEBASE-001: No Floating FPS Timebase in Runtime

**Owner:** All runtime code under pkg/air/src and pkg/air/include

Output timing math MUST use RationalFps (fps_num / fps_den). Runtime code MUST NOT compute frame/tick durations via float-derived formulas.

**Forbidden in runtime:**
- `1'000'000.0 / fps`, `1'000'000 / fps`, `1e6 / fps` for duration
- `round(1e6 / fps)`, `round(1'000'000 / fps)` for duration
- Any expression computing duration by dividing million by floating FPS

**Allowed:**
- `RationalFps::FrameDurationUs()`, `FrameDurationNs()`, `FrameDurationMs()`
- Integer formulas: `(n * 1'000'000 * fps_den) / fps_num`
- `DeriveRationalFPS(double_fps)` then `fps.FrameDurationUs()`

---

## Broadcast-Grade Guarantees

### LAW-OUTPUT-LIVENESS

TS packets must flow continuously. Stalls >500ms indicate failure.

**Source:** `PlayoutInvariants-BroadcastGradeGuarantees.md` (laws/)

---

### Clock Law (Layer 0)

MasterClock is sole time authority. Content clock is not MasterClock and must not be source of "now" for transition decisions.

PTS correctness measured against MasterClock, not wall clock.

---

## Document History

- **2026-02-23:** Initial consolidation of all INV-* files
- Individual INV-* files archived to `/pkg/air/docs/archive/invariants/`
- Source files consolidated from `/pkg/air/docs/contracts/` (root level invariants)
