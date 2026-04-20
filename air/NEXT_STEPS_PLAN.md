# AIR vNext — Next Steps: Inventory-Then-Plan

Status: planning doc, 2026-04-20. Successor to CHECKPOINT.md's "Next-step options" section. **Amended 2026-04-20** to reflect product decisions and org-chart model finalized in conversation (see memory files `project_retrovue_air_product_decisions`, `project_retrovue_air_org_chart`, `project_retrovue_air_execution_discipline`, `feedback_broadcast_vocabulary`).
Scope: `air/` only. `runtime/` used as reference and vocabulary source; no code changes to it.

## Preamble: vocabulary

Vault-authoritative names (from `/opt/retrovue-obsidian/Retrovue/00_components/`) used below:

PlaybackDirector, ReadinessController, BootstrapContentGate, PacingController, SeamController,
SourceProducer, Normalizer, BufferStore, Clock, AIR_Pipeline, AIR_Boundary,
AIR_Runtime, AIR_Lifecycle, AIR_Observability.

The vault explicitly assigns "mux / output byte production" to **AIR_Pipeline**. There is no separate vault component named "Encoder," "Muxer," or "OutputSink" — those are mechanisms executing AIR_Pipeline's emission, not authority owners. The transport contract across which bytes leave AIR is owned by **AIR_Boundary**.

Per `00_components/CLAUDE.md`: the vault is the source of truth; where it is silent, findings are classified as gaps rather than speculation.

---

## Section 1 — Runtime pipeline inventory (scheduled block → UDP socket)

Trace of a scheduled program block through `/opt/retrovue/runtime/` end-to-end. Files are absolute paths. This is the reference model; it is NOT what `air/` will build verbatim.

### 1.1 Process / gRPC entry
- **Binary entry + signal handling** — `/opt/retrovue/runtime/src/main.cpp`. Sets up crash/shutdown signals, FFmpeg global init (`avformat_network_init`), constructs `MasterClock` from system time, builds `PlayoutEngine`, `PlayoutInterface`, `PlayoutControlImpl` gRPC service, listens on `0.0.0.0:50051`, starts Prometheus-format metrics on `:9308`.
- **gRPC service adapter** — `/opt/retrovue/runtime/src/playout_service.cpp` (`PlayoutControlImpl`, 1619 lines). RPCs: `StartChannel`, `AttachStream`, `LoadPreview`, `SwitchToLive`, `StopChannel`, `StartBlockPlanSession`, `FeedBlockPlan`, `StopBlockPlanSession`, `SubscribeBlockEvents`, `UpdatePlan`, `GetVersion`. Evidence pipeline + forensic-dump hookup lives here.
- **Domain interface** — `/opt/retrovue/runtime/include/retrovue/runtime/PlayoutInterface.h` (+ `.cpp`). Thin wrapper over `PlayoutEngine`.

### 1.2 Session authority
- **PlayoutEngine** — `/opt/retrovue/runtime/include/retrovue/runtime/PlayoutEngine.h` + `runtime/src/runtime/PlayoutEngine.cpp` (2187 lines). Single-session execution authority. Holds `channels_` map (legacy multi-channel hangover), `PlayoutInstance` struct, `SwitchWatcher` thread, deadline-driven `ExecuteSwitchAtDeadline`, `Register{Mux,MuxAudio}FrameCallback` bridge to mux.
- **PlayoutControl state machine** — `/opt/retrovue/runtime/src/runtime/PlayoutControl.cpp`. Preview/live atomic switch states.
- **PlayoutController** — `/opt/retrovue/runtime/src/runtime/PlayoutController.cpp`. Wires control surface into ProducerBus.
- **ProducerBus** — `/opt/retrovue/runtime/src/runtime/ProducerBus.cpp` (26 lines, thin). Tracks LIVE vs PREVIEW producer.

### 1.3 Block-plan session (the path actually used for scheduled playout)
- **PipelineManager** — `/opt/retrovue/runtime/include/retrovue/blockplan/PipelineManager.hpp` + `.cpp`. The de facto current-state realization of PlaybackDirector + AIR_Pipeline. Owns:
  - Active + pending producers (blockplan "A" and "B" slots).
  - The 9-branch TAKE cascade (`SelectCascadeBranch`: PAD_SEAM_OVERRIDE → CONTENT_SEAM_OVERRIDE → CADENCE_REPEAT → NORMAL_ADVANCE → BLOCK_FENCE → SEGMENT_SEAM_HOLD → GENUINE_UNDERFLOW → PRIMED_NO_DECODER → NOT_PRIMED).
  - The bootstrap content gate call site.
  - The per-tick Run() loop.
- **SeamPreparer** — `/opt/retrovue/runtime/src/blockplan/SeamPreparer.cpp`. Prepares the "B" producer ahead of seam.
- **ProducerPreloader** — `/opt/retrovue/runtime/src/blockplan/ProducerPreloader.cpp`. Off-thread preload.
- **TickProducer** — `/opt/retrovue/runtime/src/blockplan/TickProducer.cpp`. Produces one tick's decoded frames on demand (wrapping the decoder).
- **FFmpegDecoderAdapter** — `/opt/retrovue/runtime/src/blockplan/FFmpegDecoderAdapter.cpp`. Adapts the common decoder into the TickProducer surface.
- **OutputClock** — `/opt/retrovue/runtime/src/blockplan/OutputClock.cpp`. Derives tick cadence + deadlines from MasterClock and channel fps.
- **Lookahead buffers** — `/opt/retrovue/runtime/src/blockplan/AudioLookaheadBuffer.cpp` and `VideoLookaheadBuffer.cpp`. Co-located pacing/admission logic that Vault's `PacingController` is meant to extract.
- **BroadcastAudioProcessor** (header-only in include path) — audio loudness/gain.

### 1.4 Bootstrap + readiness + seam
- **BootstrapContentGate** — `/opt/retrovue/runtime/src/bootstrap/BootstrapContentGate.cpp` + `BootstrapGateEvaluator.cpp`. Current-state vault-canonical kickoff authority. 19 contract tests.
- **ReadinessEvaluator/Observer** — `/opt/retrovue/runtime/src/readiness/ReadinessEvaluator.cpp` + `ReadinessObserver.cpp`. Signal consumption + verdict emission.
- **SeamController + SeamEvaluator** — `/opt/retrovue/runtime/src/seam/*.cpp`. Seam arming/firing/commit phases.

### 1.5 Decode + frame production
- **FFmpegDecoder** — `/opt/retrovue/runtime/src/decode/FFmpegDecoder.cpp` (1589 lines). Demux + decode for video and audio streams; frame offset seeking; producer-specific glue.
- **FrameProducer** — `/opt/retrovue/runtime/src/decode/FrameProducer.cpp`. Producer-side interface.
- **Producers (IProducer implementations)**:
  - `/opt/retrovue/runtime/src/producers/file/FileProducer.cpp` — real asset.
  - `/opt/retrovue/runtime/src/producers/black/BlackFrameProducer.cpp` — pad.
  - `/opt/retrovue/runtime/src/producers/programmatic/ProgrammaticProducer.cpp` — synthetic.
- **RealAssetSource** — `/opt/retrovue/runtime/src/blockplan/RealAssetSource.cpp`. Blockplan-session wrapper around FileProducer.

### 1.6 Buffers + selection + rendering
- **FrameRingBuffer** — `/opt/retrovue/runtime/src/buffer/FrameRingBuffer.cpp` + `FrameIndexedVideoStore.cpp`. Legacy live ring + the indexed video store referenced by emission.
- **FrameRenderer** — `/opt/retrovue/runtime/src/renderer/FrameRenderer.cpp`. Takes the selected frame each tick and hands it off.
- **ProgramOutput** — `/opt/retrovue/runtime/src/renderer/ProgramOutput.cpp` (1441 lines). Per-tick "commit a frame" authority that drives OutputBus. Holds the mux-callback connection and the connect/disconnect-to-OutputBus surface.
- **TimingLoop** — `/opt/retrovue/runtime/src/runtime/TimingLoop.cpp`. Deadline-driven tick loop; reports backpressure events; injects `MasterClock` for tick identity and skew metrics.
- **TimelineController** — `/opt/retrovue/runtime/src/timing/TimelineController.cpp`. Channel-monotonic timeline bookkeeping relative to MasterClock.
- **MasterClock** — `/opt/retrovue/runtime/src/timing/SystemMasterClock.cpp` (+ `TestMasterClock.cpp`). Single time authority; vault `Clock.md` maps to this in AIR space.

### 1.7 Encode + mux
- **OutputBus** — `/opt/retrovue/runtime/src/output/OutputBus.cpp`. Fan-in point from ProgramOutput; fan-out to attached IOutputSink.
- **IOutputSink** interface — `/opt/retrovue/runtime/include/retrovue/output/IOutputSink.h`. `Start/Stop/ConsumeVideo/ConsumeAudio/SetStatusCallback/GetStatus`. Explicitly says "Sink does NOT own engine state or channel concepts."
- **MpegTSOutputSink** — `/opt/retrovue/runtime/src/output/MpegTSOutputSink.cpp` (1608 lines). Wraps `EncoderPipeline` and `SocketSink`; enforces `O_NONBLOCK` on the fd; configures throttle-vs-detach policy; holds sink liveness counters; wires packet-capture into a `MuxInterleaver` for global-DTS-monotonic muxing.
- **EncoderPipeline** — `/opt/retrovue/runtime/src/playout_sinks/mpegts/EncoderPipeline.cpp` (2475 lines). Owns:
  - libx264/NVENC video encoder context (`AVCodecContext`), YUV420P input frame, `SwsContext` for pixel-format conversion if needed, IDR-before-output gate, per-segment video frame counter.
  - AAC audio encoder context, house-format audio buffer (S16 interleaved), sample-counter-authoritative PTS (`audio_encode_sample_counter_`), silence injection for audio liveness.
  - MPEG-TS muxer (`AVFormatContext`), custom AVIO write callback (`AVIOWriteThunk`), `MuxInterleaver` for global DTS ordering, muxer options for PCR cadence.
  - OutputTiming pacing gate (`GateOutputTiming`) on `(pts, steady_clock)` anchor — real-time emission discipline.
  - Window counters for encode-phase memory diagnostics.
- **MpegTSEncoder** (legacy thin shim) — `/opt/retrovue/runtime/src/playout_sinks/mpegts/MpegTSEncoder.cpp` (82 lines).
- **PTSController** — `/opt/retrovue/runtime/src/playout_sinks/mpegts/PTSController.cpp` (67 lines). PTS rescale helpers.
- **MuxInterleaver** (header-implemented in `include/retrovue/playout_sinks/mpegts/MuxInterleaver.hpp`). Holds cloned packets, sorts by DTS, drains in global order. Gate logic for startup holdoff.
- **ClockUtils** — `/opt/retrovue/runtime/src/playout_sinks/mpegts/ClockUtils.cpp`. 90kHz conversions.

### 1.8 Transport
- **SocketSink** — `/opt/retrovue/runtime/src/output/SocketSink.cpp` (441 lines). Non-blocking UDS/TCP byte consumer. Owns:
  - Writer thread with `poll()`+`send()` loop.
  - Bounded buffer with high/low water marks (hysteresis).
  - Detach-vs-throttle policy and callbacks.
  - Slow-consumer detection (`DetachSlowConsumer`).
  - `SIGPIPE` / `EPIPE` safe handling.
- **SinkDiagnostics** — `/opt/retrovue/runtime/src/output/SinkDiagnostics.cpp`. Common detach logging + `AirShutdownFired()` marker.

Note: current shipping topology is UDS (Unix Domain Socket) per channel, not raw UDP. AIR writes MPEG-TS to `/tmp/retrovue/air/<channel_id>.sock`; Core's fanout reads and serves over HTTP to viewers. The user's "UDP socket" phrasing is a simplification — honored in spirit ("bytes on wire over a socket") but flagged as an open question below.

### 1.9 Telemetry + observability
- **MetricsExporter + MetricsHTTPServer** — `/opt/retrovue/runtime/src/telemetry/*`. Prometheus scrape at `/metrics`.
- **EvidenceEmitter + EvidenceSpool + GrpcEvidenceClient** — `/opt/retrovue/runtime/src/evidence/*`. As-run / proof records shipped to Core.
- **Logger + ObservabilityLogger + AirMemoryMonitor** — `/opt/retrovue/runtime/src/util/*`.

### 1.10 Cross-cutting pacing + A/V sync concerns distributed across the above
Not a separate component in runtime/, but load-bearing behaviors to note:
- **Bootstrap A/V phase gate** — front-PTS delta within output frame duration required before real content starts. Lives in `BootstrapContentGate`.
- **Content-before-pad IDR gate** — `INV-CONTENT-BEFORE-PAD-IDR-001`, enforced inside `EncoderPipeline::encodeFrame`.
- **Silence injection for audio liveness** — `GenerateSilenceFrames` inside `EncoderPipeline`. Runtime conflates "produce silence" with "pace audio" because there is no Normalizer-side audio pad producer.
- **PCR pacing** — `EncoderPipeline::GateOutputTiming` + muxer PCR options. Real-time egress discipline.
- **Global DTS monotonic ordering** — `MuxInterleaver` buffers cloned packets, sorts, drains. Required because video+audio encode latencies differ.
- **SwsContext coherence** — `INV-ENCODER-SWS-COHERENCE-001`. Scaler recreated on source-format change. In `air/` this responsibility already lives in `StandardNormalizer` upstream of the encoder.

---

## Section 2 — Runtime → vNext mapping

For each runtime concern, the vault-authoritative vNext owner and its status in `air/` today.

| # | Runtime stage / concern | vNext owner (vault name) | In `air/` today? | Architectural delta |
|---|---|---|---|---|
| 1 | Process entry, gRPC server bind, FFmpeg init | (boundary mechanism; not a vault authority) | No | No equivalent; `air/` has no binary yet. Ship as a thin `air/src/main.cpp` when needed. |
| 2 | gRPC `PlayoutControl` surface (`StartChannel`, `AttachStream`, `StartBlockPlanSession`, `SwitchToLive`, …) | AIR_Boundary (transport contract) | No | In vNext, segment identity is final at the boundary; no `LoadPreview/SwitchToLive` choreography. Session-start payload carries auth segment + successor + JIP offset. |
| 3 | PlayoutEngine (session authority, channels map, SwitchWatcher) | **AIR_Lifecycle** + **PlaybackDirector** (orchestration subset) | Partial: minimal PlaybackDirector holds active-assignment only. AIR_Lifecycle authority surface not built. | Target is one session per process; the `channels_` map and `SwitchWatcher` are legacy artifacts that vault explicitly retires. |
| 4 | PlayoutControl state machine, ProducerBus | **PlaybackDirector** (active assignment + pending successor) | Partial: `PromoteToAssignment` is the atomic swap; pending/prepare/activate/retire directive surface not yet implemented. | "Switch preview→live" becomes `PromoteToAssignment` gated by a BootstrapContentGate or SeamController directive, not by external gRPC. |
| 5 | PipelineManager (tick loop + TAKE cascade + block/segment state) | **AIR_Pipeline** (per-tick execution realization) | No | Vault `Migration Notes` in `AIR_Pipeline.md` says several cascade branches migrate upstream into Normalizer (CADENCE_REPEAT), PacingController (admission), SeamController (seam branches). AIR_Pipeline shrinks. |
| 6 | SeamPreparer, SeamController, SeamEvaluator | **SeamController** | No in `air/`. Vault spec exists. | In vNext, seam is a directive source; "seam-ready" lives in Normalizer/BufferStore fronts. |
| 7 | BootstrapContentGate + BootstrapGateEvaluator | **BootstrapContentGate** | No in `air/`. Vault spec + runtime/ implementation exist as reference. | In vNext, the gate *reads* aggregate readiness from ReadinessController (directive) rather than evaluating depth-floors directly. |
| 8 | ReadinessEvaluator + ReadinessObserver | **ReadinessController** | No in `air/`. Vault spec exists. | In vNext, this is the single authority for readiness verdicts; other components consume the verdict. |
| 9 | AudioLookaheadBuffer + VideoLookaheadBuffer (co-located pacing + storage) | **PacingController** (policy) + **BufferStore** (storage) | Storage partially: `VideoPreviewBuffer` / `AudioPreviewBuffer` implement the BufferStore preview role. Policy: not built. | Vault explicitly separates these. `air/`'s preview buffers already honor "storage components do not own policy" — no hysteresis or park logic inside them. |
| 10 | FFmpegDecoder, FrameProducer, File/Black/Programmatic producers | **SourceProducer** (conformer contract) | Yes: `PadSourceProducer`, `FileSourceProducer`, `SyntheticSourceProducer` all implement `ISourceProducer`. | `air/` producers emit source-native PTS + format. Runtime producers were closer to the rendered side. |
| 11 | RealAssetSource, ProducerPreloader, TickProducer | (mechanism under SourceProducer + PlaybackDirector `prepare`) | No | Preload/prepare becomes PlaybackDirector `prepare(source_identity)` intent. Not yet in `air/`. |
| 12 | Cadence / rate conversion / pixel-format scale (inside decoder + encoder path) | **Normalizer** | Yes: `StandardNormalizer` does cadence resample + SRC + aspect-preserving scale. `IdentityNormalizer` for passthrough. | Large architectural win: runtime does scaling at encode time (SwsContext in EncoderPipeline); vNext does it per-source upstream so the pipeline always sees channel-canonical frames. |
| 13 | FrameRingBuffer + FrameIndexedVideoStore (live ring) | **BufferStore** (live role) | No: `air/` has preview-role BufferStore only. Live-role not yet realized. | In vNext, live is downstream of promotion; until emission exists, there's no live buffer to populate. |
| 14 | FrameRenderer + ProgramOutput + TimingLoop | **AIR_Pipeline** (per-tick emission realization) + **Clock** (tick identity) | No. The `air/` tests are not tick-driven; they are pull-mode. | vNext makes the tick loop depend on Clock as injected dependency. Phase 7C done; 7D (control-plane) still pending. |
| 15 | MasterClock + TimelineController + SystemTimeSource | **Clock** (injected AuthoritativeClock) | No: `air/` has no Clock abstraction at all. Tests don't need one. | Must be first authority constructed per vault instantiation order. |
| 16 | OutputBus + IOutputSink | (mechanism owned by **AIR_Pipeline**'s mux/output byte production surface) | No | Vault says "Output sinks are implementation mechanisms, not authority owners." Keep as internal mechanism. |
| 17 | MpegTSOutputSink (encoder+socket wiring) | (mechanism under AIR_Pipeline) | No | Will live inside `air/` as a concrete mechanism named something like `MpegTsEmitter` or similar; not a new vault component. |
| 18 | EncoderPipeline (x264 + AAC + mux + pacing + liveness + IDR gate + silence injection + DTS interleave) | (mechanism under AIR_Pipeline) | No | In vNext several of this class's concerns move out: silence injection → pad audio Normalizer; scaling → Normalizer; PCR pacing → PacingController egress. What remains is the narrower "frames in, TS packets out" duty. |
| 19 | MuxInterleaver (global DTS monotonic) | (mechanism under AIR_Pipeline) | No | Still needed in vNext, likely narrower (no silence-injection special cases). |
| 20 | SocketSink (non-blocking writer thread + backpressure + detach/throttle) | (mechanism under **AIR_Boundary** transport) | No | In vNext separate out more cleanly: SocketSink's detach vs throttle policy is load-bearing and has no direct vault owner today. **Gap.** |
| 21 | PTSController, ClockUtils (90kHz conversions) | (utility under AIR_Pipeline) | No | Pure math; port as needed. |
| 22 | MetricsExporter + MetricsHTTPServer + EvidenceEmitter + EvidenceSpool | **AIR_Observability** | No | Vault `AIR_Observability.md` is thin (24 lines); the aggregation surface is a named gap in `Flow - Tune-In`. |
| 23 | Crash/signal handlers, AirMemoryMonitor | (mechanism under AIR_Lifecycle / AIR_Safety) | No | Port when building the binary. |
| 24 | `INV-CONTENT-BEFORE-PAD-IDR-001` (no pad IDR) | AIR_Pipeline (contractual) | No | Must be re-enforced on any vNext mechanism. |
| 25 | Bootstrap A/V front-PTS delta gate | **BootstrapContentGate** | No | Spec ready; needs implementation. |
| 26 | Silence injection for audio liveness | **PadSourceProducer** (already emits silence via Normalizer) OR PacingController directive | Partial: `PadSourceProducer` already emits silence at rate. No emission path consumes it yet. | vNext cleaner: silence is a first-class source, not a hack inside the encoder. |

Classifications per vault CLAUDE.md:

- **Authority complete in vault, needs implementation in `air/`**: Clock, ReadinessController, BootstrapContentGate, PacingController, SeamController, PlaybackDirector (full surface), AIR_Pipeline, AIR_Lifecycle.
- **Contract clarification needed**: Row 20 — SocketSink-equivalent transport mechanism below AIR_Boundary. `Flow - Tune-In` gap #4 ("Output boundary opening moment unspecified") names this. AIR_Observability aggregation surface is also a named gap.
- **Missing enforcement**: None identified beyond the gaps already called out in `Flow - Tune-In` (7 gaps listed there).

---

## Section 3 — Prioritized step list

Ordering principle: **shortest path to "bytes leaving AIR over a socket" for a single source, no seams, no multi-block, no full orchestration.** After that milestone (Step 6), layer in session lifecycle, kickoff, readiness, and seams. Each step is a one-sitting unit (hours, not days), ends with a working demonstrable artifact, and has a concrete test.

### Step 1 — Add `Clock` abstraction
**What it adds.** `air/include/clock.hpp` with an `AuthoritativeClock` interface (`monotonic_us()`, `monotonic_ns()`, `now_utc_ms()`) and two conformers: `SystemClock` (wraps `std::chrono::steady_clock`) and `ControllableClock` (manually advanced, for tests). Injection is kwarg/constructor-parameter style; no globals.
**Test.** New contract file `air/tests/contracts/clock_contract_test.cpp`: (a) ControllableClock advances monotonically, never regresses under `Advance(dt)`; (b) SystemClock passes a sanity bracket (`steady_clock::now()` taken immediately before and after); (c) two consumers share the injected instance and read the same values.
**Does NOT.** Retrofit `StandardNormalizer` / `IdentityNormalizer` to consume Clock. They don't do wall-clock math; no retrofit needed. Don't add a clock to `file_source_producer` — decode uses container PTS.
**Why first.** Every downstream authority must be constructed with a Clock reference per vault `Boundary With Clock` clauses. Adding it now, with no dependents, keeps the change tiny.

### Step 2 — Add `ChannelPts` derivation helper + Pacing-free tick driver (no time yet)
**What it adds.** A `TickDriver` utility (not a vault authority — a test mechanism) that calls a callback N times in a tight loop with monotonic tick indices, and a helper to convert tick index to channel PTS using `Rational::NthStepPtsUs` (already in `channel_canonical.hpp`). Lives in `air/include/tick_driver.hpp`.
**Test.** `air/tests/contracts/tick_driver_test.cpp`: (a) tick indices 0..99 produce PTS values equal to `NthStepPtsUs(k)`; (b) callback invoked exactly N times; (c) Clock injection is exercised but cadence is not yet real-time.
**Does NOT.** Sleep. Real-time pacing. Don't introduce `PacingController` yet — this is the dumbest-possible tick source for the emission path.
**Why second.** Emission needs *something* driving it. The real `AIR_Pipeline` tick loop will replace this, but we need one end of the pipe to turn.

### Step 3 — Add `FrameEmitter` mechanism: tick pulls from preview, logs a frame fingerprint
**What it adds.** `air/include/frame_emitter.hpp` / `.cpp`. Owns: reference to a `PlaybackDirector` (minimal one, existing), pulls `VideoFrame` + `AudioBlock` per tick from whichever preview the active assignment points to. No encoding yet. Just: `(tick_index) → {video_frame, audio_block}` with absolute channel PTS computed via `LiveSegment::AbsoluteVideoPtsUs`. Emits a structured fingerprint per tick to a callback (used for testing).
**Test.** `air/tests/contracts/frame_emitter_test.cpp`: (a) with PadSourceProducer preloaded into preview via existing fixture, 90 ticks produce 90 video fingerprints with continuous channel PTS; (b) after `PromoteToAssignment` to a FileSourceProducer-fed preview, PTS continuity is preserved across promotion; (c) underflow (empty preview) emits a structured underflow event and returns null for that tick without crashing.
**Does NOT.** Write any bytes. Enforce `INV-CASCADE-GUARANTEED-EMISSION-001` (null→pad fallback) fully — only flag underflow; pad substitution arrives in Step 4. No encoder, no mux, no socket.
**Why third.** This is the load-bearing skeleton of AIR_Pipeline emission. Everything else plugs onto this skeleton.

### Step 4 — `FrameEmitter` underflow → pad substitution (CASCADE-GUARANTEED-EMISSION)
**What it adds.** A dedicated fallback `PadSourceProducer`+`IdentityNormalizer`+preview pair always attached to FrameEmitter; on pull-underflow from the active segment's preview, emit from the pad pair instead. Records a structured `UnderflowSubstitutionEvent`.
**Test.** Extend `frame_emitter_test.cpp`: (a) empty active preview → tick still produces a frame (pad); (b) pad PTS is on the same channel timeline as the substituted content PTS (no PTS jump); (c) substitution counter increments by exactly the expected amount.
**Does NOT.** Add a content-before-pad IDR gate. Re-anchor PTS. Introduce BootstrapContentGate. (The pre-kickoff pad period from the vault tune-in flow is a session-lifecycle concern handled in Step 7.)
**Why fourth.** Satisfies the vault's emit-every-tick invariant before we add any real-world I/O downstream.

### Step 5 — `MpegTsEncoderMechanism`: YUV420P + S16 → `AVPacket` (no transport yet)
**What it adds.** `air/include/mpeg_ts_encoder.hpp` / `.cpp`. Owns an `AVCodecContext` for libx264 (constant params: channel canonical resolution, fps, fixed bitrate e.g. 4Mbps), an `AVCodecContext` for AAC (channel sample rate, stereo, fixed bitrate e.g. 192kbps), and an `AVFormatContext` muxer writing to an in-memory AVIO buffer (captured via a `write_callback` that appends to a `std::vector<uint8_t>`). Takes a `VideoFrame` + `AudioBlock` per encode call; outputs bytes via callback. Reuses `runtime/third_party/` libav + libx264 linkage.
**Test.** `air/tests/contracts/encoder_mechanism_test.cpp`: (a) open→encode 60 video frames + corresponding audio blocks via `StandardNormalizer` output from `SampleA.mp4`→close; total captured bytes > 0; first bytes match MPEG-TS sync byte `0x47`; (b) `ffprobe` can parse the captured buffer (invoke via `popen`); (c) IDR-first: first video packet has `AV_PKT_FLAG_KEY` set.
**Does NOT.** Open a socket. Pace emission. Interleave by global DTS (rely on `av_interleaved_write_frame` default). Add silence injection. Add PCR pacing. Support encoder reconfiguration (format fixed per session).
**FIRST "BYTES ON WIRE" MILESTONE, partial**: bytes exist in-memory and are valid MPEG-TS. The next step moves them to a socket.

### Step 6 — `SocketEmitter` mechanism + end-to-end: file decode → channel canonical → encode → socket
**What it adds.** `air/include/socket_emitter.hpp` / `.cpp`. Wraps an `fd` passed in from outside (test opens a socket pair; real deployment will receive from `AttachStream`). Single-threaded write: a writer function called from the encode callback with `write(fd, buf, n)` handling `EAGAIN` via a bounded in-memory backoff buffer (small, e.g. 256KB; **drop-on-full with a counter, no throttle, no detach policy ever** — product rule: AIR never pauses emission in response to downstream backpressure; slow consumer is the consumer's problem).
**Test.** New integration test `air/tests/contracts/end_to_end_emission_test.cpp`: (a) set up `socketpair(AF_UNIX, SOCK_STREAM, 0)`; (b) wire `FileSourceProducer("SampleA.mp4") → StandardNormalizer → VideoPreviewBuffer/AudioPreviewBuffer → PlaybackDirector (promoted) → FrameEmitter → MpegTsEncoderMechanism → SocketEmitter(write_fd)`; (c) drive TickDriver for 60 ticks; (d) read bytes from `read_fd` into a buffer; (e) assert buffer parses as MPEG-TS (sync byte check + `ffprobe` success); (f) assert PTS continuity from ffprobe-observed PTS values.
**Does NOT.** UDP. Throttle policy. Detach policy. Real-time pacing. Multi-session. gRPC.
**FIRST "BYTES ON WIRE" MILESTONE, complete.** After Step 6 you can point `ffplay` at a TCP port and watch decoded SampleA play through the full vNext stack. Stop here, celebrate, regroup.

### Step 7 — Inject real-time pacing at socket write (egress rate limiter, before PacingController)
**What it adds.** A tiny pacing shim inside SocketEmitter that sleeps to keep emission at channel-rate bytes-per-second based on muxed bitrate (computed as `output_bytes_so_far / elapsed_channel_seconds`). Uses injected Clock. Still not vault `PacingController`; this is the egress-rate discipline that lives in runtime's `GateOutputTiming`.
**Test.** `pacing_egress_test.cpp`: (a) with `SystemClock`, 10 seconds of channel content takes 10±0.2 seconds of wall time to emit; (b) with `ControllableClock`, behavior is deterministic (no real sleep). Instrument with an injected sleep function to keep tests fast.
**Does NOT.** Become the vault PacingController (that's admission policy, not egress). Interleave audio silence. Change encoder behavior.
**Why here.** Without Step 7, Step 6 emits as-fast-as-possible and is only visibly correct when piped into ffprobe. Step 7 makes it playable in real time — a big demo win.

### Step 8 — Binary: `retrovue_air_vnext` + minimal gRPC `AttachStream` only
**What it adds.** `air/src/main.cpp`: reads a file path + listen endpoint from argv, opens the endpoint as a TCP listener, accepts one connection, wires the full pipeline, emits until EOF, exits. Also adds: SIGPIPE handler ported from runtime, FFmpeg global init. No gRPC yet (purely argv-driven). Call it "Stage 1 binary."
**Test.** A shell-level smoke test `air/tests/smoke/smoke_binary.sh` launched by ctest: spawn `retrovue_air_vnext --input SampleA.mp4 --listen 127.0.0.1:50100`, connect via `socat TCP:127.0.0.1:50100 | ffprobe -`, assert ffprobe returns zero. Skip in CI if socat absent.
**Does NOT.** Implement any gRPC RPC. Link gRPC at all. Spawn from Core.
**Why here.** Gives a first demonstrable artifact that isn't a gtest binary.

### Step 9 — `ReadinessController` (aggregate health verdict)
**What it adds.** `air/include/readiness_controller.hpp` / `.cpp` with a verdict enum (`NotReady`, `Pending`, `Ready`) computed as **aggregate health, not depth alone**. Inputs include: decoder fault state (faulting producer is never ready), first video frame decodable, first audio sample present, monotonic PTS (no regressions), video/audio fronts aligned within tolerance, **minimum runway duration** (time-based, not frame-count — accommodates varying fps), depth floor met. Any one failing → not ready. Pure function of inputs. Emits observable transition events with structured reason class.
**Test.** `readiness_test.cpp`: (a) empty inputs → `NotReady`; (b) all conditions met → `Ready`; (c) decoder fault alone → `NotReady` regardless of depth; (d) each transition emits one event with reason class.
**Does NOT.** Drive any behavior yet. Nothing reads its verdict.
**Why now.** Precondition for BootstrapContentGate and AIR_Lifecycle failure path per vault instantiation order. FileProducer emits signals; ReadinessController aggregates into a verdict — producers do not self-declare ready.

### Step 10 — `BootstrapContentGate` (bootstrap transition owner)
**What it adds.** `air/include/bootstrap_content_gate.hpp` / `.cpp`. Consumes ReadinessController verdict. On the first tick where verdict is `Ready` for the pending content assignment, transitions `closed → open` and arms a bootstrap transition via `PD.ArmSuccessor(content_assignment, target_tick)` where `target_tick` is the next lawful emission boundary. Sticky (fires exactly once per session).
**Test.** `bootstrap_gate_test.cpp`: (a) stays closed until Readiness verdict is Ready; (b) fires exactly once even if readiness oscillates; (c) arm directive carries correct target_tick; (d) observable kickoff event has correct fields.
**Does NOT.** Evaluate readiness itself (that's ReadinessController's job). Drive emission directly. Handle scheduled seams or failure transitions (separate owners — see org chart).
**Why now.** Owns the **bootstrap transition class** (pad → first content). One of three transition owners; the others are SeamController (scheduled) and AIR_Lifecycle (failure).

### Step 11 — Session lifecycle: pre-kickoff pad emission, commit-on-tick-boundary
**What it adds.** Extend `PlaybackDirector` with broadcast-vocabulary directive surface:
- `ArmSuccessor(assignment, target_tick)` — any controller, any thread, queues a pending successor for commit at `target_tick`.
- `CommitSuccessor(tick_index)` — called by the emitter at the frame-commit point; takes any pre-armed successor whose `target_tick == tick_index`. Nothing applies mid-frame.

FrameEmitter starts with the pad assignment active. On the bootstrap arm + commit, the pad → content succession executes at a tick boundary. No mid-frame swaps, no torn frames.
**Test.** `session_kickoff_test.cpp`: (a) pre-kickoff ticks emit pad bytes; (b) after commit tick, emission reads from content buffer; (c) channel PTS is continuous across the commit tick (`INV-BOOTSTRAP-PTS-CONTINUOUS-001`); (d) commit is exact (never off-by-one from `target_tick`); (e) kickoff fires exactly once even if readiness oscillates.
**Does NOT.** Add SeamController. Handle multiple blocks. Handle failure transitions.
**Why here.** Establishes the **shared arm/commit mechanism** used by all three transition classes (bootstrap, scheduled, failure). Vocabulary: *arm* for the pre-commit request, *commit* for the take — not "promote."

### Step 12 — gRPC stub: `StartChannel` + `AttachStream` only, Stage-2 binary
**What it adds.** Generate the C++ gRPC stubs for the existing `protos/playout.proto` (already generated for runtime/; reuse or regenerate), implement two RPCs: `StartChannel` (stashes channel config + file path from a field in the request or config JSON) and `AttachStream` (connects to a UDS per runtime convention and plumbs the fd into SocketEmitter).
**Test.** Extend smoke test: use `grpcurl` or a small Python client to call `StartChannel` then `AttachStream`, then `read` from the UDS, pipe to ffprobe. Same pass criterion as Step 8 smoke test.
**Does NOT.** Implement `LoadPreview`, `SwitchToLive`, `StartBlockPlanSession`, `FeedBlockPlan`, `SubscribeBlockEvents`. The vault's `INV-AIR-NO-SEGMENT-DRIVEN-EXECUTION-001` and `INV-AIR-NO-ADHOC-SWITCHING-001` actively forbid re-implementing runtime's choreography in vNext. Intentionally defer these.
**Why here.** Proves `air/` is Core-wireable without ever building the legacy choreography.

### Step 13 — Single-block BlockPlan session ingestion (first editorial boundary)
**What it adds.** `StartBlockPlanSession` RPC implementation accepting one block A containing one segment with JIP offset 0. PlaybackDirector consumes `BlockA` as the editorial source identity and plumbs `FileSourceProducer` + `StandardNormalizer` + preview pair from the block's asset path.
**Test.** `block_plan_single_segment_test.cpp` + smoke test variant. Verify channel PTS anchor matches block start.
**Does NOT.** Accept block B. Handle successor plans. Handle JIP != 0.
**Why here.** First touch of Core's editorial model; minimum viable Core↔AIR integration.

### Step 14 — Two-block BlockPlan + `SeamController` (scheduled transition owner)
**What it adds.** `SeamController` — owner of the **scheduled transition class**. Explicit state machine `observing → armed → committed_for_tick(N) → executed`:
- **observing**: watching block A's fence approach.
- **armed**: tens of ms before fence, check Readiness for block B; if ready, arm via `PD.ArmSuccessor(B, fence_tick)`. If B goes un-ready between arming and fence, disarm and fall back to pad-bridge.
- **committed_for_tick(N)**: directive is published with `target_tick = N`. Decision is frozen; PD and emitter execute deterministically at tick N.
- **executed**: at tick N, emitter calls `CommitSuccessor(N)`, block B becomes current. Observable event emitted.

**Fence is sacred.** At fence tick, SeamController commits **either** the pre-armed successor **or** pad. Block A never overruns its fence. Underrun (source shorter than allotted duration) is handled by pad filling to the fence.
**Test.** `seam_single_test.cpp`: (a) block A 5s + block B 5s, B ready → clean seam at fence tick, PTS continuous; (b) B not ready at fence → pad committed at fence, block B commits at next tick once ready; (c) B ready 1 frame before fence → pad-flash then B (arming latency honored); (d) B ready 10s early → parks (PacingController keeps buffer steady) then seams at fence; (e) lifecycle phase events emitted in order.
**Does NOT.** Handle missed-seam JIP. Handle successor-plan revisions. Support more than two blocks. Handle runtime faults (that's AIR_Lifecycle's failure transition, Step 16).
**Why here.** First seam is the first scheduled transition. **Decision early, execution exact** — broadcast-safe.

### Step 15 — `PacingController` (admission + park/unpark)
**What it adds.** The vault-spec PacingController: observes buffer depth + front PTS, issues `admit`/`hold`/`discard` to the preview buffers on producer-side pushes, issues `park`/`unpark` to fill-threads. Before Step 15, emission is synchronous and there are no fill-threads; this step introduces them.
**Test.** Pacing contract tests: starvation response, overshoot clamp, park/unpark events. Pure-function tests plus one integration test showing buffers stay at steady depth under varying producer rates.
**Does NOT.** Throttle emission — there is no downstream throttle path (product rule). Replace egress pacing from Step 7 (that's transport rate, distinct from admission). Handle runtime faults.

### Step 16 — `AIR_Lifecycle` failure-transition path + EOF-before-fence handling
**What it adds.** AIR_Lifecycle gains a concrete job: ownership of the **failure transition class**. When ReadinessController drops the current assignment's verdict due to an irrecoverable fault (decoder error, EOF-before-fence, source I/O failure), AIR_Lifecycle:
1. Declares the current assignment failed (immediate, not at scheduled fence).
2. Arms a pad-bridge via `PD.ArmSuccessor(pad, next_tick)` — pad becomes authoritative live bridge.
3. When Readiness says the next block is ready, arms that successor via `PD.ArmSuccessor(next_block, next_tick)`.
4. The failed block's original scheduled fence is preserved in as-run metadata for reporting, but is no longer live authority.

**Behavior by fault type:**
- **Decoder fault mid-block**: retire current immediately, pad-bridge, fast-track successor once ready. Not "pretend current is still airing until scheduled fence."
- **FileSourceProducer EOF before fence**: same — treat as fault. Retire, pad-bridge, successor when ready.
- **Socket backpressure**: not a failure transition at all. Pipeline keeps running, bytes drop (product rule 1). No AIR_Lifecycle involvement.
- **Core disconnect**: terminal (product rule 7). AIR shuts down via normal exit path. Not a failure transition within AIR.

**Test.** `failure_transition_test.cpp`: (a) decoder fault mid-block → immediate retirement, pad-bridge observable event, successor commits at next ready tick; (b) EOF before fence → same trajectory; (c) failed block's scheduled fence does not trigger a scheduled transition (SeamController stays `observing`); (d) as-run metadata preserves the original fence and marks block as failed.
**Does NOT.** Reassign authority for scheduled or bootstrap transitions — those stay with SeamController and BootstrapContentGate. Attempt reconnect or session recovery. Support multi-channel.
**Why here.** Three transition classes are now all implemented with three explicit owners sharing the `ArmSuccessor` / `CommitSuccessor` mechanism.

---

## Milestone summary

- **After Step 6**: bytes on wire, one source, one shot, ffplay works.
- **After Step 8**: standalone runnable binary, no gRPC.
- **After Step 11**: vault-correct tune-in trajectory (pre-kickoff pad → kickoff → content) end-to-end.
- **After Step 12**: Core-wireable minimal vNext binary.
- **After Step 14**: two-block seam handling, first real "broadcast" demonstrable.
- **After Step 16**: vNext covers the load-bearing behaviors runtime/ covers, minus multi-channel and full successor-plan revision, which are outside vNext's single-session charter.

## Dependency / sequencing notes

- Steps 1–6 are strictly linear (each depends on the previous).
- Steps 7 and 8 can run in parallel after Step 6 (independent concerns).
- Steps 9 and 10 can run in parallel; Step 11 depends on both.
- Step 12 can start after Step 8; doesn't block session-lifecycle work in Steps 9–11.
- Steps 13–14 depend on Step 12.
- Step 15 depends on Step 11 (fill-thread introduction). Step 16 depends on 15.

## Open questions

**Closed by product/design decisions on 2026-04-20:**

- ✅ **#5 Clock epoch.** Resolved: monotonic primary via injected `AuthoritativeClock`; wall-clock UTC only when Step 13 begins consuming Core's `join_utc_ms`. No Clock epoch complexity in Steps 1–12.
- ✅ **#7 SocketEmitter detach vs throttle.** Resolved: never throttle, never detach; drop-on-full. Product rule — AIR never pauses emission in response to downstream backpressure. SocketSink's runtime/ policy does not port to vNext.

**Still open:**

1. **Transport protocol for vNext.** Runtime uses UDS per channel (`/tmp/retrovue/air/<channel_id>.sock`) connected *after* `AttachStream`. The original prompt said "UDP socket"; runtime is stream-over-UDS not UDP. Which does vNext target? Recommendation: match runtime (UDS stream socket) to preserve Core compatibility; defer UDP.
2. **Encoder parameter freedom.** Fixed bitrate / constant-QP / NVENC vs libx264 — runtime supports both via env. vNext Step 5 should pick one (recommendation: libx264 CBR 4Mbps for deterministic tests) and defer NVENC.
3. **gRPC surface re-use vs subset.** The `runtime/protos/playout.proto` has many legacy RPCs (`LoadPreview`, `SwitchToLive`, segment RPCs). Vault `AIR_Boundary.md` explicitly forbids these for scheduled playout but they are still defined. Does vNext ship a new proto file, or share and implement only the modern subset?
4. **Binary name + build target.** Is vNext intended to eventually replace `runtime/build/retrovue_air`, or to coexist as `air/build/retrovue_air_vnext`?
6. **AIR_Observability aggregation surface.** Vault Flow-Tune-In gap #5 names this as unresolved. Per-component callbacks are sufficient through Step 14; raise as a vault update when emit sites exceed ~6.
8. **Multi-block vs single-segment vNext scope.** Confirm that vNext implements block-plan semantics in Steps 13+ and does not try to handle `StartChannel` as a standalone mode.

**Derived rules no longer open (applied throughout plan):**
- AIR is 1-process-1-channel-1-session. No `channels_` map. PlaybackDirector constructed once at process startup.
- AIR emits only after consumer (Core) connects via `AttachStream`. Socket file is created at AIR startup; emission loop begins on attach.
- Core disconnect is terminal. No reconnect protocol in vNext.
- Loudness normalization is per-source, inside Normalizer's audio chain (alongside sample-rate conversion). Not in the encoder.
- Egress emission is paced to channel frame rate. Real-time, not as-fast-as-possible. Uses injected `AuthoritativeClock`.
- Three transition classes (scheduled / bootstrap / failure) with three owners (SeamController / BootstrapContentGate / AIR_Lifecycle) sharing the `ArmSuccessor` + `CommitSuccessor` mechanism on PD.
