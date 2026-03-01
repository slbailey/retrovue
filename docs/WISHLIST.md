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

- **Independent Audio Servicing Pipeline (Broadcast-Grade)** *(Phase 2 / Phase 8+; design doc / wishlist. Not immediately required to ship; canonical “real broadcast” endpoint.)*

  **Problem:** Current architecture couples audio production to video decode progress. When video buffering backpressures decode, audio can starve, causing `AUDIO_UNDERFLOW_SILENCE`, stutter, slow-motion perception, and PCR/PTS instability. Audio is effectively a side effect of video decode rather than an independently serviced stream.

  **Goals:**
  - Decouple audio production from video decode so that audio is never starved by video backpressure.
  - Maintain a dedicated **AudioLookaheadBuffer** target depth via continuous demux/decode/resample independent of video buffer fullness.
  - Allow video decode to be independently throttled; audio is protected by its own watermarks and backpressure rules.
  - Enforce explicit policies for mixed-FPS and DROP/CADENCE: video frame selection may drop/repeat; audio must reflect continuous media time and house clock pacing.

  **Non-goals:**
  - Do not change Core’s ownership of schedule intent, segment boundaries, or playout plans; Core still drives what is “live” and when seams occur.
  - Do not remove or bypass the existing PAD A/B architecture; the audio pipeline must integrate with seam readiness and segment swaps.
  - Do not introduce a second “editorial” timeline; audio and video remain on the same house clock and media-time basis, with servicing decoupled, not semantics.

  **Proposed design:**

  1. **Dedicated AudioService**
     - Demuxes, decodes, and resamples audio **continuously** to maintain `AudioLookaheadBuffer` at a configurable target depth.
     - Owns its own pull from the source (e.g. same asset/container as video, but separate read/decode path) so that backpressure on video decode does not block audio fill.
     - Watermarks: refill when depth falls below low watermark; optional high watermark to avoid unbounded buffering. Backpressure rules apply only to the audio path (e.g. do not advance demux past a safe lead over video if we need A/V sync; see dual-clock below).

  2. **Video decode independence**
     - Video decode can be throttled (e.g. when downstream is slow) without reducing audio decode rate. AudioService runs on its own thread/task and is not gated by “next video frame” availability.
     - Sync discipline: audio and video are aligned on **house clock** and **media time** at defined sync points (e.g. segment start, seam); during steady state, audio pacing is driven by house clock, and video frame selection (DROP/DUPLICATE/CADENCE) is driven by output fps and availability. Audio never “waits” for video decode to produce the next frame.

  3. **Mixed-FPS and DROP/CADENCE policy**
     - **Video:** Frame selection may drop or repeat frames (e.g. 60→29.97 DROP, 23.976→29.97 DUPLICATE) per existing or future cadence engine. Video PTS reflects selected output frames.
     - **Audio:** Must reflect **continuous** media time and house clock pacing: no artificial gaps or repeats that would cause audible stutter or drift. Resampling handles rate conversion; audio buffer is consumed at a rate determined by house clock (and optionally PCR), not by video frame ticks.

  4. **API sketches (conceptual)**
     - `AudioService::Start(asset_or_demux_handle, output_format, target_depth_ms, low_watermark_ms)` — start continuous fill against `AudioLookaheadBuffer`.
     - `AudioService::Stop()` / `AudioService::SwitchSource(next_asset_or_handle)` — for seam and segment boundaries.
     - `AudioService::GetDepthMs()`, `AudioService::WaitForMinDepth(min_ms, timeout)` — for readiness and integration with seam logic (e.g. PAD_B priming).
     - Optional: `AudioService::SetHouseClock(clock)` or equivalent so pacing is explicit and testable.
     - Buffer/consumer side: existing (or extended) `AudioLookaheadBuffer` remains the contract boundary; AudioService is the sole producer for that buffer during a segment.

  5. **Interaction with TickProducer / FFmpegDecoder**
     - **TickProducer:** Continues to drive “output” time (house clock, frame ticks). It does **not** drive audio decode; it drives when audio is **consumed** (e.g. when we emit samples to the mux). AudioService runs asynchronously and keeps the buffer full; TickProducer (or mux stage) pulls from `AudioLookaheadBuffer` at playout time.
     - **FFmpegDecoder:** Today it may do both video and audio decode in one pipeline. Under this design, either:
       - **Option A:** FFmpegDecoder remains the video decoder; a separate **audio-only** demux/decode path (e.g. dedicated AVFormatContext/AVCodecContext for audio, or a separate “audio decoder” instance reading from the same or a split demux) feeds AudioService. Demux may be shared (with careful thread-safety) or split (e.g. pre-demux copy of audio stream).  
       - **Option B:** FFmpegDecoder exposes an “audio only” mode or a dedicated AudioDecoder that is invoked by AudioService on its own thread; video decode path is separate and can be throttled without blocking this path.
     - Contract: AudioService never blocks on “next video frame”; FFmpegDecoder (video) and AudioService (audio) do not share a single blocking decode loop.

  6. **Seams (PAD/content) and dual-clock drift**
     - **On seam (segment swap, PAD ↔ content):** AudioService must switch source (new segment or PAD). Sync point: at the seam, we define a new common anchor (e.g. house clock time T, media time M). AudioService drains or flushes as per segment-end policy, then starts filling from the new source; consumer (mux/TickProducer) continues to consume at house clock rate so there is no “pause” in wall-clock time. Any small gap is handled by documented policy (e.g. silence insertion, or hold last sample for one segment boundary only).
     - **Avoiding dual-clock drift:** There is only **one** authoritative clock for output: the house clock (and PCR if used). Audio **pacing** (consumption from AudioLookaheadBuffer) is driven by that clock. Audio **production** (decode/resample into the buffer) is driven by “keep buffer at target depth” and must not run on a different long-term rate. So: production runs “as fast as needed” to keep depth, consumption runs at house clock rate; we avoid drift by (1) not having a separate “audio clock” and (2) aligning to house clock at seams and optionally at periodic sync points. No second PLL or clock domain for audio.

  **Invariants / Contracts (candidate):**
  - **INV-AUDIO-001:** Audio consumption rate is determined only by house clock (and PCR if applicable); no rate derived from video frame ticks.
  - **INV-AUDIO-002:** AudioService maintains `AudioLookaheadBuffer` depth between configured low and high watermarks during steady state; underflow (depth below minimum required for playout) is a failure mode that must be observable and recoverable.
  - **INV-AUDIO-003:** At segment seam, audio and video share the same sync anchor (house time + media time); no independent “audio timeline” that can drift from video.
  - **INV-AUDIO-004:** Video frame selection (DROP/CADENCE) does not alter audio sample emission; audio reflects continuous media time and house-clock pacing.

  **Observability:**
  - **Metrics:** Audio buffer depth (min/max/current), underflow count, refill latency, source switch latency at seams, resampler input/output rates.
  - **Logging:** Segment start/end for audio source, depth at seam, underflow events (with reason: backpressure vs decode lag vs source switch), and any sync correction applied.
  - **Alerts:** When depth remains below low watermark for longer than a threshold, or when underflow occurs (e.g. `AUDIO_UNDERFLOW_SILENCE` replacement with structured event + counter).

  **Rollout steps (conceptual):**
  1. **Design and contract:** Document AudioService API and invariants in AIR contracts; define buffer ownership and seam handoff with existing PAD/SeamScheduler.
  2. **Audio-only demux/decode path:** Implement or isolate an audio-only path (Option A or B above) that can run without blocking on video decode; unit tests with synthetic sources.
  3. **AudioService component:** Implement AudioService that fills `AudioLookaheadBuffer` from the audio-only path; integrate with existing buffer and watermarks; no change yet to TickProducer/FFmpegDecoder coupling in production.
  4. **Decouple consumption:** Ensure TickProducer/mux consumes audio from buffer at house clock rate only; remove any implicit coupling where audio “waits” on video decode.
  5. **Seam integration:** On segment swap, drive AudioService source switch and sync anchor; validate no dual-clock drift and no underflow at seams (tests + staging).
  6. **Observability and hardening:** Add metrics, logging, and recovery policies; replace legacy underflow handling with structured events; document rollout and rollback.

---

- **Linear-to-Library QR Bridge (Trailer Watch-Now Option)** *(Wishlist only; documentation of a future concept. No code, contract, or runtime changes.)*

  **Concept Overview:**
  RetroVue remains a strictly linear broadcast simulator. However, trailers that promote a future Tier 1 scheduled movie could optionally display a QR code that bridges the viewer OUT of RetroVue and into their personal media server (Plex, Jellyfin, Emby, etc.) to watch the promoted film immediately.

  Flow:
  1. A trailer promotes a future Tier 1 scheduled movie.
  2. A lower-third displays the scheduled airtime (e.g., "Sunday @ 9PM — HBO Classics").
  3. A QR code appears late in the trailer (recommended: final 10–15 seconds for urgency).
  4. Scanning the QR redirects to a RetroVue bridge endpoint.
  5. The bridge endpoint performs an HTTP redirect to the viewer's configured library provider.
  6. The viewer watches the film on their own platform. RetroVue's involvement ends at the redirect.

  **Architectural Integrity:**
  - No VOD playback inside RetroVue. The system remains a linear broadcast simulator.
  - No playback orchestration inside RetroVue. RetroVue does not control, monitor, or coordinate external playback.
  - No MasterClock changes. The channel timeline is unaffected.
  - No Playlog or Channel timeline mutation. The QR bridge is invisible to scheduling and as-run logging.
  - Implemented purely as metadata on trailer assets + an OverlayStage concept for QR rendering.

  **Conceptual Metadata Addition — PromoBridge:**
  Trailer assets may carry optional `PromoBridge` metadata:
  - `external_provider` — target library system (`plex`, `jellyfin`, `emby`, etc.)
  - `external_key` — provider-specific content identifier (`ratingKey`, `itemId`, etc.)
  - `allow_watch_now` — bool; controls whether the QR overlay activates for this trailer

  PromoBridge metadata is editorial metadata attached to the asset. It does not affect scheduling, playout plans, or segment boundaries.

  **Overlay Concept — LibraryBridgeOverlayStage:**
  - A new OverlayStage that activates only for trailer assets carrying PromoBridge metadata with `allow_watch_now = true`.
  - QR code is generated at playout time from the bridge URL and the asset's PromoBridge metadata.
  - Recommended placement: final 10–15 seconds of the trailer, creating urgency ("scan now or wait until Sunday").
  - The overlay is purely visual; it does not alter audio, segment timing, or playout behavior.

  **Redirect Service Concept:**
  - Endpoint: `/bridge/{promo_id}`
  - Resolves `promo_id` to the PromoBridge metadata for the asset.
  - Performs an HTTP redirect (302) to the provider's deep link (`plex://`, `jellyfin://`, etc.).
  - RetroVue does not control playback after the redirect. The handoff is complete and final.
  - No state is written back into Core. No playlog entry. No schedule mutation.

  **Strategic Value:**
  - Preserves appointment viewing as the primary model. The scheduled airing remains the default experience.
  - Bridges viewer impatience without compromising the linear philosophy — the viewer leaves RetroVue to watch elsewhere.
  - Feels like modern broadcast behavior: a promotional call-to-action within a linear stream.
  - Enables potential future engagement metrics (bridge click-through rates) without altering the broadcast model.

  **Explicit Non-Goals:**
  - No VOD streaming support inside RetroVue.
  - No Plex/Jellyfin/Emby API auto-play orchestration.
  - No channel timeline alteration when a viewer scans the QR.
  - No schedule mutation based on bridge usage.
  - No blending of linear and on-demand models internally. RetroVue is linear. The bridge is an exit ramp, not a lane merge.

---

