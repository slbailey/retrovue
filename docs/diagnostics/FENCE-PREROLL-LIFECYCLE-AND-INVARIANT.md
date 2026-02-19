# Fence preroll lifecycle, decoder failure steps, and INV-FENCE-TAKE-READY-001

## 1. Ordered logs for a block that goes black at fence

For a given `block_id` (e.g. blk-782b...), the **preroll lifecycle** produces this ordered sequence when things work or fail:

| Order | Log | Where | Meaning |
|-------|-----|--------|--------|
| 1 | **PREROLL_SUBMIT block_id=...** | PipelineManager (TryKickoffBlockPreload) | Block submitted to SeamPreparer for upcoming fence |
| 2 | **PREROLL_WORKER_START block_id=...** | SeamPreparer (ProcessRequest) | Worker began processing this block |
| 3 | **DECODER_STEP block_id=... step=probe \| validation \| open \| seek result=...** | TickProducer (AssignBlock) | Exact stage in decoder init; on failure, step and result identify where it broke |
| 3b | **FFmpegDecoder DECODER_STEP open_input \| avformat_find_stream_info \| find_video_stream \| initialize_codec \| initialize_scaler \| packet_alloc \| seek FAILED ret=... err=...** | FFmpegDecoder | FFmpeg error code and message for that step |
| 4 | **SEGMENT_DECODER_OPEN block_id=...** | TickProducer (AssignBlock) | Decoder opened and seeked successfully (only on success path) |
| 5 | **INV-BLOCK-PRIME-001: PrimeFirstTick ...** or **INV-AUDIO-PRIME-001: wallclock timeout** | TickProducer (PrimeFirstTick) | First decode + audio prime result |
| 6 | **PREROLL_WORKER_PRIME block_id=... first_decode_ok=Y/N audio_depth_ms=...** | SeamPreparer (ProcessRequest) | Worker finished prime for this block |
| 7 | **PREP_COMPLETE type=block block=... decoder_used=...** or **PREROLL_DECODER_FAILED block_id=...** | SeamPreparer (ProcessRequest) | Block result stored; decoder_used=false for content => PREROLL_DECODER_FAILED |
| 8 | **PREROLL_TAKE_RESULT block_id=... segment_type=... decoder_used=Y/N** | PipelineManager (TryTakePreviewProducer) | Tick loop took the result; decoder_used=N => zombie discarded |
| 8b | **PREROLL_DECODER_FAILED ... discarding_result** and optionally **PREROLL_RETRY block_id=...** | PipelineManager (TryTakePreviewProducer) | Content block with no decoder discarded; retry once if headroom ≥ 2000ms |
| 9 | **PRE_FENCE_TICK ... next_block_id=... next_fed=...** | PipelineManager (tick loop) | One tick before fence; next_block_opened and next_fed |
| 10 | **FENCE_TRANSITION ... next_block_id=... next_block_fed=... decoder_state=...** | PipelineManager (tick loop) | At fence tick |
| 11 | **FENCE_PAD_CAUSE ...** or real frame commit | PipelineManager (tick loop) | Pad cause if B not primed |
| 12 | **INV-FENCE-TAKE-READY-001 VIOLATION** (if content-first and pad) | PipelineManager (tick loop) | Assert + structured log |

**Conclusion from timeline:** If decoder truly failed, you will see **DECODER_STEP ... result=fail** (and/or FFmpegDecoder **DECODER_STEP ... FAILED**) for that block_id before **PREROLL_TAKE_RESULT decoder_used=N**. If you see **PREROLL_TAKE_RESULT block_id=blk-782b decoder_used=N** but **no** DECODER_STEP failure for that block, the "decoder failed" hypothesis is wrong and the cause is scheduling/state (e.g. wrong result taken, or worker never ran for that block).

---

## 2. Exact decoder failure step

**FFmpegDecoder** now logs each step with result and, on failure, **ret** and **err** (av_strerror):

- **open_input** — `avformat_open_input` result
- **avformat_find_stream_info** — `avformat_find_stream_info` result
- **find_video_stream** — no video stream
- **initialize_codec** — codec init failed
- **initialize_scaler** — scaler init failed
- **packet_alloc** — `av_packet_alloc` failed
- **seek** — `av_seek_frame` result (in SeekToMs)

**TickProducer** logs:

- **DECODER_STEP block_id=... step=probe result=fail** — asset probe failed
- **DECODER_STEP block_id=... step=validation result=fail detail=...** — BlockPlanValidator failed
- **DECODER_STEP block_id=... step=open result=fail** — decoder_->Open() returned false (see FFmpegDecoder for stage)
- **DECODER_STEP block_id=... step=seek result=fail** — SeekPreciseToMs failed

**Deliverable:** One-sentence explanation: *"Decoder failed at step &lt;X&gt; due to &lt;Y&gt;."* — X is the last DECODER_STEP or FFmpegDecoder step that failed; Y is the err string or detail. If no such failure is logged for that block_id, the decoder-failure hypothesis is incorrect.

---

## 3. JIP works, natural rollover fails — why?

**JIP path (same asset):**

- Block is loaded in **Run()** before the main loop: **TryLoadLiveProducer()** from queue → **AssignBlock** (same TickProducer/FFmpegDecoder path) → **PrimeFirstTick** (sync) → **StartFilling**.
- **SESSION_FIRST_BLOCK** logs decoder_opened, prime_done_before_clock=Y, StartFilling_called=Y.
- No SeamPreparer worker; no async timing. Decoder open + seek + prime run to completion before the first tick.

**Natural rollover path:**

- Block is submitted in **TryKickoffBlockPreload** (PREROLL_SUBMIT) and processed by **SeamPreparer** worker: AssignBlock + PrimeFirstTick in worker thread.
- Result is taken in the tick loop when **HasBlockResult()**; then **StartFilling** for preview buffers (fill thread runs async).
- Fence tick can arrive before the preview fill thread has pushed enough frames into the buffer (**next_fed=0**).

**Why same asset can succeed in JIP but fail at fence:**

1. **Decoder really fails only in worker** — e.g. open/seek fails under worker timing (resource contention, different thread, interrupt callback). Then DECODER_STEP/PREROLL_DECODER_FAILED will appear for that block; JIP path never hits that context.
2. **State/timing, not asset** — Worker completed successfully (decoder_used=Y, PREP_COMPLETE), but the result was taken late or preview buffer never primed in time (scheduling). Then PREROLL_TAKE_RESULT shows decoder_used=Y; FENCE_TRANSITION shows next_fed=0. So the issue is priming lag / buffer not ready at fence, not decoder failure.

If **JIP consistently succeeds** for the same asset, the problem is almost certainly **state/timing** (priming lag or take timing), not asset/decoder failure. The new DECODER_STEP and PREROLL_* logs tell you which.

---

## 4. INV-FENCE-TAKE-READY-001

**Invariant:** At the fence tick, if the next block’s first segment is CONTENT, the system must satisfy at least one:

- Preview buffer primed to required threshold, or  
- Explicit fallback source engaged (never raw black).

It must **never** take PAD for a content-first block due to priming lag.

**Enforcement:**

- When we are about to emit PAD for slot B at the fence, we check whether the next block is content-first (from preview_ or, if discarded, from **expected_preroll_first_seg_content_**).
- If yes: we log **INV-FENCE-TAKE-READY-001 VIOLATION** with tick, fence_tick, next_block_id, cause, and **assert(false)**.
- No tick skipping, no wallclock change, no delayed fence, no silence-only mask. The assert forces fixing the root cause (priming or fallback), not masking with black.

---

## 5. Retry behavior

- When **TryTakePreviewProducer** discards a result (content block, no decoder), it checks **headroom_ms** (fence frame − current frame, converted to ms).
- If **headroom_ms ≥ 2000** and we have **last_submitted_block_** for that block and have not already retried that block_id (**retry_attempted_block_id_**), we **re-submit** the same block once and log **PREROLL_RETRY block_id=... headroom_ms=...**.
- Second attempt runs in SeamPreparer; if it fails again we do not retry again for that block_id (we escalate to fallback: PADDED_GAP or sync queue drain).
- Retry does not change fence timing or skip ticks; it only gives the worker one more chance to open/prime the same block before the fence.

---

## 6. Preview ownership

- **expected_preroll_block_id_** is set when we **Submit** in TryKickoffBlockPreload (the block we expect at the next fence).
- At the fence (take_b && !take_rotated), if **preview_** is non-null we check **next_block_id == expected_preroll_block_id_**. If they differ we log **PREROLL_OWNERSHIP_VIOLATION expected=... actual_next=...**.
- Preview buffers are not reassigned to a “deeper” lookahead; one preview slot per fence. Single **block_result_** in SeamPreparer; we do not submit the next block until we take, so the result we take is always for the block we last submitted.

---

## Final deliverable (one paragraph)

**Was this truly a decoder failure or a scheduling/state issue?**  
If for the failing block_id you see **DECODER_STEP ... result=fail** (or FFmpegDecoder **DECODER_STEP ... FAILED**) and **PREROLL_DECODER_FAILED**, then the decoder did fail at a specific step (open_input, seek, etc.); the one-sentence explanation is “Decoder failed at step X due to Y” from those logs. If you see **PREROLL_TAKE_RESULT decoder_used=N** but **no** DECODER_STEP failure for that block_id, then the block either never reached the worker for that id (scheduling/identity) or the result was a zombie for another reason (state); in that case it is a scheduling/state machine issue, not a proven decoder failure.

**What change makes natural rollover as deterministic as JIP?**  
(1) **INV-FENCE-TAKE-READY-001** makes it impossible to take PAD for a content-first block at the fence without asserting — so we must either prime B in time or engage an explicit fallback. (2) **Zombie rejection** prevents a no-decoder producer from being used as preview (next_block_opened=0), so we don’t pretend B is ready when it isn’t. (3) **One retry** when headroom ≥ 2000ms gives the worker one more chance to open/prime the same block. (4) **Exact DECODER_STEP and PREROLL_* logging** proves whether the failure was decoder (step X, err Y) or timing/ownership.

**How does the system ensure no black at take without skipping ticks?**  
By enforcing INV-FENCE-TAKE-READY-001: we never allow “take PAD for content-first B due to priming lag.” If B is content-first and not primed, we hit the assertion and must fix the cause (earlier priming, worker completing in time, or explicit sync fallback path). We do not skip ticks, delay the fence, or mask with silence-only pad; the invariant forces a deterministic, broadcast-grade take model.
