# Fence black frames: natural rollover vs JIP

## Observed behavior

- **Natural block transition (A → B at fence):** produces black frames.
- **Stop + restart (JIP) into the same block:** works (real frames immediately).
- Tier-2 rows valid, no Tier-2 miss, feed-ahead healthy — not a scheduling issue.

## One-sentence root cause

**Natural rollover does not produce real frames at the fence because the tick loop never waits for the preview (B) video lookahead buffer to be primed before the fence tick — the content-before-pad gate (INV-PAD-PRODUCER-007) only skips ticks before the first real frame is committed; JIP opens and primes the first block synchronously before the first tick and can skip ticks until the live buffer is primed, so real frames are available immediately.**

## Delta: natural rollover vs JIP

| Aspect | Natural rollover (A → B at fence) | JIP (start into block B) |
|--------|-----------------------------------|---------------------------|
| Block B load | SeamPreparer worker: AssignBlock + PrimeFirstTick async | TryLoadLiveProducer: AssignBlock + PrimeFirstTick sync before clock |
| Decoder open/seek | In worker; producer returns with kReady | Same (TickProducer), before first tick |
| PrimeFirstTick | Done in SeamPreparer (audio + internal primed frames) | Done in Run() before main loop |
| Lookahead buffer | New preview_video_buffer_ created when we TakeBlockResult; StartFilling runs async | video_buffer_ created once; StartFilling before first tick |
| Wait for buffer primed? | No — at fence we always emit a frame (pad if B buffer not primed) | Yes — INV-PAD-PRODUCER-007 can skip ticks until video_buffer_ primed (only before first_real_frame_committed) |
| Result at first tick | If fill thread hasn’t filled B buffer by fence tick → pad | Buffer primed or we skip ticks → real frame |

## Instrumentation added (PipelineManager)

- **FENCE_TRANSITION:** at fence tick: current_block_id, next_block_id, next_block_fed, producer_state, decoder_state, first_seg_asset_uri.
- **PRE_FENCE_TICK:** one tick before fence: next_block_id, next_block_opened, first_seg_asset_uri, next_fed.
- **PREROLL_ARMED:** first_seg_asset_uri when block prep is submitted.
- **PREROLL_STATUS:** next_block_opened, first_seg_asset_uri, decoder_used when we take block result.
- **FENCE_PAD_CAUSE:** when pad at fence: cause (no_preview_buffers / buffer_not_primed / buffer_empty_after_primed), segment_type_first_seg, decoder_returned_empty.
- **SESSION_FIRST_BLOCK:** JIP path: block, decoder_opened, prime_done_before_clock, StartFilling_called.

SeamPreparer already logs **PREP_COMPLETE** with decoder_used and audio_depth_ms (decoder open + prime in worker).

## Block identity and preroll failure (blk-782b scenario)

### New logs (block identity and failure)

- **PREROLL_SUBMIT block_id=...** — emitted when a block is submitted to SeamPreparer (TryKickoffBlockPreload). Confirms which block was requested for the upcoming fence.
- **PREROLL_TAKE_RESULT block_id=... segment_type=... decoder_used=Y|N** — emitted when we take the block result (TryTakePreviewProducer). Confirms which block the result is for and whether it has a decoder.
- **PREROLL_DECODER_FAILED block_id=...** — emitted in SeamPreparer when a *content* block completes with no decoder (open/seek failed), and again in PipelineManager when we take such a result and discard it (so we do not set preview_; next_block_opened stays 0).

### Job ownership and buffer reuse

- **Single block result slot:** SeamPreparer has one `block_result_`. We do not submit the next block prep until `HasBlockResult()` is false (i.e. we have taken the current result). So the result we take is always for the block we last submitted; a later block cannot overwrite the current B’s result before we take it.
- **PREVIEW buffers:** One `preview_video_buffer_` and one `preview_audio_buffer_` per “current” preview block. They are created when we first take a block result and assign to `preview_`, and are moved to live (B→A) at the fence. They are not reused for multiple future blocks; each new preview gets new buffers when we take the next result.
- **Zombie rejection:** If the taken result is a content block with no decoder, we now log PREROLL_DECODER_FAILED and return nullptr, so we do not set `preview_` (next_block_opened=0) and avoid a “opened but no_decoder” zombie.

### One-sentence root cause (next block selected but unprimed)

**blk-782b... can be selected as next at fence (next_block_id) and yet be unprimed (next_fed=0, decoder_state=no_decoder) because its preroll job completed with a producer that had no decoder (open or seek failed for that block in the SeamPreparer worker), so we took that result and set preview_ (next_block_opened=1) but the fill thread could not produce frames, leaving next_fed=0; later blocks preroll successfully because their decoder opens succeed, and with zombie rejection we now discard failed content results so next_block_opened=0 instead of leaving a no-decoder producer in preview_.**

To confirm in logs: blk-782b... should appear in **PREROLL_SUBMIT** and **PREROLL_TAKE_RESULT**; if decoder failed, **PREROLL_DECODER_FAILED** (worker and/or PipelineManager) will appear for that block_id.

## Horizon

No horizon logic was changed; diagnosis is decoder/producer and fence TAKE path only.
