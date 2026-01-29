# Last-Mile Pre-Publish Audit

**Purpose:** Evaluate potential gotchas before final publish of the refactor branch. This is a checklist, not a warning siren. Any items that need addressing are spelled out explicitly.

**Scope:** libav vs ffmpeg defaults, ProgramFormat contract, aspect policy, thread & lifetime ownership.

---

## 1. libav vs ffmpeg binaries — the REAL risk

**Question:** Are pixel format, color range, audio format, channel layout, and timebase **explicitly configured** in code, or are we relying on “whatever libav picks”?

### Findings

| Item | Status | Location / notes |
|------|--------|------------------|
| **Pixel format** | ✅ Explicit | FileProducer: `dst_format = AV_PIX_FMT_YUV420P`; EncoderPipeline: `AV_PIX_FMT_YUV420P` throughout. |
| **Color range** | ⚠️ **Not set** | No `color_range`, `color_primaries`, `color_transfer`, or `colorspace` set in `pkg/air/src` or `pkg/air/include`. We rely on libav/decoder defaults. |
| **Color primaries / transfer / matrix** | ⚠️ **Consciously ignored (implicit)** | Same as above. Acceptable for single-sink today; when adding a second sink or different delivery specs, mismatch risk increases. |
| **Audio sample format** | ✅ Explicit | FileProducer: handles `AV_SAMPLE_FMT_S16` and `AV_SAMPLE_FMT_FLTP` explicitly; EncoderPipeline: sets `AV_SAMPLE_FMT_FLTP` (or first codec-supported). |
| **Audio channel layout** | ✅ Explicit | EncoderPipeline: `av_channel_layout_from_mask(..., AV_CH_LAYOUT_STEREO)` (with fallback for 2 channels). |
| **Audio sample rate** | ⚠️ **Hardcoded in encoder** | EncoderPipeline: `audio_codec_ctx_->sample_rate = 48000` (line ~236). Not read from ProgramFormat. See §2. |
| **Timebase propagation** | ✅ Explicit | EncoderPipeline: video `time_base` 1/fps, stream 1/90000; audio time_base 1/sample_rate. FileProducer: uses stream `time_base` from source for PTS→us. |

### Verdict

- **If these are explicit in code → you're good.** Video pixel format, audio format/channel layout, and timebase are explicit.
- **If you're relying on “whatever libav picks” → you'll regret it later when you add a second sink.**  
  **Risk:** Color range / primaries / transfer / matrix are **not** set. We are implicitly using decoder/default behavior. For a single pipeline and 1080p30 broadcast, this is survivable. Before adding another sink or strict delivery specs (e.g. BT.709, limited vs full range), add explicit setting (e.g. on decoder output and/or encoder input) and document the choice.

**Recommendation:** Before merge, either (a) document “color metadata: currently decoder/default; formalize when adding second sink,” or (b) add a one-page “libav defaults to hunt for” list and tick off color_range/primaries/transfer in a follow-up. No block for current single-sink publish.

---

## 2. ProgramFormat contract — did it actually land everywhere?

**Invariant:** There is exactly **one** authoritative ProgramFormat per PlayoutInstance.

### Paths checked

| Path | Status | Notes |
|------|--------|--------|
| **PlayoutInstance** | ✅ | Single `ProgramFormat program_format` per instance; set at StartChannel from JSON; fixed for instance lifetime. |
| **FileProducer** | ✅ | Does not decide output format. Gets `target_width`, `target_height`, `target_fps` from ProducerConfig filled by PlayoutEngine from `state->program_format`. |
| **ProgramOutput** | ✅ | Does not enforce scale/aspect/frame rate; consumes frames. Format is enforced upstream (FileProducer). |
| **OutputSink (MpegTSOutputSink)** | ✅ | Consumes ProgramFormat: playout_service passes `program_format.GetFrameRateAsDouble()`, `program_format.video.width`, `program_format.video.height` into `MpegTSPlayoutSinkConfig`. |
| **EncoderPipeline** | ⚠️ **Audio not from ProgramFormat** | Video: `target_width` / `target_height` / `target_fps` from config (ProgramFormat). **Audio:** `sample_rate = 48000` and stereo are **hardcoded** in EncoderPipeline. `MpegTSPlayoutSinkConfig` has no `target_sample_rate` or `target_channels`. |

### Verdict

- **One authoritative ProgramFormat per PlayoutInstance:** ✅ Holds.
- **FileProducer → reads source format but does not decide output format:** ✅ Uses ProgramFormat-derived config.
- **ProgramOutput → does not invent format:** ✅ Pass-through.
- **OutputSink → consumes ProgramFormat (video):** ✅ Video path uses ProgramFormat.
- **EncoderPipeline → no hardcoded width/height:** ✅ Width/height come from config (ProgramFormat). **But** encoder audio sample rate and channel count are still hardcoded; they do not follow ProgramFormat.audio.

**Recommendation:** Treat as **technical debt, not a merge block**. Current ProgramFormat JSON and Core usage use 48 kHz stereo; behavior is consistent. Before supporting non-48k or non-stereo program formats, add `target_sample_rate` and `target_channels` (or equivalent) to sink/encoder config and wire from ProgramFormat. The 640×480 bug fix (ProgramFormat-driven video dimensions) was the canary; audio is the remaining gap.

---

## 3. Aspect ratio — policy implicit but consistent

**Question:** Is there one consistent behavior (Preserve DAR / crop / stretch), and do we avoid different sinks doing different things?

### Findings

- **AspectPolicy** exists: `Preserve`, `Stretch`, `Crop` (Crop future). Default is **Preserve**.
- **FileProducer:** Uses `AspectPolicy::Preserve`: scale to fit, letterbox/pillarbox to ProgramFormat dimensions. No stretch.
- **EncoderPipeline:** Receives frames already at ProgramFormat dimensions (from FileProducer). It may scale only when input size differs from opened codec size; it does not define aspect policy.
- **Stretch:** Explicitly rejected in producer; only used if policy were set to Stretch (not default).

### Verdict

- **One implicit policy:** Preserve DAR, letterbox/pillarbox. ✅  
- **Formalizing policy later:** Acceptable; code is consistent.  
- **Different sinks doing different things:** Avoided; single producer path, single scaling policy. ✅  

No change required before publish.

---

## 4. Thread & lifetime ownership — quiet but critical

**Question:** Is the ownership graph correct, and can any thread outlive PlayoutInstance shutdown?

### Ownership graph (verified in code)

| Owner | Owns | Notes |
|-------|------|--------|
| **PlayoutInstance** | ProgramOutput, OutputBus, TimingLoop, PlayoutControl, ring_buffer, live_producer, preview_producer | All `unique_ptr` or value; cleared in StopChannel. |
| **OutputBus** | Zero or one OutputSink (`sink_`, `unique_ptr<IOutputSink>`) | DetachSink(true) calls `sink_->Stop()` then `sink_.reset()`. |
| **OutputSink (MpegTSOutputSink)** | EncoderPipeline, mux_thread_ | Stop() joins mux_thread_, then closes encoder. Destructor calls Stop(). |
| **gRPC layer (PlayoutControlImpl)** | stream_states_ (FD, hello_thread) | Does **not** own PlayoutInstance or OutputBus. |

### Teardown order (PlayoutEngine::StopChannel)

1. **Control:** `state->control->Stop(...)`
2. **OutputBus:** `state->output_bus->DetachSink(true)` → sink->Stop() (joins MuxLoop), sink_.reset()
3. **ProgramOutput:** `state->program_output->Stop()` (stops consumer thread)
4. **Producers:** RequestTeardown, wait until not running, stop(), reset()
5. **Ring buffer:** drain and Clear()
6. **State:** channels_.erase(it)

### Verdict

- PlayoutInstance owns ProgramOutput, OutputBus, TimingLoop; OutputBus owns at most one OutputSink; OutputSink owns EncoderPipeline and worker thread(s). ✅  
- gRPC layer owns no long-lived engine objects. ✅  
- Teardown order: detach sink first (sink stops and joins its thread), then program output, then producers, then buffer. No thread outlives PlayoutInstance shutdown. ✅  

**Green light** for thread and lifetime ownership.

---

## Summary table

| Area | Status | Action before publish |
|------|--------|----------------------|
| 1. libav defaults | ⚠️ Color metadata implicit | Document or add “defaults to hunt for” list; optional follow-up to set color_range/primaries/transfer. |
| 2. ProgramFormat | ⚠️ Audio not in encoder config | Document as tech debt; wire ProgramFormat.audio when adding non-48k/non-stereo. |
| 3. Aspect policy | ✅ Consistent | None. |
| 4. Thread & lifetime | ✅ Correct | None. |

**Conclusion:** Safe to publish. The only “must” is to **document** the two ⚠️ items (color defaults, ProgramFormat audio gap) so they are not forgotten when adding a second sink or new program formats. No mandatory code change for this publish.
