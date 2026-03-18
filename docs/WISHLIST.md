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

Distributed Playout Workers

Introduce the ability to separate the Control Plane (scheduling, playlog generation, MasterClock, orchestration) from the Playout Execution Plane (ffmpeg producers).

Allow multiple worker nodes to dynamically execute channel playout based on load and availability, while preserving these invariants:

Control plane remains authoritative.

Scheduling and playlog generation remain centralized.

Workers are stateless and reconstruct playout from database + MasterClock.

Channels can be reassigned without timeline drift.

This phase should not alter current single-node behavior and must remain an additive evolution.

---

- **Per-Channel Encoding Bitrate.** Allow each channel to specify its own video encoding bitrate instead of the hardcoded 5 Mbps. A movie channel with 8 Mbps source material should encode at 8 Mbps; a TV channel with 3 Mbps content should encode at 3 Mbps. Requires a `bitrate` field in channel YAML format config, propagation through the Core playout plan to AIR, and AIR using the per-channel value instead of the hardcoded `config.bitrate = 5000000` in `playout_service.cpp` and `MpegTSPlayoutSinkConfig.hpp`.

---

- **Deterministic Playout Test Endpoint.** Enable on-demand, deterministic playback of any scheduled block (and later program/segment/channel) via HTTP, using the exact same playout pipeline as live AIR.

  **Problem this solves:** Current debugging of seams and playout behavior is time-dependent, non-deterministic, and slow to iterate (must wait for the timeline to reach the relevant block). This makes contract validation (seam continuity, cadence, short segments, etc.) inefficient and unreliable.

  **Desired capability:** A URL-triggered endpoint that accepts a block ID, launches a real playout session, and streams MPEG-TS output immediately.

  Example:
  ```
  http://<host>:8000/test/block/{block_id}.ts
  ```

  **Behavioral requirements:**
  - MUST use the same PipelineManager / TickProducer / Producer stack as live AIR.
  - MUST NOT bypass or simulate playout logic.
  - MUST produce identical behavior to live playout for the same block.
  - MUST start at block start (offset = 0) for initial version.
  - MUST stream in real time (no offline rendering).

  **Architecture constraints:**
  - Treat as a one-off ephemeral channel/session.
  - Reuse schedule/block resolution, playout pipeline, and producer (ffmpeg).
  - Maintain MasterClock alignment model (no alternate timing system).

  **Future extensions (not required for v1):**
  - `/test/program/{program_id}`
  - `/test/segment/{asset_id}`
  - `/test/channel/{channel_id}?t=<timestamp>`
  - Offset-based playback (mid-block testing)

  **Why this matters:**
  - Enables instant seam testing (no waiting for schedule).
  - Allows rapid validation of short segments, transitions, and buffer behavior.
  - Becomes a core QA and debugging tool.
  - Aligns with broadcast principle: "Any scheduled unit should be playable on demand."

  **Non-goals (v1):** No UI required. No persistence of sessions. No historical playback tracking.

  **Success criteria:** Hitting the endpoint immediately begins playback of the specified block. Seam behavior matches live channel behavior exactly. Engineers can reproduce seam bugs in seconds instead of minutes.

---
