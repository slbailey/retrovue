# Structured evidence: AIR teardown (cheers-24-7, reason=stopped)

**Scope:** Most recent AIR session for channel `cheers-24-7` that ended with `reason=stopped`.  
**Log:** `pkg/air/logs/cheers-24-7-air.log`  
**Window:** 120 seconds before first `AUDIO_UNDERFLOW_SILENCE` through 30 seconds after `CLEANUP_DEFERRED_FILL_BEGIN` (teardown).

- First `AUDIO_UNDERFLOW_SILENCE`: line 42941, frame=387220  
- `CLEANUP_DEFERRED_FILL_BEGIN` (teardown): line 42943  
- Session end: lines 42961–42962  
- Window: tick ≈ 383620 → end of log (≈ line 42561–42964). No per-line timestamps; tick/frame and wall_ms used where present.

---

## Timeline (chronological, trimmed to relevant lines)

Only lines in the window that match the requested patterns (or are needed for context) are below. Unmatched patterns: no `INV-BLOCK-WALLFENCE`, `fence_tick`, `BlockCompleted`, `remaining_block_frames`, `INV-FRAME-BUDGET`, or `block_start_tick` in this window; no `INV-TICK-GUARANTEED-OUTPUT`, `fallback`, `freeze`, `black`; no `stopping AIR`, `StopChannel`, `OutputClock`, or `Producer state change` in this log (server-side AIR only).

**Segment swap and priming (tick 386707–386708):**

```
[PipelineManager] EnsureIncomingBReadyForSeam B_ready tick=386707 to_segment=10 segment_b_audio_depth_ms=0 segment_b_video_depth_frames=1
[PipelineManager] SEGMENT_SWAP_DEFERRED reason=not_ready incoming_audio_ms=0 incoming_video_frames=1 tick=386707
[PipelineManager] SEGMENT_TAKE_COMMIT tick=386708 from_segment=9 to_segment=10 (CONTENT) is_pad=0 segment_b_audio_depth_ms=853 segment_b_video_depth_frames=25 audio_depth_ms=853 audio_gen=0 asset=/mnt/data/Filler/Commercials/Visa - Olympics (1988).mp4 seg_b_ready=1
[PipelineManager] CLEANUP_DEFERRED_FILL_BEGIN tick=386708 context=segment_swap
[PipelineManager] CLEANUP_DEFERRED_FILL_END tick=386708 context=segment_swap dt_ms=0
[PipelineManager] SEGMENT_PREP_ARMED tick=386708 parent_block=blk-27876a6566d2 next_segment=12 segment_type=CONTENT seam_frame=387621 headroom_frames=913 headroom_ms=30433 required_frames=8 skipped_pads=1
[PipelineManager] SEGMENT_SEAM_TAKE tick=386708 from_segment=9 (CONTENT) to_segment=10 (CONTENT) prep_mode=PREROLLED swap_branch=SWAP_B_TO_A next_seam_frame=387613
[PipelineManager] SEGMENT_SWAP_POST tick=386708 live_audio_depth_ms=874
```

**Priming (block/segment B):**

```
[VideoBuffer:SEGMENT_B_VIDEO_BUFFER] StartFilling: HasPrimedFrame=1 has_decoder=1 audio_buffer=yes
[VideoBuffer:SEGMENT_B_VIDEO_BUFFER] StartFilling: primed_frame audio_count=0
[TickProducer] Block assigned: blk-27876a6566d2 frames_per_block=902 segments=1 decoder_ok=true has_pad=0 input_fps=29.97 input_frame_dur_ms=33 output_frame_dur_ms=33
[TickProducer] INV-BLOCK-PRIME-001: primed frame 0 pts_ms=0 ct_before=0 asset=/mnt/data/Interstitials/Commercials/Toys/Toys-Queasy Bake.mkv
[TickProducer] INV-AUDIO-PRIME-001: PrimeFirstTick wanted_ms=500 got_ms=512 met=1 total_decodes=11 null_run=0 buffered_video=11
[SeamPreparer] PREP_COMPLETE type=segment block=blk-27876a6566d2 segment_index=12 segment_type=CONTENT decoder_used=true audio_depth_ms=512
```

**Last HEARTBEAT before underflow:**

```
[PipelineManager] HEARTBEAT frame=387000 video=25/30 refill=32.5586fps decode_p95=3444us audio=814ms/1000ms a_pushed=507904 a_popped=468800 sink=0/32768
```

**Underflow and teardown:**

```
[PipelineManager] DIAG_CONTENT_AUDIO tick=387210 is_pad=0 samples=1600 a_src_depth_ms=321 audio_pts_90k=1161630000 tag=REAL_AUDIO
[PipelineManager] AUDIO_UNDERFLOW_SILENCE frame=387220 is_pad=0 buffer_depth_ms=21 needed=1600 total_pushed=820224 total_popped=819200 a_src_primed=1 audio_ticks_emitted=387220
[PipelineManager] INV-VIDEO-LOOKAHEAD-001: UNDERFLOW frame=387221 buffer_depth=0 total_pushed=513 total_popped=513
[PipelineManager] CLEANUP_DEFERRED_FILL_BEGIN tick=teardown context=teardown
[PipelineManager] CLEANUP_DEFERRED_FILL_END tick=teardown context=teardown dt_ms=0
[PipelineManager] STOP_FILLING_BEGIN context=teardown_video tick=teardown
[FillLoop:LIVE_AUDIO_BUFFER] FILL_EXIT reason=fill_stop
[PipelineManager] STOP_FILLING_END context=teardown_video tick=teardown dt_ms=401
[PipelineManager] STOP_FILLING_BEGIN context=teardown_preview tick=teardown
[PipelineManager] STOP_FILLING_END context=teardown_preview tick=teardown dt_ms=0
[PipelineManager] STOP_FILLING_BEGIN context=teardown_pad_b tick=teardown
[PipelineManager] STOP_FILLING_END context=teardown_pad_b tick=teardown dt_ms=0
[PipelineManager] Session encoder closed: 3206770896 bytes written
[PipelineManager] SocketSink closed: delivered=3206770896 enqueued=3206770896 errors=0 detached=0
[PipelineManager] Thread exiting: frames_emitted=387221, reason=stopped
[EmitSessionEnded] reason=stopped, blocks_executed=6, subscribers=1
```

---

## Fence state

- **session_frame_index at death:** 387221 (from `Thread exiting: frames_emitted=387221` and `INV-VIDEO-LOOKAHEAD-001: UNDERFLOW frame=387221`).
- **fence_tick:** Not logged at death. Last block fence in log: `INV-BLOCK-WALLFENCE-001` at fence_frame=364337 (line 40389, block blk-97866b90b486). After that, only segment seams. `SEGMENT_PREP_ARMED` at tick=386708 gives `next_seam_frame=387621`; no `fence_tick` field in this log line.
- **remaining_block_frames:** Not logged at death. From `SEGMENT_PREP_ARMED`: seam_frame=387621, session_frame at death=387221 → 400 frames until next seam. `remaining_budget` appears only at block fences (e.g. INV-BLOCK-WALLFENCE remaining_budget=54000), not in this window.

---

## Priming state

- **Was next block kReady?** At segment swap (tick=386708) B was taken (SEGMENT_TAKE_COMMIT, SWAP_B_TO_A). Block blk-27876a6566d2 was assigned and `INV-BLOCK-PRIME-001` and `INV-AUDIO-PRIME-001` logged; segment B was kReady/primed.
- **Was a primed frame available?** At audio underflow: `a_src_primed=1`. At video underflow: `buffer_depth=0 total_pushed=513 total_popped=513` — video lookahead was exhausted; TryGetFrame failed, so no primed frame available for that tick.

---

## Output state

- **Last successful frame emitted:** Last HEARTBEAT before underflow: `frame=387000`. Last tick with both audio and video successfully supplied: 387219 (DIAG_CONTENT_AUDIO and normal path). At frame 387220: audio underflow (AUDIO_UNDERFLOW_SILENCE), silence injected; video still obtained. At frame 387221: video underflow (INV-VIDEO-LOOKAHEAD-001), then loop exit. So last successful *video* frame emission is 387220; `frames_emitted=387221` at exit means one more frame count after that (the code path that breaks does not emit frame 387221).
- **First underflow event:** `AUDIO_UNDERFLOW_SILENCE frame=387220` (line 42941).
- **Did fallback fire?** No log line in this file contains `fallback`. Audio underflow path injects silence (comment in code: “fallback tick”); no separate “fallback” log.

---

## Teardown trigger

- **What log line directly precedes CLEANUP_DEFERRED_FILL_BEGIN (teardown)?**  
  `[PipelineManager] INV-VIDEO-LOOKAHEAD-001: UNDERFLOW frame=387221 buffer_depth=0 total_pushed=513 total_popped=513`

- **What code path sets reason=stopped?**  
  - **Video underflow:** In `PipelineManager.cpp`, when `TryGetFrame` fails and the audio source was primed, the code logs `INV-VIDEO-LOOKAHEAD-001: UNDERFLOW`, then `ctx_->stop_requested.store(true, std::memory_order_release)` and `break` (lines 1470–1477).  
  - **Loop exit:** The main tick loop exits due to that `break`.  
  - **TEARDOWN (lines 2616–2635):** After the loop, `if (ctx_->stop_requested.load(...) && termination_reason == "unknown")` then `termination_reason = "stopped"` (lines 2619–2621). Then `CLEANUP_DEFERRED_FILL_BEGIN tick=teardown context=teardown` is logged (line 2627).  
  - **Session end:** Later, `Thread exiting: frames_emitted=..., reason=stopped` (2771–2774) and `callbacks_.on_session_ended(termination_reason, ...)` (2776–2778). Core/playout_service then emits `EmitSessionEnded` with that reason (playout_service.cpp 1290, 1305).  
  So: **Video underflow → set stop_requested and break → TEARDOWN → set termination_reason = "stopped" (when still "unknown") → CLEANUP_DEFERRED_FILL_BEGIN (teardown) → Thread exiting reason=stopped → EmitSessionEnded(reason=stopped).**

---

## Preliminary observations (factual only, no root-cause speculation)

1. There is a single session in the log; it ends with `reason=stopped` at lines 42961–42962.
2. First and only `AUDIO_UNDERFLOW_SILENCE` in the session is at frame 387220 (line 42941); buffer_depth_ms=21, needed=1600, a_src_primed=1.
3. On the very next tick (387221), video lookahead underflow is logged: buffer_depth=0, total_pushed=513, total_popped=513. 513 = 387221 − 386708 (tick of SEGMENT_TAKE_COMMIT to segment 10).
4. Segment swap to segment 10 (Visa - Olympics) occurred at tick 386708; ~17s of wall time (DIAG wall_ms from ~500 to ~17529) and 513 frames later, video buffer is exhausted and audio had already underflowed once (387220).
5. The log line immediately before `CLEANUP_DEFERRED_FILL_BEGIN tick=teardown context=teardown` is the VIDEO UNDERFLOW line.
6. `reason=stopped` is set in PipelineManager during TEARDOWN when `stop_requested` is true and `termination_reason` is still `"unknown"`; the only setter of `stop_requested` in the tick loop that leads to this exit is the video underflow path (PipelineManager.cpp 1476–1477).
7. No `INV-BLOCK-WALLFENCE`, `remaining_block_frames`, `INV-TICK-GUARANTEED-OUTPUT`, `fallback`, `freeze`, `black`, `stopping AIR`, `StopChannel`, `OutputClock`, or `Producer state change` appear in the extracted window in this log.
8. Last HEARTBEAT before underflow: frame=387000; refill=32.56fps, video=25/30, audio=814ms/1000ms.

---

## Extraction: SEGMENT_EOF, decoder_ok, DecodeNextFrameRaw, block_ct_ms_, segment boundary

**Search results (full log):**

- **SEGMENT_EOF:** 76 occurrences. Format: `[TickProducer] SEGMENT_EOF segment_index=0 asset_uri=... block_ct_ms=<ms> block_id=...`. No `SEGMENT_EOF` for Visa - Olympics (1988).mp4 in this log.
- **decoder_ok=false:** No matches. Every `Block assigned:` line has `decoder_ok=true`.
- **DecodeNextFrameRaw returned nullopt:** No matches in log.
- **block_ct_ms_:** No matches (log uses `block_ct_ms=` in SEGMENT_EOF, not `block_ct_ms_`).
- **segment boundary:** No literal "segment boundary" phrase. Segment-related logs: SEGMENT_TAKE_COMMIT, SEGMENT_SEAM_TAKE, SEGMENT_SWAP_POST, SEGMENT_PREP_ARMED, SEGMENT_SWAP_DEFERRED, SEGMENT_DECODER_OPEN (see Timeline above).

---

## Answers to specific questions

### Last log line referencing the Visa - Olympics asset

**Line 42867:**

```
[PipelineManager] SEGMENT_TAKE_COMMIT tick=386708 from_segment=9 to_segment=10 (CONTENT) is_pad=0 segment_b_audio_depth_ms=853 segment_b_video_depth_frames=25 audio_depth_ms=853 audio_gen=0 asset=/mnt/data/Filler/Commercials/Visa - Olympics (1988).mp4 seg_b_ready=1
```

All Visa - Olympics references in the log (chronological):

| Line   | Log |
|--------|-----|
| 28305  | [METRIC] asset_open_input_ms=21 uri=.../Visa - Olympics (1988).mp4 |
| 28306  | [METRIC] asset_stream_info_ms=3 uri=.../Visa - Olympics (1988).mp4 |
| 28307  | [RealAssetSource] Probed: .../Visa - Olympics (1988).mp4 (30196ms) |
| 41403  | [METRIC] asset_open_input_ms=5 uri=.../Visa - Olympics (1988).mp4 |
| 41404  | [METRIC] asset_stream_info_ms=2 uri=.../Visa - Olympics (1988).mp4 |
| 41405  | [RealAssetSource] Probed: .../Visa - Olympics (1988).mp4 (30196ms) |
| 41406  | [FFmpegDecoder] Opening: .../Visa - Olympics (1988).mp4 |
| 41410  | [FFmpegDecoder] DECODER_STEP open_input OK uri=.../Visa - Olympics (1988).mp4 720x480 @ 29.97 fps |
| 41411  | [TickProducer] SEGMENT_DECODER_OPEN block_id=blk-27876a6566d2 segment_index=0 asset_uri=.../Visa - Olympics (1988).mp4 ... |
| 41413  | [TickProducer] INV-BLOCK-PRIME-001: primed frame 0 ... asset=.../Visa - Olympics (1988).mp4 |
| **42867** | **[PipelineManager] SEGMENT_TAKE_COMMIT ... asset=.../Visa - Olympics (1988).mp4 seg_b_ready=1** |

No later line mentions Visa - Olympics. Session tore down at frame 387221 without reaching SEGMENT_EOF for that asset.

---

### Last decoder activity before frame 387221

- **Explicit decoder log lines:** Last FFmpegDecoder line before underflow (before 42941) that refers to the **live** path is the decoder that was opened for Visa at 41406 (DECODER_STEP open_input OK). After the swap at 386708, there are no further `[FFmpegDecoder] Opening:` or `[FFmpegDecoder] DECODER_STEP` lines for Visa; the next decoder line in the window is at 42877 `[FFmpegDecoder] Closing decoder` (one of the decoders closed during segment-swap cleanup), then 42861–42865 opening Toys-Queasy Bake.mkv for **next** segment prep.
- **Fill-loop activity (decoder consumption):** Last activity that implies the live decoder still decoding is:
  - **42919** `[PipelineManager] HEARTBEAT frame=387000 ... refill=32.5586fps decode_p95=3444us ...`
  - **42940** `[PipelineManager] DIAG_CONTENT_AUDIO tick=387210 ... a_src_depth_ms=321 ...` (real audio from decoder).
  - **42946** `[DIAG-H2-SUMMARY:LIVE_AUDIO_BUFFER] ... ticks=513 decodes=513 ...` (after STOP_FILLING: 513 decodes on LIVE_AUDIO_BUFFER over the segment).

So the last decoder-related evidence before frame 387221 is HEARTBEAT at frame=387000 (refill=32.56fps, decode_p95=3444us) and DIAG_CONTENT_AUDIO at tick=387210 (a_src_depth_ms=321). No per-frame "DecodeNextFrameRaw" or "DECODER_STEP" lines appear in the log for the live decoder in that range.

---

### Was there a SEGMENT_EOF?

**For Visa - Olympics: No.** There is no `SEGMENT_EOF` line for `Visa - Olympics (1988).mp4` in the log. The session ended at frame 387221 (video underflow then teardown) before the segment could complete. The last `SEGMENT_EOF` in the session is line 41013 for Pacific Bell - Cellular Service.mp4 (block blk-27876a6566d2, segment before Visa in the same block).

**In the session overall:** Yes — 76 SEGMENT_EOF lines for other assets (each with `block_ct_ms=<value>`, no `block_ct_ms_`).

---

### Was decoder_ok ever set false?

**No.** Every `Block assigned:` line in the log has `decoder_ok=true`. There are no occurrences of `decoder_ok=false` in `cheers-24-7-air.log`.

---

## SegmentBoundary computation (for segment 10 / Visa - Olympics investigation)

### Code location that computes SegmentBoundary values

- **Function:** `BlockPlanValidator::ComputeBoundaries(const BlockPlan& plan)`
- **File:** `pkg/air/src/blockplan/BlockPlanValidator.cpp`, lines 198–236.

Logic:

- Sorts `plan.segments` by `segment_index`.
- For each segment: `bound.start_ct_ms = ct` (running CT), `bound.end_ct_ms = ct + seg->segment_duration_ms`, then `ct = bound.end_ct_ms`.
- So **start_ct_ms** and **end_ct_ms** are derived solely from the previous segment’s end and the current segment’s **segment_duration_ms**.

### What it uses as its duration source

- **Source:** `BlockPlan::Segment::segment_duration_ms` (i.e. `seg->segment_duration_ms` in `ComputeBoundaries`).
- **Origin of that value:** The `BlockPlan` is produced by `FedBlockToBlockPlan(FedBlock)`, which copies `FedBlock::Segment::segment_duration_ms` from the block fed by Core. So the duration used for boundaries is the **scheduled segment duration** from Core, not ffprobe/media duration. Validation uses an `asset_duration_fn` for existence and offset checks but does **not** store or use asset duration for boundary computation.

### Where live_boundaries_ comes from

- `live_boundaries_` is set from `AsTickProducer(live_.get())->GetBoundaries()` (PipelineManager.cpp: 913, 1767, 2531).
- TickProducer’s `boundaries_` is set in `AssignBlock()` from `validated_.boundaries`, and `validated_.boundaries` is the result of `BlockPlanValidator::Validate(plan, 0).boundaries`, which calls `ComputeBoundaries(plan)`.

So for block `blk-27876a6566d2`, segment 10’s boundary is exactly what `ComputeBoundaries` produced from that block’s segment 10 `segment_duration_ms`.

### Whether segment 10 boundary duration is ~17100 ms

- **Not observable from the existing log:** Boundary values are not printed for this session. The new logging (`SEGMENT_BOUNDARY_AT_ACTIVATION`, `ARM_SEGMENT_PREP_SYNTH`) will show `dur_ms` and `boundary start_ct_ms/end_ct_ms` for each segment at block activation and when arming segment prep.
- **Interpretation:** 513 frames at 30 fps ⇒ 513 × (1000/30) ms = **17 100 ms**. If segment 10’s **boundary** duration were ~17 100 ms, the seam would occur at that point and the lookahead would be sized for 513 frames, which matches the observed `total_pushed=513 total_popped=513` at underflow. So a **~17100 ms** segment 10 boundary is **consistent** with the observed 513-frame run; to confirm, run with the new logging and inspect `SEGMENT_BOUNDARY_AT_ACTIVATION` and `ARM_SEGMENT_PREP_SYNTH` for block `blk-27876a6566d2` and segment index 10.
