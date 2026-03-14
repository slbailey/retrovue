# INV-HANDOFF-001: Frame-Store Redesign — Implementation Plan

**Status:** Plan (no code yet).  
**Goal:** Replace “next frame wins” FIFO semantics with “frame matching selected_src wins” so the tick loop is the sole authority for which source frame is displayed; decode only supplies frames.

---

## 1. Design principles

| Principle | Description |
|-----------|-------------|
| **Tick loop is sole authority** | Each tick the loop computes `selected_src = SourceFrameForTick(output_tick)` and requests that exact frame. No implicit “head of queue” semantics. |
| **Decoder supplies frames** | The decode/fill path only produces frames and stores them. It does not decide which frame is “current”; it does not enforce cadence. |
| **Frame store keyed by index** | Frames are stored by `source_frame_index`, not in a FIFO. The consumer asks for frame N. |
| **REPEAT = reuse prior frame** | On a REPEAT tick we reuse the last displayed frame. No pop, no dependency on queue order or fill timing. |
| **Audio independent** | Audio is buffered and consumed per tick regardless of which video frame is displayed. No gating of audio push on “allowed” video decode. |

---

## 2. Why step back from the cadence gate

The current approach enforces cadence in the **fill thread** (gate decode so we only push when `producer_next <= next_required + lookahead`). That leads to:

- **Underflow risk** when the gate is strict (only one frame ahead).
- **Audio choppiness** when the gate blocks decode (no decode ⇒ no audio push).
- **Oscillation / jitter** when we use a threshold (e.g. audio below target) to bypass the gate.

Cadence is a **consumer** concern: “which source frame should be shown this tick?”. The **producer** should only supply frames; the **consumer** should ask for the right one. So cadence belongs in the tick loop (authority) and in the **interface** between tick loop and frame supply (request by index), not in the fill thread.

---

## 3. Target architecture: frame store

### 3.1 Data model

- **Store:** A structure keyed by `source_frame_index` (1-based to match `SourceFrameForTick`).
  - Option A: `std::map<int64_t, VideoBufferFrame>` (or unordered_map).
  - Option B: Bounded sliding window: only keep indices in `[selected_src - back_margin, selected_src + lookahead]`; evict outside that range.
- **Fill thread:** Decode produces frames in order. For each decoded frame with index `N`, **store** it at key `N` (and evict if over capacity).
- **Tick loop:** On ADVANCE: `selected_src = SourceFrameForTick(...)`. Request frame `selected_src` from the store. If present ⇒ use it and update “last displayed”. If absent ⇒ underflow (decode has not reached that index yet). On REPEAT: use last displayed frame; do not touch the store.

### 3.2 Audio

- Audio continues to be produced by the same decode path (each decoded video frame carries its audio).
- Audio is pushed into `AudioLookaheadBuffer` **whenever** we decode a frame, independent of whether that frame is ever requested by the tick loop.
- The tick loop consumes audio per tick (fixed samples per tick) as today. No change to audio consumption logic.

### 3.3 Underflow and backpressure

- **Underflow:** Tick requests frame N, store does not have N ⇒ underflow (decode not reached N yet). Same hard-fault semantics as today.
- **Backpressure:** The store has a bounded size. When full, the fill thread must evict (e.g. oldest by index) or block. Eviction policy should prefer keeping a window around “current” selected_src (e.g. requested by tick loop or last known selected_src).

### 3.4 REPEAT ticks

- No pop, no lookup. `chosen_video = &last_good_video_frame_` (or equivalent). Already the case in the current code; keep it.

---

## 4. Implementation plan (phased)

### Phase A — Intermediate proof: “discard until head matches selected_src”

**Purpose:** Validate that **exact frame addressing** (consumer requests the frame that matches `selected_src`) removes the fast-play / underflow tradeoff, without yet changing the fill path or data structure.

**Idea:** Keep the current FIFO and fill thread. In the **consumer** (tick loop), when we would pop one frame on ADVANCE, instead:

1. Compute `selected_src = SourceFrameForTick(...)` (already done).
2. **While** the buffer is non-empty and `front.source_frame_index != selected_src`: pop the front and **discard** it (do not use it; count discarded).
3. If the buffer is non-empty and `front.source_frame_index == selected_src`: pop that frame and use it.
4. Else: underflow (empty or head never matched).

So we simulate “request exact frame” on top of the existing FIFO: we discard decoded frames until the head is the one we want. If playback is correct (no fast play, correct frame at each tick) and INV-HANDOFF-001 holds, we have proven that the bug is purely “using the wrong frame from the queue”. Cost: we may discard frames (wasted decode) and we may underflow if decode is slow and we never see `selected_src` at the head.

**Required API (VideoLookaheadBuffer):**

- **TryPeekFront(VideoBufferFrame& out)** → `bool`: if non-empty, assign `out = frames_.front()` (or a copy), return true; else false. Does not pop.
- **DiscardFront()** → void: if non-empty, pop front, update `total_popped_` (and any stats), notify `space_cv_`. Optionally count “discarded” separately for diagnostics.

**Tick loop change (PipelineManager, ADVANCE path):**

- When `should_advance_video && v_src`:
  - In **intermediate-proof mode** (e.g. `kFrameStoreProofMode` or compile flag):
    - Loop: while `v_src->TryPeekFront(peek)` and `peek.source_frame_index != selected_src_this_tick`: `v_src->DiscardFront()`; increment discarded counter.
    - Then: if `v_src->TryPeekFront(peek)` and `peek.source_frame_index == selected_src_this_tick`: `v_src->TryPopFrame(vbf)` (or pop and assign), use `vbf`. Else: underflow (treat as no frame).
  - Else (current behavior): single `v_src->TryPopFrame(vbf)`.

**Validation:** Run 23.976 → 29.97 content. Confirm:

- No fast play; no INV-HANDOFF-001 violations (because we only use a frame when it matches `selected_src`).
- Optional: log discarded count per tick or per window; expect non-zero when fill thread was “ahead”.
- If underflow increases, that indicates decode cannot keep the “right” frame at the head in time; frame-store design will need to ensure decode runs ahead of consumption (store by index avoids discarding).

**Build:** Phase A proof logic is **disabled by default**. To enable, configure with  
`-DINV_HANDOFF_PROOF_A=1` (e.g. `cmake -S pkg/air -B pkg/air/build -DINV_HANDOFF_PROOF_A=1`)  
so that `INV_HANDOFF_PROOF_A` is defined and the discard-until-match path is compiled in. Without it, the advance path uses the original single `TryPopFrame` and playback is unchanged.

**Deliverable:** Documented proof mode, optional build flag, and validation results. No removal of cadence gate yet; proof mode can coexist with current fill behavior.

---

### Phase B — Frame store (keyed by source_frame_index)

**Purpose:** Replace the FIFO with a store keyed by `source_frame_index`.

**Design choices:**

- **Container:** Bounded map or sliding window. Suggested: a map (e.g. `std::map<int64_t, VideoBufferFrame>`) with a max size; when at capacity, evict the entry with smallest key (oldest index) before insert. Alternatively, maintain only indices in `[min_key_, min_key_ + capacity)` and advance `min_key_` when the tick loop advances (requires tick loop to signal “I will not ask for indices &lt; X”).
- **Fill thread:** Instead of `frames_.push_back(vf)`, do `store_[vf.source_frame_index] = std::move(vf)`; then evict if `store_.size() > capacity`. Eviction: remove smallest key (or key outside [current - back, current + front] if we have a “current” hint from the tick loop).
- **Consumer API:** `TryGetFrame(int64_t source_index, VideoBufferFrame& out)` → bool. If `store_.count(source_index)` then assign and optionally remove (or leave for REPEAT / debugging). Return false if not present.

**Migration:** Introduce a new buffer type (e.g. `VideoFrameStore`) or a mode in `VideoLookaheadBuffer` (e.g. “frame_store_mode”) so we can switch without rewriting all call sites at once. PipelineManager would use “get(selected_src)” instead of “pop front”.

---

### Phase C — Tick loop: request by selected_src; REPEAT unchanged; audio independent

**Tick loop (ADVANCE):**

- `selected_src = SourceFrameForTick(...)` (unchanged).
- Call `v_src->TryGetFrame(selected_src, vbf)`. If true, use `vbf` and set last_good_*. If false, underflow.
- REPEAT path: unchanged; reuse `last_good_video_frame_`.

**Audio:** Fill thread pushes audio to `AudioLookaheadBuffer` for every decoded frame. No condition on “allowed” video index. Remove cadence-gate logic from the fill thread (Phase D).

---

### Phase D — Simplify fill thread: decode and store only

- Remove Phase 3 cadence gate from `VideoLookaheadBuffer::FillLoop()` (no `next_required_source_frame_`, no “decode for audio only” drop logic tied to cadence).
- Fill thread loop: decode (TryGetFrame from producer); if frame received, store by `source_frame_index` and push audio. If store full, evict then store. No “only push when producer_next <= next_required”.
- Optional: tick loop can pass “hint: I am at selected_src” so the store can evict indices &lt; selected_src - back_margin (reduces memory).

---

## 5. Intermediate proof (Phase A) — Detailed steps

1. **VideoLookaheadBuffer**
   - Add `bool TryPeekFront(VideoBufferFrame& out) const` (or non-const if we need to read under lock): under mutex, if `frames_.empty()` return false; else assign `out = frames_.front()`, return true.
   - Add `void DiscardFront()`: under mutex, if !empty pop_front, increment `total_popped_`, notify `space_cv_`. Optionally increment a `discarded_count_` for diagnostics.

2. **PipelineManager**
   - Add a mode flag (e.g. `bool frame_store_proof_mode_` or `#ifdef INV_HANDOFF_FRAME_STORE_PROOF`). Default false so behavior is unchanged.
   - In the ADVANCE path where we currently call `v_src->TryPopFrame(vbf)`:
     - If proof mode: loop calling `TryPeekFront` and `DiscardFront` until front matches `selected_src_this_tick` or buffer empty. Then if front matches, `TryPopFrame(vbf)` and use it; else underflow.
     - Else: keep current single `TryPopFrame(vbf)`.

3. **Invariant**
   - INV-HANDOFF-001 remains: we only *use* a frame when `vbf.source_frame_index == selected_src_this_tick`. In proof mode we enforce that by discarding until match. So no violation in proof mode (except underflow if we never see the frame).

4. **Validation**
   - Enable proof mode. Run 23.976 → 29.97. Check: no fast play, no INV-HANDOFF-001 violations. Optionally log discarded count; if high, confirms fill was “ahead” and frame-store will avoid that waste.

5. **Rollback**
   - Proof mode off = current behavior. No removal of cadence gate until Phase D.

---

## 6. Summary

| Phase | What | Outcome |
|-------|------|---------|
| **A** | Consumer “discard until head == selected_src” on current FIFO | Proof that exact-frame addressing fixes the bug; no change to fill or store. |
| **B** | Replace FIFO with frame store keyed by source_frame_index | Consumer can request frame N; no discard. |
| **C** | Tick loop requests selected_src; REPEAT reuse; audio independent | Single authority; audio decoupled from video gate. |
| **D** | Remove cadence gate from fill thread; decode and store only | Simpler fill; no oscillation/jitter from gate. |

The intermediate proof (Phase A) is the lowest-risk way to validate the redesign before committing to the frame-store implementation (Phases B–D).
