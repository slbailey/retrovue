# VNEXT_TRANSFORMATION — Component Transformation Map

## Top matter

**Purpose.** For every component that exists today in `/opt/retrovue/runtime/` and `/opt/retrovue/air/`, this document states (1) what it is now, (2) the vault-authoritative vNext shape, and (3) the single mapping action required to reshape it. This replaces Section 2 of `NEXT_STEPS_PLAN.md` and deliberately omits Section 3 (forward plan). It is a "today vs. target" reshape ledger, not a roadmap. Section 1 of `NEXT_STEPS_PLAN.md` (runtime pipeline inventory) remains the definitive current-state prose; this document references it rather than duplicating.

**Decisions applied (2026-04-20).** This document has been amended to reflect product-behavior and org-chart decisions finalized in conversation on this date. See memory files for full context:
- `project_retrovue_air_product_decisions` — never throttle, per-source loudness, real-time emission, 1-process-1-channel, emit-only-after-consumer-connects, fault retires current assignment immediately, Core disconnect is terminal.
- `project_retrovue_air_org_chart` — PD is coordinator; three transition classes (scheduled / bootstrap / failure) with three owners (SeamController / BootstrapContentGate / AIR_Lifecycle) sharing the `ArmSuccessor` + `CommitSuccessor` mechanism on PD.
- `project_retrovue_air_execution_discipline` — seam arms early and commits for target tick; promotions apply only at tick boundaries; readiness is aggregate health; fence is sacred (underrun OK, overrun never).
- `feedback_broadcast_vocabulary` — use broadcast terms (arm, commit, take, cue, fence, seam, pad, fill) over generic software verbs.

**Legend — mapping actions.**
- **already-done-in-air** — the vNext-compliant form already exists under `/opt/retrovue/air/`; the runtime/ component is retired by virtue of parallel implementation.
- **extend-in-place** — keep the `air/` component; add surface to reach the vault target.
- **build-new-in-air** — no `air/` equivalent exists; construct fresh. The `runtime/` version is reference, not template.
- **delete / retire** — the vault explicitly retires this concept (or splits it across others); no vNext equivalent.
- **extract-and-split** — the `runtime/` component conflates multiple authorities; vNext splits along vault-drawn boundaries.

**Vault primary sources used.**
- `/opt/retrovue-obsidian/Retrovue/00_components/` — PlaybackDirector, ReadinessController, BootstrapContentGate, PacingController, SeamController, SourceProducer, Normalizer, BufferStore, Clock, AIR_Pipeline, AIR_Boundary, AIR_Runtime, AIR_Lifecycle, AIR_Observability, AIR_Safety, AirBridge, RunwayManager.
- `/opt/retrovue-obsidian/Retrovue/04_truths/` — Authority Domains Have Sole Owners; Storage Components Do Not Own Policy; Source Time Is Producer-Local, Channel Time Is Canonical; Directive-Based Coupling Preferred Over Observation-Based Coupling; Time Authorities Must Be Singular; Transition Boundaries Require Singular Ownership; Session Readiness Has One Owner.
- `/opt/retrovue-obsidian/Retrovue/02_flows/Flow - Tune-In.md` — seven named gaps (instantiation, PD↔BCG coordination, kickoff directive delivery, output boundary opening moment, observability aggregation, producer-lifecycle sequencing, pad always-present).
- `/opt/retrovue-obsidian/Retrovue/06_decisions/ADR-006`, `ADR-007`.
- `/opt/retrovue/air/NEXT_STEPS_PLAN.md` — Section 1 inventory baseline.

---

## Group 1 — Session authority & lifecycle

| Today (path + class) | Today's responsibility | vNext shape | Action | Notes |
|---|---|---|---|---|
| `runtime/src/runtime/PlayoutEngine.cpp` + `include/retrovue/runtime/PlayoutEngine.h` (`PlayoutEngine`, 2187 lines) | Single-session execution authority; holds `channels_` map, `PlayoutInstance`, `SwitchWatcher` thread, deadline-driven `ExecuteSwitchAtDeadline`, gRPC mux-frame callback bridge. | Splits into **AIR_Lifecycle** (single-session charter, failure authority table, epoch, idempotent start/stop) + **PlaybackDirector** (active/pending-assignment truth, successor plan). `channels_` map and `SwitchWatcher` are explicitly retired by `INV-AIR-NO-ADHOC-SWITCHING-001` and `INV-SESSION-SINGLE-ACTIVE-001`. | extract-and-split | No vault component called "PlayoutEngine"; concept splits cleanly. `SwitchWatcher` thread is forbidden by vault — preview→live choreography is retired. |
| `runtime/src/runtime/PlayoutController.cpp` + `PlayoutController.h` | Wires control surface into ProducerBus; mediates Engine↔Producer state. | Subsumed under PlaybackDirector's orchestration surface (prepare/activate/retire directives) per `PlaybackDirector.md §Orchestration Surface`. | delete / retire | Vocabulary collision: "Controller" naming comes from Engine-era; vault uses "Director" for orchestration, "Controller" for specialised decision authorities (ReadinessController, SeamController, PacingController). |
| `runtime/src/runtime/ProducerBus.cpp` (26 lines) | Tracks LIVE vs PREVIEW producer. | PlaybackDirector owns active + pending assignment directly (`INV-PLAYBACK-SINGLE-OWNER-001`); there is no separate "bus" abstraction. The air/ `PlaybackDirector::PromoteToAssignment` already realises the atomic swap. | delete / retire | The "bus" is a state pattern rendered obsolete by PlaybackDirector's directive surface. |
| `runtime/src/runtime/PlayoutInterface.cpp` + `PlayoutInterface.h` | Thin wrapper over PlayoutEngine presented to gRPC. | Collapsed into AIR_Boundary's gRPC adapter (Group 2). | delete / retire | Wrapper layer needed only because PlayoutEngine had internal channel map; single-session vNext needs no wrapper. |
| `air/include/playback_director.hpp` (`PlaybackDirector`, `LiveSegment`) | Active-assignment truth + `PromoteToAssignment` atomic swap + promotion count. | Broadcast-vocabulary directive surface per 2026-04-20 decision: `ArmSuccessor(assignment, target_tick)` (any caller, any thread) + `CommitSuccessor(tick_index)` (called by emitter at frame-commit point). Pending-assignment publication, coordination reads from BootstrapContentGate / SeamController / AIR_Lifecycle (three transition-class owners) / ReadinessController / RunwayManager. Kickoff-sequencing invariants (`INV-PLAYBACK-PRE-KICKOFF-PREPARE-001`, `INV-PLAYBACK-PENDING-ASSIGNMENT-OBSERVABLE-BEFORE-KICKOFF-001`) still apply; legacy `prepare/activate/retire/promote` vocabulary retires in favour of `arm/commit`. | extend-in-place | `PromoteToAssignment` splits into `ArmSuccessor` + `CommitSuccessor`. Minor surgery: the atomic swap primitive stays; its callers change from synchronous invocation to arm-then-commit-on-tick-boundary. Vault update owed on `PlaybackDirector.md`. |

**Architectural reshape.**
- The `channels_` map is a multi-channel-per-process hangover. Vault `Truth - Channel Lifecycle Has One Owner` and `INV-SESSION-SINGLE-ACTIVE-001` explicitly bind one AIR process to one channel; the map is retired, not refactored.
- "Switch preview→live" as an externally driven verb dies. vNext promotion is triggered by a directive from BootstrapContentGate (at kickoff) or SeamController (at a seam) — never by a caller-issued RPC. `INV-AIR-NO-ADHOC-SWITCHING-001` makes the ban explicit.
- Construction order (Clock → ReadinessController → PacingController → BootstrapContentGate → PlaybackDirector → SourceProducers) is an authority-ownership invariant per `PlaybackDirector.md §Instantiation & Construction`. runtime/'s ad-hoc construction inside `main.cpp` does not satisfy it.
- The vault treats PlaybackDirector as possibly the session-construction owner, flagged as revisitable. `Flow - Tune-In` gap #1 (instantiation surface underspecified) is unresolved.

---

## Group 2 — Control plane / gRPC boundary

| Today (path + class) | Today's responsibility | vNext shape | Action | Notes |
|---|---|---|---|---|
| `runtime/src/playout_service.cpp` + `playout_service.h` (`PlayoutControlImpl`, 1619 lines) | gRPC service impl. RPCs: `StartChannel`, `AttachStream`, `LoadPreview`, `SwitchToLive`, `StopChannel`, `StartBlockPlanSession`, `FeedBlockPlan`, `StopBlockPlanSession`, `SubscribeBlockEvents`, `UpdatePlan`, `GetVersion`. Evidence hookup. | **AIR_Boundary**'s gRPC surface shrinks: retain `StartChannel`, `AttachStream`, `StartBlockPlanSession`, `FeedBlockPlan`, `StopBlockPlanSession`, `SubscribeBlockEvents`, `StopChannel`, `GetVersion`. Retire `LoadPreview`, `SwitchToLive`, `UpdatePlan` (choreography RPCs) per `INV-AIR-NO-ADHOC-SWITCHING-001` and `INV-AIR-NO-SEGMENT-DRIVEN-EXECUTION-001`. Session-start payload carries auth segment + successor + `join_utc_ms` per `INV-AIR-CORE-CONTRACT-001`. | extract-and-split | The mechanism (gRPC service class) survives; the *surface* narrows. Half of the RPCs are explicitly vault-forbidden. |
| `runtime/src/main.cpp` | Binary entry, signal handling, FFmpeg `avformat_network_init`, constructs MasterClock, PlayoutEngine, gRPC server on :50051, metrics on :9308. | Binary entry is a mechanism under AIR_Lifecycle / AIR_Safety; not a vault authority. Signal handling is under AIR_Safety. | build-new-in-air | No `air/` equivalent exists; `air/` has no binary yet. Port with construction order matching vault instantiation sequence. |

**Architectural reshape.**
- The single biggest reshape at the control plane is the *disappearance* of the preview→live choreography. `LoadPreview` + `SwitchToLive(now + X)` + `frame_count = -1` are all retired as a set per `AIR_Boundary.md §Prohibited` and `AIR_Runtime.md INV-AIR-NO-SEGMENT-DRIVEN-EXECUTION-001`.
- Evidence plumbing inside `PlayoutControlImpl` ties the gRPC surface to AIR_Observability and needs to move to a dedicated observability aggregation owner — which `Flow - Tune-In` gap #5 flags as an unresolved vault gap.
- `GetVersion` / `StopChannel` / `AttachStream` / BlockPlan family (`Start/Feed/Stop/Subscribe`) are the vault-compatible RPCs per `AIR_Boundary.md §Interfaces`.

---

## Group 3 — Clock & timing

| Today (path + class) | Today's responsibility | vNext shape | Action | Notes |
|---|---|---|---|---|
| `runtime/src/timing/SystemMasterClock.cpp` (+ `MasterClock.h`) | Single time authority; UTC epoch + drift parameter; wraps steady/system clocks. | **Clock** (vault `Clock.md`). `AuthoritativeClock` interface, injected, singular per `Truth - Time Authorities Must Be Singular` and `INV-CLOCK-PICKLABLE-001` equivalent. Construction order position #1 (before all other authorities). | build-new-in-air | `air/` has no Clock abstraction at all — tests are pull-driven and don't need one. `Clock.md` §Authority documents the Python-side implementation but is normative for AIR C++ via `Truth - Time Authority Is Injected`. |
| `runtime/src/timing/TestMasterClock.cpp` + `.h` | Test clock with manual advance. | `ControllableClock` conformer to `AuthoritativeClock`. | build-new-in-air | Reference pattern; vNext tests will want an equivalent. |
| `runtime/src/timing/TimelineController.cpp` + `TimelineController.h` | Channel-monotonic timeline bookkeeping vs. MasterClock. | Channel timeline as "tick index → channel PTS" is mechanism. In `air/` this role is fulfilled by `Rational::NthStepPtsUs` inside `channel_canonical.hpp` (drift-free round-to-nearest). | already-done-in-air | `channel_canonical.hpp` supersedes. `LiveSegment::AbsoluteVideoPtsUs` composes anchor + relative PTS at emission — that's the channel timeline. |
| `runtime/src/time/SystemTimeSource.cpp` + `.hpp` | Wall-clock source adapter. | Clock implementation mechanism. | build-new-in-air | Port as `SystemClock` conformer to `AuthoritativeClock`. |
| `runtime/src/runtime/TimingLoop.cpp` + `TimingLoop.h` | Deadline-driven tick loop; reports backpressure; injects MasterClock for tick identity and skew metrics. | Mechanism under **AIR_Pipeline** per `AIR_Pipeline.md §Boundary With Clock` — "reads authoritative time through an injected Clock reference for tick identity." Not a vault-named authority. | build-new-in-air | Will be the vNext pipeline tick driver. See Group 10. |
| `runtime/src/blockplan/OutputClock.cpp` + `OutputClock.hpp` + `IOutputClock.hpp` | Derives tick cadence + deadlines from MasterClock and channel fps. | Derived view of Clock + Rational; no separate authority. | delete / retire | Rolls into the AIR_Pipeline tick mechanism; Rational handles fps derivation. |

**Architectural reshape.**
- `Truth - Time Authorities Must Be Singular` + `INV-NORMALIZER-OUTPUT-CHANNEL-TIME-001` together make Clock the first authority constructed and the only time oracle in business logic. MasterClock is functionally correct but its UTC epoch + drift parameter need to map cleanly to `AuthoritativeClock.now_utc_ms()` + `monotonic_us()`.
- Phase 7C (durable timestamps) is documented as done; Phase 7D (control-plane Clock injection) is pending in the repo CLAUDE.md. vNext binary entry must not read wall-clock anywhere outside the Clock impl.
- `TimelineController` and `OutputClock` are mechanisms that expose derivations already present in `Rational`. In `air/` they collapse into `channel_canonical.hpp` arithmetic, which is a meaningful structural simplification.

---

## Group 4 — Source production & decode

| Today (path + class) | Today's responsibility | vNext shape | Action | Notes |
|---|---|---|---|---|
| `runtime/src/decode/FFmpegDecoder.cpp` + `FFmpegDecoder.h` (1589 lines) | Demux + decode video/audio; frame-offset seeking; letterbox scaling code at decoder level. | Decode mechanism lives *inside* a `SourceProducer` conformer per `SourceProducer.md`. Scaling is *not* here — it belongs to Normalizer per `INV-NORMALIZER-OUTPUT-CHANNEL-FORMAT-001`. | already-done-in-air | `air/src/file_source_producer.cpp` decodes via libavformat/libavcodec + libswresample. Scaling is in `StandardNormalizer`. |
| `runtime/src/decode/FrameProducer.cpp` + `FrameProducer.h` | Producer-side interface (base for producers). | `ISourceProducer` abstract interface per `source_producer.hpp`. | already-done-in-air | `air/include/source_producer.hpp` is the vNext contract. Mapping: runtime `FrameProducer` ≈ `ISourceProducer` but with channel-rendered output rather than source-canonical. |
| `runtime/src/producers/file/FileProducer.cpp` | Real-asset file-backed producer. | `FileSourceProducer` in `air/include/file_source_producer.hpp` — emits source-canonical PTS/format; lets Normalizer do scaling. | already-done-in-air | air/ version rejects non-YUV420P at Prepare (deferred), where runtime silently scaled. Tested against `SampleA.mp4` + `SampleB.mp4`. |
| `runtime/src/producers/black/BlackFrameProducer.cpp` | Pad producer (broadcast-black frames + silence). | `PadSourceProducer` in `air/include/pad_source_producer.hpp` — pre-allocated YUV420P + silence PCM; source PTS via `Rational::NthStepPtsUs`. | already-done-in-air | Zero per-tick allocation preserved. |
| `runtime/src/producers/programmatic/ProgrammaticProducer.cpp` | Synthetic/test producer. | `SyntheticSourceProducer` in `air/include/synthetic_source_producer.hpp` — configurable source framerate + sample rate; burned-in frame index in Y plane; constant/ramp/sine audio. | already-done-in-air | Contract-test-only; not production. |
| `runtime/src/blockplan/RealAssetSource.cpp` + `RealAssetSource.hpp` | BlockPlan-session wrapper around FileProducer. | PlaybackDirector `prepare(source_identity)` constructs a `FileSourceProducer` + Normalizer pair under its directive surface. `RealAssetSource` has no vault concept. | delete / retire | Wrapper is an artifact of PipelineManager's A/B slot pattern; not vault-shaped. |
| `runtime/src/blockplan/ProducerPreloader.cpp` + `ProducerPreloader.hpp` | Off-thread preload of the B producer. | Realised as PlaybackDirector's `prepare` directive issued to a not-yet-active producer per `PlaybackDirector.md §Orchestration Surface`. No vault-named "preloader." | delete / retire | The directive surface dissolves the need for a dedicated preloader class. |
| `runtime/src/blockplan/TickProducer.cpp` + `TickProducer.hpp` + `ITickProducer.hpp` + `ITickProducerDecoder.hpp` | Produces one tick's decoded frames on demand (wrapping decoder). | Pull-mode ISourceProducer does this per `SourceProducer.md §Interfaces` — the Normalizer is the primary pull-consumer. | already-done-in-air | `ISourceProducer::PullVideo()` / `PullAudio()` are the pull surface. |
| `runtime/src/blockplan/FFmpegDecoderAdapter.cpp` + `FFmpegDecoderAdapter.hpp` | Adapts common decoder into TickProducer surface. | FileSourceProducer adapts libav directly; no adapter layer. | delete / retire | Adapter existed because TickProducer and FFmpegDecoder had incompatible shapes; vNext collapses them. |
| `runtime/include/retrovue/blockplan/PadProducer.hpp` + `DefaultProducerFactory.hpp` + `IProducerFactory.hpp` | Producer-factory abstraction. | Construction is under PlaybackDirector's `prepare` directive per `PlaybackDirector.md §Instantiation`. No factory vault component. | delete / retire | Factory pattern is scaffolding; vault prescribes direct construction under directive. |

**Architectural reshape.**
- `Truth - Source Time Is Producer-Local, Channel Time Is Canonical` and `INV-NORMALIZER-SOLE-TRANSLATION-POINT-001` draw a hard line: runtime's producers emitted channel-rendered output (decoded + scaled). vNext producers emit source-canonical output only. Scaling moves out of the decoder.
- The A/B slot pattern (`blockplan`'s "active + pending" with SeamPreparer + ProducerPreloader) is a mechanism realization of the vault's "pending assignment" concept. vNext collapses this into PlaybackDirector's pending-assignment truth + `prepare` directive — one authority instead of three cooperating mechanisms.
- Producer health becomes a first-class signal per `INV-PRODUCER-FAILURE-OBSERVABLE-001`; readiness *consumption* of that signal moves to ReadinessController per `SourceProducer.md §Consumers`.

---

## Group 5 — Normalization (cadence, SRC, scale, format)

| Today (path + class) | Today's responsibility | vNext shape | Action | Notes |
|---|---|---|---|---|
| Scaling code inside `runtime/src/decode/FFmpegDecoder.cpp` (letterbox logic) | Source-to-channel resolution / pixel-format conversion at decode time. | **Normalizer** (per `Normalizer.md`). Aspect-preserving letterbox/pillarbox; no stretching. | already-done-in-air | `air/src/standard_normalizer.cpp` implements aspect-preserving scale via libswscale. Verified with `SampleA.mp4` at 720×480 → 968×720 from `cheers-24-7.yaml`. |
| Cadence resample inside `runtime/src/blockplan/TickProducer.cpp` | Video rate conversion interleaved with decode-pull, fill-thread pacing, TAKE cascade. | Normalizer video sub-normalizer per `Normalizer.md §Owned Truth`. 2:3, 4:5 pulldown etc. via `floor(k * src_num * ch_den / (ch_num * src_den))`. | already-done-in-air | Tested at 24→30, 60→30, NTSC ratios, identity. |
| `runtime/src/blockplan/FrameIndexedVideoStore.cpp` + `FrameIndexedVideoStore.hpp` | Cadence-repeat lookup keyed by source frame index. | Cadence repeats are Normalizer-internal pattern state. FIVS dissolves. Source-frame-index key violates `Truth - Source Time Is Producer-Local, Channel Time Is Canonical` (source-time leak into channel-canonical scope). | delete / retire | `BufferStore.md §Current-State Conformance` names FIVS as "non-conforming at archetype level" violating `INV-BUFFERSTORE-CONSUMPTION-SEMANTIC-EXTERNAL-001` *and* the producer-local/channel-canonical boundary. Dual violation. |
| Audio SRC (implicit in runtime; assumption was "source rate = channel rate") | None explicit. | Normalizer audio sub-normalizer per `Normalizer.md §Owned Truth` — SRC with sample-accurate PTS. | already-done-in-air | `StandardNormalizer` linear-interpolation SRC. Tested 44.1→48 constant, 44.1→48 ramp, 48→48 passthrough. Vault flags polyphase filter upgrade as deferred quality work. |
| PTS translation scattered across `PipelineManager`, `TickProducer` (priming correction), `FedBlock.asset_start_offset_ms` | None single-owned. | Normalizer channel-origin model: single `(source_pts_anchor, channel_pts_anchor)` per Normalizer instance per `INV-NORMALIZER-SHARED-CHANNEL-ORIGIN-001`. Tiered re-anchor per `INV-NORMALIZER-REANCHOR-BOUNDED-001`. | already-done-in-air | air/ consolidates via `Rational::NthStepPtsUs` + `ChannelOrigin`. Tier-2 re-anchor tested in `promotion_test.cpp`. |
| `air/include/standard_normalizer.hpp` + `src/standard_normalizer.cpp` | Cadence, SRC, scale, PTS translation. | Normalizer. Conformant. | already-done-in-air | No extension needed for current scope. Pixel-format fan-out (non-YUV420P) and audio channel-layout conversion flagged as deferred by `Normalizer.md §Deferred`. |
| `air/include/identity_normalizer.hpp` + `src/identity_normalizer.cpp` | Passthrough for already-at-rate sources. | Normalizer. Conformant. Pairs with `PadSourceProducer`. | already-done-in-air | Contract-validation use. |
| `runtime/include/retrovue/blockplan/LoudnessGain.hpp` + `BroadcastAudioProcessor.hpp` | Audio loudness/gain processing. | **Normalizer's audio sub-chain** (per-source). Sits alongside sample-rate conversion; applied before the source's audio reaches the preview buffer. | build-new-in-air | Product decision 2026-04-20: loudness is per-source, inside Normalizer. Different sources arrive at different loudness; AIR normalizes each so viewers never adjust TV volume. Not a separate post-Normalizer mechanism, not a vault gap — vault's `Normalizer.md` can now claim this authority. |

**Architectural reshape.**
- Normalization is the biggest structural vNext win already realised in `air/`. What runtime/ scattered across five files (FFmpegDecoder scaling, TickProducer cadence, FIVS repeat cache, PipelineManager PTS origin, FedBlock offset handling) collapses into one Normalizer per producer. Three bug families (`PTS_DRIFT_DETECTED`, cadence-phase reset at seams, `FIVS_MISS` at cadence-repeat ticks) are structurally excluded by construction, not patched.
- `INV-NORMALIZER-SOLE-TRANSLATION-POINT-001` makes translation a once-per-frame event at a single site. Downstream re-translation is prohibited — this permanently shrinks AIR_Pipeline's responsibilities (`CADENCE_REPEAT` branch disappears).
- FIVS is the most load-bearing deletion in this group. It violates two truths simultaneously.

---

## Group 6 — Buffering & storage

| Today (path + class) | Today's responsibility | vNext shape | Action | Notes |
|---|---|---|---|---|
| `runtime/src/blockplan/AudioLookaheadBuffer.cpp` + `AudioLookaheadBuffer.hpp` | Audio FIFO with silence-on-underflow; currently holds source-rate samples. | **BufferStore** (preview role) + additionally enforce `INV-PREVIEW-CHANNEL-CANONICAL-001` (migrate to channel rate). Archetype-conforming per `BufferStore.md §Current-State Conformance`. | already-done-in-air | `air/include/preview_buffer.hpp` → `AudioPreviewBuffer` is the vNext realisation. runtime's is archetype-conforming but at the wrong rate; the rate-canonicality migration is superseded by the Normalizer-produces-channel-rate property. |
| `runtime/src/blockplan/VideoLookaheadBuffer.cpp` + `VideoLookaheadBuffer.hpp` | Video FIFO + `AV_LEAD_CLAMP` overshoot policy + `audio_burst_active_` / `av_lead_clamp_bypass_active_` hysteresis + `drop_video_for_audio` liveness + `should_park_for_lookahead` park policy + fill-thread park/unpark directives. | **BufferStore** (preview role, storage only) per `BufferStore.md §Current-State Conformance`. The four policy domains extract to **PacingController** per `Truth - Storage Components Do Not Own Policy`. | extract-and-split | `BufferStore.md` explicitly calls this "non-conforming at archetype level." The storage half is realised in `air/VideoPreviewBuffer`; the policy half belongs to PacingController (Group 9, not yet built). |
| `runtime/src/buffer/FrameRingBuffer.cpp` + `FrameRingBuffer.h` | Legacy live ring buffer. | **BufferStore** in live role — but vNext realises "live role" by PlaybackDirector pointing its active assignment at an existing preview buffer (not a separate live-role class) per `BufferStore.md §Current-State Conformance`. | delete / retire | Live-role-as-distinct-class is explicitly retired; `BufferStore.md` specifies the pointer-swap pattern instead. |
| `air/include/preview_buffer.hpp` + `src/preview_buffer.cpp` (`VideoPreviewBuffer`, `AudioPreviewBuffer`) | Channel-canonical preview buffers; sole-writer = Normalizer; bounded; frontier/underflow/overflow observable; no peer-state admission; no directive emission. | BufferStore archetype, preview role. Adds `INV-PREVIEW-CHANNEL-CANONICAL-001` + `INV-PREVIEW-DESTINATION-PTS-CONTIGUOUS-001` per `BufferStore.md §Invariants`. | already-done-in-air | Fully conformant. Single-threaded first-slice scope is explicitly flagged in the header; thread-safety is added when fill-thread introduced (Group 9). |

**Architectural reshape.**
- `Truth - Storage Components Do Not Own Policy` is the defining reshape for this group. `VideoLookaheadBuffer`'s four co-located atomics are the canonical illustration of policy accretion at a storage component; `PacingController` exists to receive them.
- vNext's novel move is not implementing "live-role BufferStore" as a class at all. `BufferStore.md §Preview vs. Live Role Distinction` explicitly says role is a binding property, not an implementation property. `air/PlaybackDirector::ActiveAssignment` realises this — the same preview instance becomes "live" by virtue of being pointed at.
- `INV-BUFFERSTORE-SOLE-WRITER-001`, `INV-BUFFERSTORE-NO-POLICY-OWNERSHIP-001`, `INV-BUFFERSTORE-NO-DIRECTIVE-EMISSION-001`, `INV-BUFFERSTORE-NO-PEER-STATE-ADMISSION-001` all hold in `air/` preview buffers by construction.

---

## Group 7 — Readiness & kickoff gating

| Today (path + class) | Today's responsibility | vNext shape | Action | Notes |
|---|---|---|---|---|
| `runtime/src/readiness/ReadinessEvaluator.cpp` + `ReadinessEvaluator.h` | Signal consumption + verdict derivation. | **ReadinessController** (verdict authority) per `ReadinessController.md`. Single-owner per `INV-READINESS-SINGLE-OWNER-001`; bounded states per `INV-VERDICT-BOUNDED-STATES-001` ({READY, NOT_READY, DEGRADED}); bounded reason class per `INV-VERDICT-REASON-CLASS-BOUNDED-001`. | build-new-in-air | runtime/ contract tests (29/29 GREEN) are reference. air/ has no ReadinessController yet. |
| `runtime/src/readiness/ReadinessObserver.cpp` + `ReadinessObserver.h` | Transition-stream emission. | Merged into ReadinessController observability surface per `INV-READINESS-OBSERVABLE-001`. | build-new-in-air | Transitions emit with injected Clock timestamps per `Clock.md §Boundary With ReadinessController`. |
| `runtime/include/retrovue/readiness/ReadinessSignals.hpp` + `ReadinessVerdict.h` | Signal + verdict data types. | Retain as ReadinessController input/output types. | build-new-in-air | Port structure; no architectural change. |
| `runtime/src/bootstrap/BootstrapContentGate.cpp` + `BootstrapContentGate.h` | Sole kickoff authority in runtime/ (D+1 consolidation retired legacy `phase_valid`). Evaluates depth-floors + source-alignment directly from buffer snapshots. | **BootstrapContentGate** per `BootstrapContentGate.md`. In target state consumes aggregate readiness as *input* from ReadinessController, retains only the kickoff-specific source-alignment precondition. Atomic, sticky, once-per-session per `INV-BOOTSTRAP-KICKOFF-ONCE-001`. | build-new-in-air | runtime/ version is current-state vault-canonical (§ Lifecycle: "Current State (landed)"). 19 contract tests reference. Transitional in runtime/ — target state requires readiness-as-input, not self-evaluated. |
| `runtime/src/bootstrap/BootstrapGateEvaluator.cpp` + `BootstrapGateEvaluator.h` + `BootstrapCommand.h` | Pure-function predicate evaluator; kickoff directive payload. | BootstrapContentGate internal mechanism + kickoff directive type. | build-new-in-air | Port the pure-evaluator shape; it matches vault's "kickoff is a pure function of inputs" posture. |

**Architectural reshape.**
- These two authorities are vault-canonical already in runtime/ (they were the first two to conform). The reshape here is *porting to `air/`*, not restructuring responsibility. Both are clean extractions.
- In the target state (`BootstrapContentGate.md §Lifecycle: Transitional`), BootstrapContentGate calls ReadinessController for aggregate readiness instead of re-deriving depth-floors. This dependency ordering is why ReadinessController is constructed before BootstrapContentGate per `PlaybackDirector.md §Instantiation & Construction`.
- Kickoff directive delivery mechanism (sync callback vs. queue vs. bus) is explicitly named as `Flow - Tune-In` gap #3.

---

## Group 8 — Seam & successor

| Today (path + class) | Today's responsibility | vNext shape | Action | Notes |
|---|---|---|---|---|
| `runtime/src/seam/SeamController.cpp` + `SeamController.h` + `SeamCommand.h` | Seam arming/firing/commit phases. | **SeamController** per `SeamController.md`. Full lifecycle (begin → armed → firing → committed → recovered → complete) per `§Seam Transition Lifecycle`. `INV-SEAM-SINGLE-EXECUTION-001`, `INV-SEAM-SINGLE-AUTHORITY-001`, `INV-SEAM-MISSED-RESOLUTION-001`. Dispositions: `switch-now`, `engage-pad`, `JIP-at-offset`. | build-new-in-air | runtime/ SeamController is in-flight (transitional per `07_problems/SeamController Invariant Reconciliation (Turn A0).md`); air/ has no equivalent. |
| `runtime/src/seam/SeamEvaluator.cpp` | Evaluates seam preconditions. | SeamController internal mechanism; reads ReadinessController verdicts per `SeamController.md §Consumers`. | build-new-in-air | Not a separate authority. |
| `runtime/src/blockplan/SeamPreparer.cpp` + `SeamPreparer.hpp` | Prepares the "B" producer ahead of seam (part of the A/B-slot mechanism in PipelineManager). | Subsumed into PlaybackDirector's `prepare` directive for the pending assignment. SeamController only triggers promotion at the seam moment. | delete / retire | The prepare-at-seam semantics are already PlaybackDirector's per `PlaybackDirector.md §Orchestration Surface`. "Preparer" vocabulary is not vault-shaped. |
| `runtime/include/retrovue/blockplan/SeamProofTypes.hpp` | Seam observability proof structures. | Mechanism under SeamController observability. | build-new-in-air | Port as observability types alongside seam events. |
| `runtime/src/standalone/SeamVerifyMain.cpp` + `SeamSegmentTest.cpp` | Standalone seam verification binaries. | Not vault-named. Artefacts of seam debugging. | delete / retire | Development tooling. Replace with contract tests under `air/tests/contracts/`. |

**Architectural reshape.**
- SeamController's target-state relationship to PacingController is `one-way phase observation, not cross-authority writes` per `SeamController.md §Boundary With PacingController`. Recovery state on either side is read by the other but not written.
- Seam *execution* at the frame level is AIR_Pipeline's job per `AIR_Pipeline.md §Owned Truth`; SeamController decides *when* and *which disposition*. The mechanism boundary is directive-based.
- The A/B producer slot mechanism in PipelineManager is the load-bearing runtime/ pattern that dissolves once PlaybackDirector owns pending-assignment truth and SeamController owns seam decisions.

---

## Group 9 — Pacing (admission + egress)

| Today (path + class) | Today's responsibility | vNext shape | Action | Notes |
|---|---|---|---|---|
| `AV_LEAD_CLAMP` inside `VideoLookaheadBuffer` | Lead/overshoot control. | **PacingController** per `PacingController.md §Owned Truth` ("Is video overshooting its allowable lead against audio?"). `INV-PACING-SINGLE-AUTHORITY`. | build-new-in-air | Pure extraction; storage becomes storage-only. |
| `audio_burst_active_`, `av_lead_clamp_bypass_active_` inside `VideoLookaheadBuffer` | Starvation-recovery hysteresis. | PacingController per `PacingController.md §Owned Truth` ("Is audio starving?"). `INV-AUDIO-LIVENESS`. | build-new-in-air | Same extraction. |
| `drop_video_for_audio` inside `VideoLookaheadBuffer` | Liveness response (suppress video frame so audio catches up). | PacingController `suppress_video_this_tick(reason)` directive per `PacingController.md §Outputs`. | build-new-in-air | Directive-issued, not self-decided by storage. |
| `should_park_for_lookahead` inside `VideoLookaheadBuffer` | Fill-thread park policy (hard-cap-before-hysteresis ordering bug is a symptom). | PacingController `park/unpark` directive per `PacingController.md §Outputs`. Ordering becomes published contract. | build-new-in-air | `Truth - Storage Components Do Not Own Policy §Migration Notes` calls this ordering bug out explicitly. |
| `GateOutputTiming` inside `EncoderPipeline` (egress bitrate / PCR pacing) | Real-time egress rate discipline — emit at channel-rate bytes-per-second. | Egress pacing is a separate concern from admission pacing. **No clear vault owner**; PacingController covers admission. `AIR_Pipeline.md §Owned Truth` claims "mux/output byte production" — egress pacing is a mechanism under that. | build-new-in-air | **Vault gap**: admission-pacing owner is clear; egress-pacing ownership is implicit at best. |
| `GenerateSilenceFrames` inside `EncoderPipeline` | Audio silence injection for liveness. | PadSourceProducer already emits silence (`pad_source_producer.hpp`); vNext's cleaner structure is silence-as-a-source, not silence-as-encoder-hack. | already-done-in-air | Pad audio stream is first-class. The encoder never manufactures silence in vNext. |

**Architectural reshape.**
- PacingController is the single biggest "extract authority from storage" reshape. Four policy domains consolidate into one authority per `Truth - Storage Components Do Not Own Policy §Migration Notes`.
- The split between *admission pacing* (PacingController, authority-owned) and *egress pacing* (mechanism under AIR_Pipeline, no named owner) is under-specified in the vault — flagged as vault gap.
- PacingController depends on Clock, AudioBuffer observability, VideoBuffer observability per `PacingController.md §Dependencies`. Construction order slot #3 per `PlaybackDirector.md §Instantiation & Construction`.
- `PacingController.md §Open Questions` flags sync-vs-async directive transport as unresolved.

---

## Group 10 — Pipeline tick & emission orchestration

| Today (path + class) | Today's responsibility | vNext shape | Action | Notes |
|---|---|---|---|---|
| `runtime/src/blockplan/PipelineManager.cpp` + `PipelineManager.hpp` | Per-tick loop; owns active + pending producers (A/B slots); 9-branch TAKE cascade (PAD_SEAM_OVERRIDE → CONTENT_SEAM_OVERRIDE → CADENCE_REPEAT → NORMAL_ADVANCE → BLOCK_FENCE → SEGMENT_SEAM_HOLD → GENUINE_UNDERFLOW → PRIMED_NO_DECODER → NOT_PRIMED); bootstrap gate call site; mux bridge. | Splits four ways: **AIR_Pipeline** (per-tick execution; emit-every-tick per `INV-CASCADE-GUARANTEED-EMISSION-001`; simplified cascade once upstream authorities exist) + **PlaybackDirector** (active/pending assignment — already partially in air/) + **SeamController** (seam branches) + **PacingController** (admission branches) + **Normalizer** (CADENCE_REPEAT). | extract-and-split | PipelineManager is the most splintered runtime/ component. `AIR_Pipeline.md §Migration Notes: May evolve` explicitly expects the cascade to shrink. |
| `runtime/include/retrovue/blockplan/IPlayoutExecutionEngine.hpp` | Execution-engine interface pattern. | Collapsed into AIR_Pipeline directly. | delete / retire | Interface abstraction is scaffolding. |
| `runtime/src/renderer/ProgramOutput.cpp` + `ProgramOutput.h` (1441 lines) | Per-tick "commit a frame" authority driving OutputBus; holds mux-callback connection; connect/disconnect to OutputBus. | Mechanism under AIR_Pipeline per `AIR_Pipeline.md §Owned Truth` ("per-tick execution realization"). Not a separate authority. | build-new-in-air | Port as the commit mechanism inside AIR_Pipeline. |
| `runtime/src/renderer/FrameRenderer.cpp` + `FrameRenderer.h` | Takes selected frame each tick, hands off. | Mechanism under AIR_Pipeline emission. | build-new-in-air | Thin; likely inlines into AIR_Pipeline. |
| `runtime/include/retrovue/blockplan/IWaitStrategy.hpp` + `PipelineMetrics.hpp` + `PlaybackTraceTypes.hpp` + `RationalFps.hpp` + `VideoBufferFrame.hpp` + `BlockPlanTypes.hpp` + `BlockPlanSessionTypes.hpp` + `BlockPlanValidator.hpp` | Blockplan types + helpers + tracing. | Data types and helpers; not authorities. Port selectively as needed. | build-new-in-air | `RationalFps.hpp` already superseded by `air/channel_canonical.hpp:Rational`. |

**Architectural reshape.**
- `AIR_Pipeline.md §Migration Notes: Pipeline input becomes channel-canonical post-migration` details exactly how the TAKE cascade shrinks. Three branches migrate out: `CADENCE_REPEAT` → Normalizer; seam branches → SeamController; admission/overshoot → PacingController. The cascade reduces to emission, fence-budget, and underflow handling.
- `INV-CASCADE-GUARANTEED-EMISSION-001`, `INV-CONTENT-BEFORE-PAD-IDR-001`, `INV-PTS-CORRECTION-SINGLE-PATH-001` are all AIR_Pipeline contractual guarantees. `INV-PTS-CORRECTION-SINGLE-PATH-001` reduces to a no-op in AIR_Pipeline (enforcement migrates to Normalizer per `AIR_Pipeline.md §Migration Notes`) — the guarantee persists, the enforcer changes.
- `Flow - Tune-In` gap #4 (output boundary opening moment unspecified) names the unresolved sequencing question here.

---

## Group 11 — Encoder & muxer mechanisms

| Today (path + class) | Today's responsibility | vNext shape | Action | Notes |
|---|---|---|---|---|
| `runtime/src/playout_sinks/mpegts/EncoderPipeline.cpp` + `EncoderPipeline.hpp` (2475 lines) | x264/NVENC + AAC + YUV420P input + SwsContext + IDR gate + per-segment video counter + sample-counter audio PTS + silence injection + MPEG-TS muxer + MuxInterleaver + PCR pacing + window counters. | Mechanism under AIR_Pipeline per `AIR_Pipeline.md §Boundary With Output Sinks and AIR_Boundary`. Responsibilities narrow: silence → PadSourceProducer (Group 4/5); scaling → Normalizer (Group 5); PCR pacing → egress (Group 9, gap); SwsContext → gone (input is channel-canonical per `AIR_Pipeline.md §Migration Notes`). Remaining: frames-in-channel-canonical, TS-packets-out. | build-new-in-air | Much smaller in vNext. `INV-CONTENT-BEFORE-PAD-IDR-001` remains enforced at encoder per `AIR_Pipeline.md §Invariants`. |
| `runtime/src/playout_sinks/mpegts/MpegTSEncoder.cpp` + `MpegTSEncoder.h` (82-line legacy shim) | Thin wrapper over EncoderPipeline. | Not needed. | delete / retire | Legacy shim. |
| `runtime/include/retrovue/playout_sinks/mpegts/MuxInterleaver.hpp` | Global DTS monotonic ordering; startup holdoff gate. | Mechanism under AIR_Pipeline; narrower (no silence-injection specials). Still required (encode latencies differ across streams). | build-new-in-air | Port with silence-injection cases removed. |
| `runtime/src/playout_sinks/mpegts/PTSController.cpp` + `PTSController.hpp` (67 lines) | PTS rescale helpers. | Utility under AIR_Pipeline emission; pure math. | build-new-in-air | Port as helpers. |
| `runtime/src/playout_sinks/mpegts/ClockUtils.cpp` + `ClockUtils.hpp` | 90 kHz conversions. | Utility under AIR_Pipeline; pure math. | build-new-in-air | Port as helpers. |
| `runtime/include/retrovue/playout_sinks/mpegts/MpegTSPlayoutSink.h` + `MpegTSPlayoutSinkConfig.hpp` + `SinkConfig.h` + `SinkStats.h` | Sink-level typing + config. | Configuration types under AIR_Pipeline emission mechanism. | build-new-in-air | Port selectively. |
| `runtime/include/retrovue/sinks/IPlayoutSink.h` + `output/IOutputSink.h` | Sink abstract interfaces. | Per `AIR_Pipeline.md §Boundary With Output Sinks`: "Output sinks are implementation mechanisms, not authority owners." Retain interface as internal mechanism surface. | delete / retire or build-new-in-air | Vault explicitly demotes to mechanism; may not even be needed as an interface. |

**Architectural reshape.**
- The 2475-line `EncoderPipeline` shrinks dramatically because several of its responsibilities migrate to proper vNext owners: silence to PadSourceProducer, scaling to Normalizer, PCR pacing to egress mechanism. The residue is "frames → TS packets" — significantly smaller.
- Encoder is the primary enforcement site for `INV-CONTENT-BEFORE-PAD-IDR-001` and — in current runtime — `INV-ENCODER-SWS-COHERENCE-001`. The latter dissolves in vNext because scaling happens upstream.
- `AIR_Safety.md §INV-BUFFER-HEADROOM-COMPILE-GUARD-001` (≥8MB sink buffer at compile time), `§INV-ENV-VAR-PRODUCTION-LOCKOUT-001` (debug env vars no-op in prod), `§INV-AUDIO-SAMPLE-INTEGER-MATH-001` (128-bit int arithmetic for audio sample count) are all enforceable at the vNext encoder/mux mechanism boundary.

---

## Group 12 — Transport (socket)

| Today (path + class) | Today's responsibility | vNext shape | Action | Notes |
|---|---|---|---|---|
| `runtime/src/output/OutputBus.cpp` + `OutputBus.h` | Fan-in from ProgramOutput; fan-out to attached IOutputSink. | Mechanism under AIR_Pipeline emission — not a vault authority. | delete / retire | Fan-out was a multi-sink-per-session pattern. Single-session vNext has one downstream path. |
| `runtime/src/output/MpegTSOutputSink.cpp` + `MpegTSOutputSink.h` (1608 lines) | Wraps EncoderPipeline + SocketSink; enforces `O_NONBLOCK`; throttle-vs-detach policy; liveness counters; wires packet-capture into MuxInterleaver. | Mechanism under AIR_Pipeline emission; composes EncoderPipeline + socket. | build-new-in-air | Much narrower: `O_NONBLOCK` enforcement and MuxInterleaver wiring survive; **throttle/detach policy is deleted** — product rule says AIR never throttles, never detaches, drops on full. Liveness counters preserved for observability. |
| `runtime/src/output/SocketSink.cpp` + `SocketSink.h` (441 lines) | Non-blocking UDS/TCP byte consumer; writer thread with `poll()`+`send()`; bounded buffer high/low water marks; detach-vs-throttle policy; slow-consumer detection; `SIGPIPE`/`EPIPE` handling. | Mechanism under **AIR_Boundary** transport per `AIR_Boundary.md §Interfaces` — carries bytes. Transport contract is UDS per channel. | build-new-in-air | **Policy gap closed by product decision 2026-04-20.** vNext socket writer: small bounded buffer, drop-on-full with counter, no hysteresis watermarks, no slow-consumer detection, no detach, no throttle. Keep `SIGPIPE`/`EPIPE` safety for crash-avoidance. AIR emits unconditionally; slow consumer is the consumer's problem. |
| `runtime/src/output/SinkDiagnostics.cpp` + `SinkDiagnostics.h` | Common detach logging + `AirShutdownFired()` marker. | Observability under AIR_Observability (partial) / AIR_Lifecycle (shutdown). | build-new-in-air | Port; small, shared. |

**Architectural reshape.**
- The socket transport has a named vault owner (AIR_Boundary for contract; mechanism under AIR_Pipeline for emission). The *policy* layered on top — detach vs. throttle — was previously an unresolved vault gap. **Resolved 2026-04-20:** no policy. AIR never throttles, never detaches, drops on full. Slow consumer is consumer's problem (product rule 1). SocketSink's runtime/ policy does not port.
- `INV-SINK-EXPLICIT-EXIT-001` (`AIR_Runtime.md`) requires the transport emission loop to exit only on explicit stop; fd invalidation triggers recovery, not termination. Must port — but "recovery" in vNext is minimal since disconnect is terminal (product rule 7).
- `INV-UDS-DRAIN-FROM-ATTACH-001` (`AIR_Boundary.md`) requires AIR to write immediately after `AttachStream` returns, with Core draining from that instant. This constrains the vNext sequencing of socket-emitter construction in the session-start path.
- Product rule: AIR emits only after consumer (Core) connects via `AttachStream`. Socket file is created at AIR startup; emission loop begins on attach. No bytes buffered into limbo.

---

## Group 13 — Observability / evidence / metrics

| Today (path + class) | Today's responsibility | vNext shape | Action | Notes |
|---|---|---|---|---|
| `runtime/src/telemetry/MetricsExporter.cpp` + `MetricsExporter.h` | Prometheus metrics aggregation. | **AIR_Observability** — `AIR_Observability.md` is thin (24 lines) with one invariant (`INV-FATAL-UNDERFLOW-VISIBILITY-001`). Aggregation surface is an unresolved gap per `Flow - Tune-In` gap #5. | build-new-in-air | Port as observability aggregation mechanism; vault under-specifies the aggregation contract. |
| `runtime/src/telemetry/MetricsHTTPServer.cpp` + `MetricsHTTPServer.h` | HTTP `/metrics` endpoint. | Mechanism under AIR_Observability. | build-new-in-air | Transport mechanism. |
| `runtime/src/evidence/EvidenceEmitter.cpp` + `EvidenceEmitter.hpp` | As-run / proof record emission to Core. | AIR_Observability (proof-record side). `AIR_Runtime.md INV-EVIDENCE-FENCE-SWAP-STRUCTURED-001` is the contractual guarantee; mechanism lives in AIR_Observability. | build-new-in-air | |
| `runtime/src/evidence/EvidenceSpool.cpp` + `EvidenceSpool.hpp` | Buffered evidence spool (handles backpressure to Core). | AIR_Observability mechanism. | build-new-in-air | |
| `runtime/src/evidence/GrpcEvidenceClient.cpp` + `GrpcEvidenceClient.hpp` | gRPC client shipping evidence to Core. | AIR_Boundary surface (Core is the server for evidence upload). | build-new-in-air | Boundary-side adapter. |
| `runtime/src/util/ObservabilityLogger.cpp` + `ObservabilityLogger.hpp` | Structured logger. | AIR_Observability mechanism. | build-new-in-air | |
| `runtime/src/util/Logger.cpp` + `Logger.hpp` | Generic logger. | Utility. | build-new-in-air | Port if needed; probably replace with spdlog or similar. |

**Architectural reshape.**
- Observability has a thin vault surface. `Flow - Tune-In` gap #5 names "AIR observability aggregation owner unnamed" as unresolved — which components publish where, and what aggregator does Core read from, are vault-silent.
- `INV-FATAL-UNDERFLOW-VISIBILITY-001` is the only specified observability invariant, currently DISABLED in runtime tests per `ReadinessController.md §Enforcement`.
- Evidence is split across two boundaries in runtime/ (emitter + spool inside AIR; gRPC client at the boundary). vNext preserves this split.

---

## Group 14 — Process / binary / signal handling

| Today (path + class) | Today's responsibility | vNext shape | Action | Notes |
|---|---|---|---|---|
| `runtime/src/main.cpp` | Binary entry, signal handling, FFmpeg global init, server bind, construction order. | Mechanism under **AIR_Lifecycle** + **AIR_Safety**. | build-new-in-air | `air/` has no binary yet; `NEXT_STEPS_PLAN.md` Step 8 scopes a first Stage-1 binary. |
| `runtime/src/util/AirMemoryMonitor.cpp` + `AirMemoryMonitor.hpp` | Process memory telemetry. | Mechanism under AIR_Observability / AIR_Safety. | build-new-in-air | Port if needed. |
| `runtime/src/util/MemoryUtils.cpp` + `MemoryUtils.hpp` | Memory helpers. | Utility. | build-new-in-air | Port selectively. |
| SIGPIPE / SIGINT handlers inside `main.cpp` | Crash, shutdown, EPIPE safety. | AIR_Safety mechanism. | build-new-in-air | `AIR_Safety.md §INV-ENV-VAR-PRODUCTION-LOCKOUT-001` applies to the binary's env-var handling. |
| `runtime/src/standalone/SeamVerifyMain.cpp` + `SeamSegmentTest.cpp` | Development-time verification binaries. | Not vault-named; replace with contract tests. | delete / retire | Development artifact. |
| `runtime/CLAUDE.md`, `THICK PROMPT.md`, `CONTRIBUTING.md`, `BUILD_CONTRACTS.sh`, `INSTALL_VCPKG_PACKAGES.sh`, `CMakePresets.json` | Build + dev-process documentation. | vNext will carry its own equivalents. | (project-hygiene; out of transformation scope) | |

**Architectural reshape.**
- Construction ordering at binary entry must obey `PlaybackDirector.md §Instantiation & Construction` (Clock → Readiness → Pacing → BootstrapContentGate → PlaybackDirector → SourceProducers). runtime/'s `main.cpp` constructs MasterClock then PlayoutEngine directly; vNext needs the full five-step sequence.
- Signal handling and FFmpeg init are AIR_Safety mechanisms with no vault authority; port cleanly.

---

## What gets deleted outright

Concepts the vault explicitly retires or splits such that no vNext component exists with the same shape:

- **`PlayoutControl` preview/live state machine** (`runtime/src/runtime/PlayoutControl.cpp`) — `INV-AIR-NO-ADHOC-SWITCHING-001` and `INV-AIR-NO-SEGMENT-DRIVEN-EXECUTION-001` forbid the preview→live choreography.
- **`SwitchWatcher` thread** (inside `PlayoutEngine.cpp`) — deadline-driven switch execution is retired; promotion is directive-driven.
- **`channels_` map** (inside `PlayoutEngine.cpp`) — single-session charter per `INV-SESSION-SINGLE-ACTIVE-001`.
- **`ProducerBus`** (`runtime/src/runtime/ProducerBus.cpp`) — subsumed by `PlaybackDirector`'s active/pending-assignment truth.
- **`PlayoutController`** (`runtime/src/runtime/PlayoutController.cpp`) — subsumed by `PlaybackDirector`'s orchestration surface.
- **`PlayoutInterface`** (`runtime/src/runtime/PlayoutInterface.cpp`) — wrapper layer obsolete.
- **`FrameIndexedVideoStore`** (`runtime/src/blockplan/FrameIndexedVideoStore.cpp`) — violates `INV-BUFFERSTORE-CONSUMPTION-SEMANTIC-EXTERNAL-001` *and* `Truth - Source Time Is Producer-Local, Channel Time Is Canonical` simultaneously.
- **`FrameRingBuffer`** (`runtime/src/buffer/FrameRingBuffer.cpp`) — live-role-as-distinct-class retired; pointer-swap pattern replaces it per `BufferStore.md §Current-State Conformance`.
- **`RealAssetSource`** (`runtime/src/blockplan/RealAssetSource.cpp`) — A/B-slot-era wrapper.
- **`ProducerPreloader`** (`runtime/src/blockplan/ProducerPreloader.cpp`) — collapses into PlaybackDirector's `prepare` directive.
- **`TickProducer`** (`runtime/src/blockplan/TickProducer.cpp`) + **`FFmpegDecoderAdapter`** (`runtime/src/blockplan/FFmpegDecoderAdapter.cpp`) — ISourceProducer pull surface replaces both.
- **`SeamPreparer`** (`runtime/src/blockplan/SeamPreparer.cpp`) — prepare-at-seam is PlaybackDirector; seam-firing is SeamController.
- **`OutputClock`** (`runtime/src/blockplan/OutputClock.cpp`) + **`IOutputClock`** (`runtime/include/retrovue/blockplan/IOutputClock.hpp`) — Rational + Clock collapse this role.
- **`OutputBus`** (`runtime/src/output/OutputBus.cpp`) — fan-out layer obsolete in single-session.
- **`DefaultProducerFactory`** + **`IProducerFactory`** (`runtime/include/retrovue/blockplan/DefaultProducerFactory.hpp`, `IProducerFactory.hpp`) — factory pattern is scaffolding; direct construction under directive.
- **`IWaitStrategy`** (`runtime/include/retrovue/blockplan/IWaitStrategy.hpp`) + `IPlayoutExecutionEngine` — interface abstractions not vault-shaped.
- **`MpegTSEncoder`** (`runtime/src/playout_sinks/mpegts/MpegTSEncoder.cpp`, 82-line legacy shim) — EncoderPipeline replaced it already.
- **`SeamVerifyMain`** + **`SeamSegmentTest`** (`runtime/src/standalone/`) — standalone dev binaries; replace with contract tests.
- **Legacy `phase_valid` gate** (already retired in runtime/ D+1) — retained here for the record.
- **`LoadPreview`, `SwitchToLive`, `UpdatePlan` RPCs** on the gRPC surface — `AIR_Boundary.md §Prohibited`.

---

## What air/ has that runtime/ never did

vNext-native structural wins already proven in `/opt/retrovue/air/`:

- **Source-canonical-producer + per-source Normalizer split** — `ISourceProducer` emits source-canonical; `StandardNormalizer`/`IdentityNormalizer` translate to channel-canonical. Runtime producers emit rendered output; the boundary is absent.
- **Channel-origin model** — `(source_pts_anchor, channel_pts_anchor)` per Normalizer, shared across audio and video sub-normalizers. Drift-free `Rational::NthStepPtsUs`. Tiered re-anchor tested. Runtime has no equivalent single-origin mechanism.
- **Aspect-preserving video scaling** as a first-class Normalizer responsibility — verified end-to-end with real H.264 at 720×480 → 968×720 letterbox. Runtime's scaling is at the decoder level.
- **Preview BufferStore conformant to archetype** — `VideoPreviewBuffer`/`AudioPreviewBuffer` with no policy accretion, no peer-state admission, no directive emission. Runtime's `VideoLookaheadBuffer` has four policy domains co-located.
- **Live-role-by-pointer pattern** — `PlaybackDirector::ActiveAssignment()` realises live role without a live-role class. Runtime has `FrameRingBuffer` as a separate live storage, plus a live/preview split state machine.
- **Drift-free rational arithmetic** — `Rational::NthStepPtsUs(k)` uses `(n * 1e6 * den + num/2) / num` rounding. Runtime's `TimelineController` derives timeline bookkeeping with accumulated `PeriodMicros` (can drift ~1us/step over long segments).
- **PTS continuity across promotion by construction** — `promotion_test.cpp` proves it. Runtime compensates with post-handoff transition drain (retired in D+1 alongside `phase_valid`).

---

## Gaps in the vault itself

Originally 10 gaps. 6 closed by product/design decisions on 2026-04-20; 2 partially resolved; 2 still open. The vault itself still needs updates to absorb the closures — see "Vault updates owed" at end.

**Closed by product/design decisions (2026-04-20):**

- ✅ **#1 SocketSink detach-vs-throttle policy authority.** RESOLVED: no policy. AIR never throttles, never detaches. Drop-on-full. Product rule 1. SocketSink policy in runtime/ does not port.
- ✅ **#4 PlaybackDirector instantiation surface.** RESOLVED: PD is constructed once at binary startup and lives for the process lifetime. No per-session factory. 1-process-1-channel-1-session rule (product rule 4).
- ✅ **#6 Output boundary opening moment.** RESOLVED: socket file is created at AIR startup. Emission loop begins on `AttachStream` (product rule 5). AIR does not emit bytes before consumer connects.
- ✅ **#7 BroadcastAudioProcessor / LoudnessGain authority.** RESOLVED: loudness is owned by Normalizer as a per-source audio sub-chain (product rule 2). Sits alongside sample-rate conversion, applied per-source before preview buffer.
- ✅ **#8 Pad-always-present invariant.** RESOLVED: pad source producer is constructed at AIR startup (before the emission loop begins) and its buffer is available from the first tick of emission. This is a consequence of product rule 5 (emit-only-after-consumer-connects) combined with PadSourceProducer being a first-class always-on producer.
- ✅ **#10 PlaybackDirector ↔ BootstrapContentGate coordination at kickoff.** RESOLVED: org-chart model + arm/commit mechanism. BootstrapContentGate arms the successor via `PD.ArmSuccessor(content, target_tick)`; PD commits on `CommitSuccessor(tick)` at the frame-commit point. No "pre-activation vs. gate-fires-and-PD-reacts" ambiguity — the arm/commit pattern collapses both into one model. PD never observes raw signals; it executes pre-committed directives.

**Partially resolved:**

- ◐ **#2 Egress pacing (bitrate rate-limiting) ownership.** Product rule 3 confirms egress is paced to channel frame rate (real-time), distinct from PacingController admission. Mechanism is a mechanism under AIR_Pipeline emission (what runtime calls `GateOutputTiming`). Ownership now has a home (AIR_Pipeline) but still needs an explicit vault name for the sub-mechanism. Vault update owed.
- ◐ **#9 SourceProducer `prepare/activate/retire` sequencing relative to kickoff.** Covered in the general case by the arm/commit pattern — producers are prepared by PD's `ArmSuccessor` and retired by failed-assignment retirement (AIR_Lifecycle). But the precise per-method semantics (`prepare` vs `activate` vs `retire`) still want explicit vault documentation. Vault update owed.

**Still open (not touched by 2026-04-20 decisions):**

- ☐ **#3 AIR_Observability aggregation surface.** `Flow - Tune-In` gap #5: `AIR_Observability.md` is 24 lines with one invariant; aggregation owner unnamed. Every other controller claims "emits observability" without a named consumer contract. Still a vault gap. Per-component callbacks are sufficient through vNext Step 14; raise as vault update when emit sites exceed ~6.
- ☐ **#5 Kickoff directive delivery mechanism.** `Flow - Tune-In` gap #3: sync callback vs. event queue vs. directive bus is unspecified in `BootstrapContentGate.md`. The arm/commit pattern constrains it (PD must accept `ArmSuccessor` calls asynchronously from any thread and drain at `CommitSuccessor`) but the concrete queue/bus mechanism is still unspecified.

**Vault updates owed (to absorb 2026-04-20 decisions):**

- `AIR_Boundary.md` — document "no throttle, no detach, drop-on-full" as explicit non-policy for the socket transport.
- `PlaybackDirector.md` — document `ArmSuccessor` / `CommitSuccessor` surface and retire legacy `prepare/activate/retire/promote` vocabulary.
- `Normalizer.md` — claim authority for loudness normalization (per-source audio sub-chain).
- `AIR_Lifecycle.md` — document ownership of **failure transition class** (retires current assignment on irrecoverable fault, arms pad-bridge, arms successor).
- `SeamController.md` — document explicit state machine `observing → armed → committed_for_tick(N) → executed` with `target_tick` directives. Clarify SeamController owns only the **scheduled transition class**, not runtime faults.
- New vault doc: **Transition Classes** — document the three-class taxonomy (scheduled / bootstrap / failure) with three owners sharing one mechanism.
- `AIR_Pipeline.md` — name the egress rate-limit pacing sub-mechanism (the vault has no name for what runtime calls `GateOutputTiming`).

**New architectural insight (not yet a vault doc): three transition classes with three owners.**

| Class | Trigger | Owner | Status |
|---|---|---|---|
| Scheduled | Fence tick reached on healthy content | SeamController | Vault spec exists; needs state-machine clarification |
| Bootstrap | Cold start pad → first content | BootstrapContentGate | Vault spec exists |
| Failure | Current assignment faulted / invalidated | AIR_Lifecycle (PD failure path) | Not yet vault-named as a transition class |

The **mechanism** — `ArmSuccessor(assignment, target_tick)` + `CommitSuccessor(tick)` — is shared across all three classes. The **decision** is owned per cause, not per mechanism. This prevents SeamController from becoming the garbage truck for runtime faults (as runtime/'s `PipelineManager` did with its 9-branch cascade).

---

### Critical Files for Implementation

The three-to-five files most load-bearing for executing this transformation:

- `/opt/retrovue/air/include/playback_director.hpp` — extension point for the broadcast-vocabulary directive surface (`ArmSuccessor` / `CommitSuccessor`, pending-assignment, kickoff sequencing); Group 1.
- `/opt/retrovue-obsidian/Retrovue/00_components/PlaybackDirector.md` — the vault spec that governs the extension; contains the authoritative construction order.
- `/opt/retrovue-obsidian/Retrovue/00_components/BootstrapContentGate.md` — the kickoff authority spec; plus `/opt/retrovue-obsidian/Retrovue/00_components/ReadinessController.md` for the readiness-as-input target state.
- `/opt/retrovue/runtime/src/bootstrap/BootstrapContentGate.cpp` — reference implementation to port to `air/`; carries the 19-test contract model.
- `/opt/retrovue/runtime/src/blockplan/PipelineManager.cpp` — the most complex extract-and-split target; its 9-branch cascade defines the shape of AIR_Pipeline + SeamController + PacingController + Normalizer work.

---

<!-- Agent reply-back content (themes + vault inconsistencies) follows; retained as appendix. -->

## Appendix A — Three biggest reshape themes

**Theme 1 — Storage-vs-policy split is pervasive.** The vault's `Truth - Storage Components Do Not Own Policy` drives reshapes in at least six components: `VideoLookaheadBuffer` (four policy domains extract to PacingController); `FrameIndexedVideoStore` (consumption-semantic violation + source-time leak — double-prohibited, deleted); `AudioLookaheadBuffer` (rate migration); `FrameRingBuffer` (live-role-as-class retired in favor of pointer-swap); the `air/` preview buffers are the proven template. This single truth produces the largest single code reduction in vNext.

**Theme 2 — Source-time-to-channel-time translation consolidates at the Normalizer.** Scaling (decoder), cadence (TickProducer), PTS origin (PipelineManager), asset-offset handling (FedBlock), and FIVS cadence-repeat cache — five scattered sites in runtime/ — collapse to one site in `air/` per `INV-NORMALIZER-SOLE-TRANSLATION-POINT-001`. Three bug families (`PTS_DRIFT_DETECTED`, cadence-phase reset at seams, `FIVS_MISS`) are structurally excluded, not patched. AIR_Pipeline simplifies because its input becomes channel-canonical; the `CADENCE_REPEAT` cascade branch disappears entirely.

**Theme 3 — Choreography-driven control becomes directive-driven control.** `LoadPreview`/`SwitchToLive(now + X)`/`frame_count = -1`/`SwitchWatcher`/preview-live state machine/A-B slot mechanism/ProducerPreloader/SeamPreparer — an entire vocabulary of mechanisms existed to orchestrate externally driven switch timing. `INV-AIR-NO-ADHOC-SWITCHING-001` + `INV-AIR-NO-SEGMENT-DRIVEN-EXECUTION-001` + `Truth - Directive-Based Coupling Preferred Over Observation-Based Coupling` retire all of this. Promotion becomes a directive from BootstrapContentGate (at kickoff) or SeamController (at seam); PlaybackDirector is the sole owner; the gRPC surface shrinks by three RPCs.

---

## Appendix B — Vault inconsistencies noticed

Places where vault docs contradict each other or where a truth and an invariant sit in tension:

1. **`PlaybackDirector.md §Target-state kickoff sequencing` vs. `Flow - Tune-In §Step 8 GAP`.** The PlaybackDirector spec picks formulation (a) — pre-activation + gate-signals-readiness — as target state (steps 3–4 of the kickoff-sequencing list). `Flow - Tune-In` gap #2 says both formulations are plausible and neither is specified. Either `Flow - Tune-In` is out of date relative to `PlaybackDirector.md` or `PlaybackDirector.md §Target-state kickoff sequencing` got ahead of the flow doc without reconciling.

2. **`BootstrapContentGate.md §Consumers` naming.** Lists `[[PipelineManager]]` as a consumer — but PipelineManager is a runtime/ implementation class, not a vault-target component. The vault elsewhere uses "`PipelineManager (or its successor)`" (§Produces). The spec inconsistently treats PipelineManager as both a runtime-artifact and a vault-target.

3. **`BufferStore.md §Current-State Conformance` for `AudioLookaheadBuffer`.** Says "archetype-conforming." Lists no migration-required policy. Yet the `VideoLookaheadBuffer` parallel case says the rate migration (to channel-canonical samples) is part of `INV-PREVIEW-CHANNEL-CANONICAL-001`. The audio case silently has the same migration and should say so.

4. **`AIR_Pipeline.md §Migration Notes` vs. `Normalizer.md §Migration Notes`.** Both claim ownership of `INV-PTS-CORRECTION-SINGLE-PATH-001` enforcement post-migration. AIR_Pipeline says "enforcement migrates to Normalizer" (text: "reduces to a no-op"). Normalizer says "`INV-PTS-CORRECTION-SINGLE-PATH-001` (currently registered against AIR_Pipeline) — the 'single path' becomes Normalizer-internal." These agree in spirit but the invariant is still registered against AIR_Pipeline per `AIR_Pipeline.md §Invariants`. The invariant hasn't actually moved in the registry.

5. **`Clock.md §Authority` Python scope vs. AIR C++ cross-cutting.** `Clock.md` begins "`runtime/clock.py` is the current Core implementation" — the whole doc is Core-Python-anchored. But `BootstrapContentGate.md §Boundary With Clock`, `SeamController.md` (via `Clock.md §Boundary With SeamController`), `PacingController.md`, `ReadinessController.md` all read "injected Clock reference" — which is meant to apply to AIR C++ too. `Clock.md` does not reconcile the Python authority description with the AIR C++ obligations those boundary sections imply. `Truth - Time Authority Is Injected` is the bridging truth but `Clock.md` itself reads as Core-only.

6. **`AIR_Observability.md` minimal surface vs. the many references to it.** The doc is 24 lines with one invariant. Virtually every other component spec says "emits observability to AIR_Observability." AIR_Observability as a canonical component is under-specified relative to the weight placed on it. `Flow - Tune-In` gap #5 acknowledges this explicitly.

7. **`AIR_Runtime.md INV-SWITCH-ARMED-RUNTIME-GUARD-001`** references "AwaitPreviewFrame" — a pending-mode state from the preview/live state machine that vault elsewhere retires (`INV-AIR-NO-ADHOC-SWITCHING-001`, `INV-AIR-NO-SEGMENT-DRIVEN-EXECUTION-001`). The invariant lives inside the vault spec that also prohibits the state machine giving rise to it. Either this invariant is a legacy-mode-only constraint (and should say so), or the "AwaitPreviewFrame" pending mode survives into vNext (and the prohibitions above need qualification).

8. **`PacingController.md §Invariants Enforced` vs. `AIR_Boundary.md §Invariants — AIR-internal` list.** PacingController names `INV-PACING-SINGLE-AUTHORITY` "(new, to be registered)." AIR_Boundary's AIR-internal invariants list already includes `INV-PACING-SINGLE-AUTHORITY-001`. Either one side is stale about registration status or the `-001` suffix convention changed mid-draft.
