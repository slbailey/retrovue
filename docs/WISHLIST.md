# RetroVue Wishlist

Ideas and desired improvements. Not yet committed to roadmaps or contracts.

---

<!-- Add items below -->

- **Continuity announcer.** AI-generated continuity announcements during tier-2 schedule buildout; voice is injected over the end of the last segment of a TV show. Requires a custom iFrameEnricher.

---

- **Expand iFrameEnricher: waterbug + lower third.** Add a waterbug enricher and a lower-third enricher; compose them like Photoshop layers inside the frame before it’s handed to the output ring buffer.

---

- **Broadcast-Grade Diagnostic Slate Overlay.** Add a configurable DiagnosticOverlayStage that activates automatically when content decoding fails or PAD continuity is engaged due to asset errors. The overlay should display block ID, asset URI, failure reason, channel ID, CT, and UTC time. Must not modify playout timing, fence behavior, or scheduling. Configurable per channel (OFF / DEV / NOC). Designed for operator clarity and rapid fault isolation.

---

- **BlockPlan contract tests run seemingly forever.** Root cause: the default build does *not* set `RETROVUE_FAST_TEST`, so tests use real wall-clock — `kStdBlockMs=5000`, `kBootGuardMs=3000`, and many tests wait for block completion with 8–20 s timeouts. With ~165 tests, pipeline-heavy tests each take 5–20+ seconds, so the full suite can take 15–30+ minutes and feels endless. **Workaround:** Configure and build with `-DRETROVUE_FAST_TEST=1` so tests use `DeterministicTimeSource`, 500 ms blocks, and 2.5 s boot guard; the suite then completes in a few minutes. Optionally make fast mode the default for CI/local `ctest` runs, or add a CTest `TIMEOUT` so a hung run is killed.

---

- **REAL Broadcast-Grade PAD_B Readiness Signaling** *(Phase 2 architectural improvement; documentation only.)*

  **Problem:** Current PAD_B priming uses a bounded spin + `std::this_thread::yield()`. This is deterministic but not optimal or architecturally clean. Professional broadcast systems use explicit readiness signaling, not polling.

  **Proposed future improvement:**

  1. **Modify AudioLookaheadBuffer:** Add a `condition_variable`; signal when `DepthMs()` crosses configurable thresholds.
  2. **Add a method:** `WaitForMinDepth(int min_ms, std::chrono::milliseconds timeout);`
  3. **Modify VideoLookaheadBuffer** similarly for frame depth.
  4. **Replace PrimePadBForSeamOrDie spin loop** with:
     ```cpp
     pad_b_audio_buffer_->WaitForMinDepth(
         kMinSegmentSwapAudioMs,
         std::chrono::milliseconds(250)
     );
     ```
  5. **If timeout occurs:** Log ERROR; fail fast in debug builds; optionally trigger fallback injection in production.

  **Benefits:** No spin/yield loops; no CPU waste; deterministic seam readiness; clear separation of producer readiness and seam logic; proper backpressure model.

  **Non-goals:** Do not remove pad_b architecture; do not collapse PAD into deterministic emission mode; maintain A/B swap model.

---

- **Broadcast-grade Seam & Cadence Engine** *(Phase 2 / tech-debt; wishlist, not necessarily implemented now.)*

  **Problem:** We currently risk seam timing drift and incorrect cadence behavior when swapping between sources with different input fps (e.g., 60fps assets in a 29.97 output session). We also observed cases where `seam_frame` can be stale after swaps, causing immediate catch-up and black/blank output.

  **Broadcast-grade requirements (wishlist):**

  1. **Single source of truth timeline**
     - Segment boundaries are defined strictly on the **output** timeline (`ctx_->fps`), never derived from input fps or decoder frame counters.
     - After any swap, seam scheduling re-bases to “now” deterministically.

  2. **Dedicated SeamScheduler component**
     - Owns `next_seam_frame`, `target_segment`, segment frame budget.
     - Explicit API: `OnSegmentStart(segment_index, seg_frames, tick_now)` ⇒ computes future seams.
     - Hard invariant: **`next_seam_frame > tick_now` ALWAYS.**

  3. **Robust cadence / rate conversion policy**
     - Explicit modes: **DROP** (60→29.97), **DUPLICATE** (23.976→29.97), **HOLD** (pad/static), **EXACT** (match).
     - Deterministic mapping from output frame number ⇒ source frame number.
     - Never “DISABLED” unless input fps == output fps.
     - Expose diagnostics counters: `dropped_frames`, `duplicated_frames`, `cadence_mode`, `src_fps`, `out_fps`.

  4. **Swap safety gates**
     - Swap only when both audio and video meet minimum readiness.
     - If swap is committed, the new live chain must have guaranteed first-frame availability (no black).
     - If not, hold previous segment and retry (never advance segment index without output).

  5. **Telemetry + proofs**
     - Log once per segment start: `segment_index`, asset, `seg_frames`, `src_fps`, `cadence_mode`, `planned_end_tick`.
     - Assert (in debug/tests): tick progression cannot skip segment start/end unexpectedly.

  **Outcome:** A future refactor that makes the system behave like professional playout: deterministic segment durations on the output clock, with explicit cadence conversion and seam scheduling that cannot drift or go stale.

---

- **Broadcast-Grade Seam Scheduling** *(Phase 2; design doc / wishlist.)*

  **Problem statement:** We currently compute segment seam frames at block activation and store them in a single precomputed `planned_segment_seam_frames_` array. Segment swaps can be deferred by readiness (especially for 60fps content). By the time a swap commits, those precomputed boundaries can lie in the past relative to the current session tick. The tick thread then sees `session_frame_index >= next_seam_frame_` immediately, triggers catch-up thrash (rapid segment advances), and can produce black output because the new segment’s first frame is not yet available. There is no separation between “when we planned to seam” and “when we actually seamed,” and no rebasing of remaining seams at swap time.

  **Goals:**
  - Replace the single precomputed seam array with an explicit **SeamScheduler** component that owns all seam logic.
  - Guarantee that the **next** seam is always strictly in the future (monotonic seam schedule).
  - Support authoritative per-segment intended airtime and clear PLANNED vs COMMITTED/ACTUAL boundaries for as-run and debugging.
  - Handle zero-duration segments (`duration_ms == 0`) via an explicit policy (e.g. until fence or minimum dwell).
  - Enable incremental rollout without rewriting the entire PipelineManager.

  **Non-goals:**
  - Do not change pad A/B architecture or readiness semantics; SeamScheduler consumes readiness outcomes.
  - Do not move cadence/rate conversion into SeamScheduler (that stays in the existing cadence/seam engine scope).
  - Do not define EPG or editorial truth; Core remains owner of schedule intent.

  **Proposed design:**

  1. **SeamScheduler component**
     - **Owns:** authoritative per-segment intended airtime window (start/end on output timeline), PLANNED boundaries (from plan), COMMITTED/ACTUAL boundaries (when seam actually fired).
     - **API (conceptual):** e.g. `OnBlockActivation(planned_segment_boundaries, output_fps)`, `OnSegmentSwap(tick_now, segment_index, segment_duration_output_frames, block_fence_frame)` → returns rebased `next_seam_frame` and updated schedule.
     - **Rebasing at swap time:** Use wall-clock/session tick as the join point; segment duration in output fps frames; block fence as hard cap. Formula: `next_seam_frame = min(tick_now + segment_duration_output_frames, block_fence_frame)`, with strict guarantee `next_seam_frame > tick_now`.
     - **Zero-duration policy:** When `duration_ms == 0`, define explicit behavior: e.g. “seam at block fence” or “minimum dwell (e.g. 1 frame) then seam,” and document in invariants.

  2. **Monotonic seam schedule**
     - SeamScheduler emits a schedule such that the **next** seam tick is always strictly in the future. No “seam now” unless it’s the intended immediate take; after any rebase, `next_seam_frame_ > session_frame_index` until the actual seam tick.

  3. **Structured events**
     - Emit structured events (e.g. JSON or typed log lines) for: segment start (planned), segment commit (actual), rebase, thrash-prevention, zero-duration handling. Consumable by as-run logging and debugging tooling.

  4. **Version stamp in every log**
     - Require a version stamp (e.g. build/version id) in every log line or log batch so that as-run and incident analysis can correlate with a specific binary.

  **Invariants (candidate):**
  - **INV-SEAM-001:** After any segment swap, `next_seam_frame > session_frame_index` (monotonic next seam).
  - **INV-SEAM-002:** `next_seam_frame <= block_fence_frame` whenever a block fence is active.
  - **INV-SEAM-003:** COMMITTED segment boundary is never before the PLANNED segment start (no time-travel).
  - **INV-SEAM-004:** Zero-duration segments are handled by documented policy only (no undefined behavior).

  **Observability:**
  - **Instrumentation counters:** number of seam corrections (rebase applied), number of thrash-preventions (swap deferred to avoid past seam), number of zero-duration segments encountered, number of “seam at fence” events.
  - **Logging:** Version stamp on every log; structured seam events (planned/committed/rebase/thrash-prevention) with tick, segment index, and reason codes.
  - **Tests:** Contract tests that assert monotonic next seam after swap, rebase semantics, and zero-duration policy.

  **Incremental rollout:**
  1. **Introduce SeamScheduler as a helper (no behavior change):** Add the component and have PipelineManager compute current `next_seam_frame_` via SeamScheduler’s API using existing `planned_segment_seam_frames_` and fence; keep writing back into `next_seam_frame_` as today. All existing invariants preserved.
  2. **Rebase at swap:** On segment swap, call SeamScheduler with `tick_now`, segment index, segment duration in output frames, and block fence; set `next_seam_frame_` from SeamScheduler’s rebased value. Add INV-SEAM-001/002 checks and instrumentation (seam corrections, thrash-preventions).
  3. **PLANNED vs COMMITTED:** SeamScheduler records PLANNED boundaries at block activation and COMMITTED at seam take; emit structured events. Add INV-SEAM-003.
  4. **Zero-duration policy:** Implement and document policy for `duration_ms == 0`; add counter and INV-SEAM-004.
  5. **Version stamp:** Add version stamp to log format and ensure all seam-related logs include it.
  6. **Deprecate raw array:** Once SeamScheduler is the single source of truth, stop populating `planned_segment_seam_frames_` from block activation for seam logic; keep only for legacy/telemetry if needed, or remove.

---

