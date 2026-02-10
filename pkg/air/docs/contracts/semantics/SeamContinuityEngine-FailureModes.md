# Seam Continuity Engine — Failure Modes & Non-Goals

**Classification:** Operator-facing reference
**Parent contract:** SeamContinuityEngine.md (INV-SEAM-001 through INV-SEAM-005)
**Audience:** Anyone debugging a channel that sounds wrong, looks wrong, or died
**Scope:** What this subsystem will not save you from, and why

---

## What the Seam Continuity Engine Actually Does

The seam engine manages decoder transitions. It opens the next decoder early on
a background thread, fills a separate buffer pair, and swaps buffer pointers at
the seam tick so the tick thread never waits on FFmpeg.

It does not make bad content good. It does not make slow I/O fast. It does not
fix problems that exist before or after the transition boundary.

---

## Correctness vs. Quality

The seam engine makes two separate guarantees. Operators must distinguish them
to avoid treating normal quality variance as a system failure.

**Correctness** means the system is functioning as designed:

- The channel stays on-air. Output never stops.
- The tick thread never blocks on decoder lifecycle (INV-SEAM-001).
- When the incoming source is not ready, the system selects fallback within the
  same tick — it does not wait (INV-SEAM-002).
- Fallback duration is tracked and exposed as an observable metric
  (INV-SEAM-005).

A channel emitting pad frames at a seam is **correct**. The overlap mechanism
detected that the incoming source was not ready and selected fallback without
stalling the clock. The contract held.

**Quality** means the overlap mechanism delivered real decoded content at the
seam tick:

- Real video from the incoming source was emitted at the seam tick (not pad).
- Real decoded audio from the incoming source was emitted at the seam tick (not
  silence) (INV-SEAM-003).
- The bounded fallback metric is zero or within the KPI threshold
  (INV-SEAM-005).

A DEGRADED outcome — where the incoming source was ready but audio prime was
short, producing 1–5 ticks of recovery silence — is a quality degradation. It
is not a correctness failure. The system operated exactly as designed: it
delivered what the preparation thread had available and bridged the shortfall
with bounded silence.

**Only these conditions are correctness failures:**

| Invariant | Correctness Failure |
|-----------|-------------------|
| INV-SEAM-001 | The tick thread blocked on decoder work. Inter-frame gap spiked at the seam tick. Late ticks correlated with transitions. |
| INV-SEAM-002 (systematic) | The incoming source consistently fails to achieve readiness on well-formed local assets, indicating the overlap window is structurally undersized or the preparation mechanism is broken. A single missed seam on a corrupt asset is not a correctness failure. |
| INV-SEAM-005 | The fallback metric is absent from Prometheus output, or reads zero despite known fallback events. The system has lost the ability to distinguish continuity from failure. |

INV-SEAM-003 (audio continuity) and INV-SEAM-004 (mechanical equivalence) are
**quality contracts**. Violating them degrades output. It does not mean the
system is broken.

---

## Silence Terminology

This document uses two terms for silence. They have different operational
meaning.

**Pad audio** is intentional, structurally correct silence. It occurs when:

- The asset has no audio track (NG-2).
- The schedule contains a planned PAD segment.
- No incoming source is available at the seam tick (PADDED_GAP).
- Session boot has not yet produced a content frame.

Pad audio is the designed output for these scenarios. It is not injected as
a recovery measure. It is the correct audio for the situation.

**Recovery silence** is injected because real decoded audio was expected but
not available. It occurs when:

- The incoming source was ready but audio prime depth was below the threshold
  (DEGRADED TAKE).
- The audio buffer underflowed during the first ticks after a seam
  (`AUDIO_UNDERFLOW_SILENCE`).
- The audio buffer was not primed despite the asset having an audio track
  (`FENCE_AUDIO_PAD`).

Recovery silence keeps the channel on-air and maintains A/V synchronization.
It is bounded by the KPI threshold (default 5 ticks). It represents a quality
degradation, not a correctness failure.

**Rule of thumb:** If the asset has audio and the system is healthy, any silence
at a seam is recovery silence and warrants investigation. If the asset has no
audio, or no content was available, the silence is pad audio and is expected.

---

## Non-Goals

### NG-1: Session Boot

**The first frame of the first block is not a seam.**

The seam engine governs transitions *between* decode sources. The initial block
load — probe, open, seek, prime, first frame to encoder — is a cold start. It
is synchronous. The output clock does not start until priming completes
(`clock.Start()` is called after block A's prime). There is no outgoing source
to overlap with.

**What the operator sees:** Startup latency between `StartChannel` and first
MPEG-TS bytes. This latency is real. It is not bounded by the seam engine. It
is bounded by how fast the first asset's decoder initializes.

**Governed by:** `INV-BOOT-IMMEDIATE-DECODABLE-OUTPUT`, not `INV-SEAM-*`.

**Why not handled:** Overlap requires a running source to produce frames during
the window. At boot, there is no running source. The only alternative is to
emit pad frames during boot, which trades startup latency for initial black
frames. That tradeoff is a product decision, not a seam engine decision.
Currently: we wait for real content.

---

### NG-2: Assets With No Audio Track

**Pad audio on a no-audio asset is correct output. Do not treat it as an
actionable continuity failure.**

If an asset has no audio track, or the audio track is undecodable, the audio
buffer is marked primed-empty. The tick thread emits pad audio (from
`PadProducer::SilenceTemplate()`). This is not recovery silence — there is no
audio to recover. The asset simply does not contain audio.

**This is not an INV-SEAM-003 violation.** The invariant requires "real decoded
audio from the incoming source's audio track." If the incoming source has no
audio track, there is no audio to decode. Pad audio is the only correct output.

**How this surfaces in metrics:**

- `air_seam_degraded_total` increments. This is expected. The DEGRADED
  classification means "audio prime did not meet the threshold." An asset with
  no audio track will never meet the threshold.
- `air_seam_audio_prime_depth_ms == 0`. This is the distinguishing signal. Zero
  prime depth with no preparation failure (`air_seam_failed_total` unchanged)
  means the preparation thread completed successfully — the asset had nothing
  to prime.

**How to filter these out:** When investigating `air_seam_degraded_total`,
cross-reference with `air_seam_audio_prime_depth_ms`. If prime depth is zero
and `air_seam_failed_total` did not increment at the same seam, the asset has
no audio. This is not actionable at the playout layer.

**Why not handled differently:** Synthesizing audio from video, crossfading
from the outgoing audio, or substituting a tone would be an editorial decision.
AIR does not make editorial decisions.

---

### NG-3: Content Shorter Than the Overlap Window

**A 200ms segment cannot provide 500ms of audio prime.**

If a segment's duration is shorter than `kMinAudioPrimeMs` (500ms), the
preparation thread will prime what it can but will not meet the threshold. The
TAKE will be classified as DEGRADED. Recovery silence will occur at the seam.

**What the operator sees:** `air_seam_degraded_total` incrementing.
`air_seam_audio_prime_depth_min_ms` showing values below 500ms. These correlate
with short segments in the block plan.

**Why not handled:** The seam engine cannot manufacture audio samples that do
not exist in the asset. The fix is upstream: Core should avoid scheduling
segments shorter than the audio prime threshold, or the operator accepts that
sub-500ms segments produce degraded transitions.

**Bounded impact:** The recovery silence is bounded by the segment's duration.
A 200ms segment produces at most ~6 fallback ticks at 30fps. This is at or
slightly above the KPI threshold of 5.

---

### NG-4: Decoder Hangs

**If FFmpeg hangs, the preparation thread hangs. The seam engine does not kill
it.**

The preparation thread's work proceeds through four phases with different
timeout characteristics:

| Phase | Call | Wallclock-bounded? | Bound |
|-------|------|--------------------|-------|
| Container probe | `ProbeAsset()` / `Open()` | **No** | Unbounded. Depends on container structure and I/O. |
| Seek | `SeekPreciseToMs()` | **No** | Unbounded. Depends on index availability and container layout. |
| Video frame 0 decode | `DecodeFrameToBuffer()` inside `PrimeFirstTick()` | **Yes** | 2 seconds (`kMaxPrimeWallclockMs`). |
| Audio accumulation | Decode loop inside `PrimeFirstTick()` | **Yes** | 2 seconds (`kMaxPrimeWallclockMs`), shared with video frame 0. |

If a container has a pathological structure (e.g., oversized moov atom,
circular reference, or malformed index), the probe or seek phase blocks
indefinitely. `PrimeFirstTick` cannot be reached.

**What the operator sees:** `air_seam_missed_total` incrementing.
`air_seam_prep_duration_max_ms` stuck at an implausibly high value, or not
updating (because the preparation never completes and therefore never publishes
a duration). The seam tick arrives, TAKE selects pad. The channel stays live
on pad frames.

**Thread leak behavior:** The hung preparation thread remains alive until
session stop, at which point `Cancel()` sets a flag and `join()` blocks until
the FFmpeg call returns (which may be never for a truly pathological
container). One thread is leaked per hung decoder. The session continues on
pad. Subsequent seams spawn new preparation threads — the SeamController does
not wait for a hung thread before arming the next seam. If multiple assets
in sequence hang, multiple threads accumulate. Session stop (`StopChannel`)
will block on joining all of them.

This is an acceptable tradeoff. The leaked threads consume minimal resources
(blocked in a kernel I/O wait, not spinning). The channel remains live. The
operator is notified via `air_seam_missed_total`.

**Why not bounded further:** Adding a wallclock timeout to `Open()` or
`SeekPreciseToMs()` requires either running FFmpeg in a subprocess, using
`pthread_cancel` (undefined behavior with C++ destructors), or wrapping every
FFmpeg call in a future-with-timeout. None of these are justified for a failure
mode caused by malformed containers that should be rejected at ingest.

**Operator action:** Investigate the asset identified in the `PREROLL_ARMED`
log preceding the miss. Re-probe it offline. If it hangs `ffprobe`, reject it
from the library.

---

### NG-5: System Resource Exhaustion

**The seam engine assumes the OS will provide threads, memory, and CPU.**

During the FILLING phase, three threads run simultaneously: tick thread,
outgoing fill thread, incoming fill thread. The preparation thread may overlap
briefly. Each fill thread holds a `VideoLookaheadBuffer` (~15 frames x ~1.2MB
at 720p = ~18MB) plus an `AudioLookaheadBuffer` (~1000ms x 48kHz x 2ch x 2B =
~192KB). Peak memory during overlap: ~40MB for two buffer sets plus two live
FFmpeg decoder contexts.

If the system is under memory pressure, `std::vector::resize()` inside the
decoder throws `std::bad_alloc`. This terminates the process.

If CPU is saturated, the fill thread falls behind, the video buffer drains, and
the tick thread pops from an empty buffer. If the buffer was previously primed,
this is a hard fault (`INV-VIDEO-LOOKAHEAD-001: UNDERFLOW`) and the session
terminates.

**Why not handled:** Graceful degradation under resource exhaustion requires an
entirely different architecture (adaptive quality, frame dropping, decode skip).
The seam engine is designed for a dedicated playout machine where resources are
provisioned. If you are running out of memory, you have a capacity problem, not
a seam problem.

---

### NG-6: Downstream Consumer Failures

**The seam engine does not compensate for slow readers.**

If the MPEG-TS consumer (Core's HTTP handler, the viewer's player) cannot
consume bytes fast enough, the `SocketSink` buffer fills. The AVIO write
callback blocks (up to 500ms). If the drain timeout expires, the sink detaches
and the session stops.

This is unrelated to seam continuity. The seam engine's output is correct. The
problem is downstream of the encoder.

**What the operator sees:** `air_continuous_detach_count > 0`, session
terminated with reason `"stopped"` and `SocketSink detach` in logs.

---

### NG-7: Clock Skew Between Core and AIR

Block fence ticks are computed from `block.end_utc_ms - session_epoch_utc_ms`.
If Core's system clock and AIR's system clock diverge (NTP skew, VM clock
drift), fence ticks will be wrong. Content will be cut short or run long.

**Why not handled:** Clock synchronization is an infrastructure concern. AIR
trusts the timestamps Core provides.

**Operator action:** Ensure NTP is configured. Check `INV-BLOCK-WALLFENCE-001:
FENCE` logs — `delta_ms` shows the gap between scheduled and actual fence time.
Consistent positive or negative deltas indicate clock skew.

---

### NG-8: Discontinuous or Malformed Audio Timelines

**The seam engine delivers audio samples as the decoder provides them. It does
not validate, correct, or rewrite audio timelines.**

The following audio anomalies are outside the seam engine's scope:

- **Discontinuous audio PTS.** If an asset's audio packets have gaps or
  backwards jumps in their presentation timestamps, the decoded samples will
  reflect those discontinuities. The seam engine pushes whatever the decoder
  outputs into the `AudioLookaheadBuffer`. The encoder receives samples in
  buffer order, not in PTS order.

- **Mid-asset sample rate or channel layout changes.** If an asset changes from
  48kHz stereo to 44.1kHz mono mid-stream, the decoder may produce samples at
  the wrong rate for the house format. The `AudioLookaheadBuffer` accepts them
  without validation. The encoder will process them, potentially producing
  audible artifacts (pitch shift, channel collapse).

- **Encoder priming delay.** The session encoder (`EncoderPipeline`) may
  introduce its own audio priming latency at session start. This is an encoder
  characteristic, not a seam characteristic. It affects the first few frames
  of a session, not seam transitions.

**How these surface in metrics:** Audio timeline anomalies do not produce seam
metrics. They are invisible to `air_seam_*` counters because the seam engine
successfully delivered the audio — the audio itself was malformed. Symptoms
appear in encoder-level metrics or viewer-reported quality complaints. If
`air_seam_audio_fallback_ticks_max == 0` and the viewer hears glitches,
the problem is content quality, not seam continuity.

**Operator action:** Validate assets at ingest. Use `ffprobe -show_entries
stream=sample_rate,channels,codec_name` to verify audio stream consistency.
Assets with mid-stream format changes should be re-encoded to a uniform format
before scheduling.

---

## When Silence Is Acceptable

### Acceptable Silence

| Scenario | Silence Type | Typical Duration | Why Acceptable |
|----------|-------------|------------------|----------------|
| Asset has no audio track | Pad audio | Entire segment | There is no audio to decode. Pad audio is the only correct output. |
| Degraded TAKE, audio prime short | Recovery silence | 1–5 ticks (33–166ms) | Bounded by KPI. Below perceptual threshold for most viewers. |
| PADDED_GAP: no incoming source available | Pad audio | Entire gap | No content exists in the queue. Pad audio preserves channel liveness. |
| Content-to-PAD segment transition | Pad audio | Planned PAD duration | This is editorial intent. The schedule says "pad here." |
| Corrupt audio stream in otherwise valid asset | Recovery silence | Unbounded within segment | Best-effort on broken content. Not a seam issue — the seam delivered what the asset contained. |
| Session boot, before clock starts | No output at all | 50–500ms | Pre-clock. Not audible. Not a seam. |

### Unacceptable Silence

| Scenario | Classification | Metric Fingerprint |
|----------|---------------|--------------------|
| Well-formed local asset, healthy system, recovery silence at segment seam | Code defect in prime logic | `degraded_total++`, `prep_duration_ms` well within window, `overlap_headroom_min_ms > 200` |
| Recovery silence at every block seam despite adequate overlap | Structural plumbing issue — audio buffer not connected after preparation | `missed_total == 0`, `degraded_total == seam_total` |
| Growing `silence_injected_total` between seam boundaries | Mid-segment audio underflow, unrelated to seam transitions | Not a seam issue. Investigate fill thread decode rate and audio buffer depth. |
| Pad audio on a no-audio asset logged as a seam failure | Classification defect — no-audio exemption not applied | `failed_total++` with `audio_prime_depth == 0` and no preparation error |

---

## When Channel Termination Is Allowed

The seam engine does not terminate the channel. `PipelineManager` does.
Termination falls into three categories.

### Lifecycle-Driven Shutdowns

These are normal. The channel was told to stop.

| Trigger | Condition | Recovery Path |
|---------|-----------|---------------|
| `stop_requested` | Core sends `StopChannel` | Normal lifecycle. Channel restarts when a viewer tunes in. |
| Last viewer leaves | Core detects 0 viewers, sends `StopChannel` | Same as above. |

### Downstream Sink Failures

These are infrastructure problems. The seam engine's output was correct; the
bytes could not be delivered.

| Trigger | Condition | Recovery Path |
|---------|-----------|---------------|
| Socket sink detach | Consumer too slow, 500ms drain timeout expired. `SocketSink detach` logged. | Viewer reconnects. Core re-spawns AIR. |
| AVIO write returns `EPIPE` | Sink closed or detached during encoder flush. | Session restarts. |
| `dup(fd)` / `fcntl()` failure | OS file descriptor error at session boot. | Session restarts. |

### Fatal Continuity Violations

These are hard faults. Something broke inside the playout pipeline.

| Trigger | Condition | Recovery Path |
|---------|-----------|---------------|
| Video buffer underflow (post-prime) | `IsPrimed() == true`, `TryPopFrame()` returns false. Fill thread is too slow or died. | Session restarts via Core. |
| Encoder failure | `encodeFrame()` returns error. | Session restarts. |
| `std::bad_alloc` | Memory exhaustion during buffer allocation. Process-fatal. | Process restarts. |

**Seam transitions do not appear in any of these tables.** A seam transition
that cannot achieve readiness produces pad frames. Pad frames are valid encoder
input. The channel stays live.

A seam transition can indirectly contribute to termination in a multi-fault
scenario: if the outgoing fill thread crashes (FFmpeg segfault) AND the video
buffer drains before the incoming source's fill thread produces enough frames,
the tick thread hits the underflow hard-fault path. The buffer depth at crash
time (~500ms at 15 frames) determines the window before termination. This
requires two independent failures — fill thread crash plus insufficient incoming
buffer depth — and is not a seam engine defect.

---

## Pathological Cases Intentionally Not Handled

### P-1: Asset That Probes Successfully but Fails on First Decode

The preparation thread calls `AssignBlock()` (probe succeeds, decoder opens,
seek succeeds) then `PrimeFirstTick()` where `DecodeFrameToBuffer()` returns
false on the first call. The producer enters `kReady` state with no primed
frame and `decoder_ok_ = false`.

**What happens:** `StartFilling()` finds no primed frame. The fill thread
starts but immediately gets nullopt from `TryGetFrame()` and exits. At the seam
tick, B's video buffer is empty. TAKE selects pad.

**Metric signal:** `air_seam_missed_total++`, `air_seam_prep_duration_ms` is
normal (preparation completed without hanging — it produced a non-decodable
result).

**Why not handled specially:** The probe/open/seek succeeded — from the
decoder's perspective, the asset looked valid. The failure occurred at decode
time. The seam engine cannot predict this. It treats it the same as any
readiness miss.

**Operator action:** Check the asset. It is probably truncated (container
headers intact, media data missing or corrupt).

---

### P-2: Cascade Failure — Every Asset in the Queue Is Broken

If every block in the queue has unresolvable or corrupt assets, every
preparation fails. The channel runs on pad frames indefinitely.

**Metric signal:** `air_seam_failed_total == air_seam_total`. This is
unmistakable.

**Why not handled:** The seam engine's contract is "deliver what the content
provides." If the content provides nothing, the output is pad audio and pad
video. The system is operating correctly — the content pipeline is broken.

**Operator action:** `failed_total == seam_total` means every transition
failed. Check the block queue. Verify assets exist on disk. Check importer
logs.

---

### P-3: Two Seams Closer Together Than the Overlap Window

If segment N is 300ms and the overlap window is 500ms, the preparation for
segment N+1 cannot complete before the N->N+1 seam tick. The overlap window for
that transition is at most 300ms — less than the audio prime target.

**What happens:** DEGRADED outcome. Audio prime is partial. Recovery silence at
the transition.

**Why not handled:** The seam engine cannot create time. If segments are shorter
than the overlap window, overlap is necessarily incomplete. The system degrades
gracefully (bounded fallback) rather than failing.

**Operator action:** If `air_seam_degraded_total` correlates with short
segments, the schedule has segments below minimum viable duration. Recommended
minimum: 2x `kMinAudioPrimeMs` (1000ms) to allow probe + open + seek + full
audio prime within the preceding segment's lifetime.

---

### P-4: Segment Seam Tick Computed From Media Time — Decode Rate Variance

Segment seam ticks are computed from `boundary.end_ct_ms` at block-load time
using rational arithmetic. The actual content consumption rate depends on the
fill thread's decode speed. If the fill thread decodes faster or slower than
expected (CPU throttling, I/O contention), the outgoing segment may exhaust
before or after the computed seam tick.

**If content exhausts early:** The fill thread exits. The video buffer has
remaining frames. The tick thread pops them until the seam tick, then swaps to
B's buffers. If the buffer drains before the seam tick — unlikely with 15-frame
target depth and segments longer than 500ms — the tick thread gets underflow.

**If content exhausts late:** The seam tick arrives while A still has frames in
its buffer. The swap fires. A's remaining buffered frames are discarded during
rotation. This is correct — the seam tick is authoritative. A few frames of
content are lost (typically 1–3 frames, 33–100ms). Not visible to the viewer.

**Why not handled more precisely:** Computing exact frame-accurate segment seam
ticks requires knowing the exact decode timestamp of every frame in advance,
which requires decoding the entire segment first. The rational-arithmetic
estimate is accurate to +/-1 frame for well-formed content. The buffer absorbs
the variance.

---

### P-5: Preparation Thread Completes but Fill Thread Never Starts

Between ARMED and FILLING, the tick thread must create B's buffer pair and call
`StartFilling()`. This happens in the pre-TAKE readiness block on every tick.
If a code defect causes the tick thread to skip this block (early `continue`,
exception, logic error), the SeamOverlapSlot stays in ARMED state. At the seam
tick, B's buffers are empty.

**Why not handled:** The seam state machine assumes its transitions are driven
correctly. If the driver (PipelineManager) skips a step, the state machine
cannot self-heal.

**Metric fingerprint:** `air_seam_missed_total++` with
`air_seam_overlap_headroom_min_ms > 0`. Preparation completed with adequate
headroom, but the miss still happened. This combination — time available, still
missed — is the fingerprint of a code defect in the driver. It does not occur
in any content or environment failure scenario.

---

### P-6: Fill Thread Crash (FFmpeg Segfault)

If FFmpeg segfaults inside the fill thread (corrupt frame data, codec library
fault, misaligned memory), the fill thread dies. Its `VideoLookaheadBuffer`
stops receiving pushes. The tick thread continues popping. The buffer drains in
~500ms (15 frames at 30fps).

If the buffer drains while `IsPrimed() == true`, the underflow hard-fault fires
and the session terminates.

**Why not handled:** FFmpeg segfaults are not catchable in-process (SIGSEGV).
The only mitigation would be running decoders in separate processes, which is a
different architecture. The 500ms buffer depth is the implicit fault tolerance
budget. It is not sufficient for automatic recovery.

**Operator action:** Check for FFmpeg crash logs. Update FFmpeg. If the crash is
reproducible with a specific asset, remove the asset from the library and file
an upstream codec report.

---

## Failure Mode Summary

| Mode | Expected Frequency | Viewer Impact | Seam Engine Response | Silence Type | Operator Metric Signal |
|------|-------------------|---------------|---------------------|-------------|----------------------|
| Corrupt asset | Occasional | One pad gap | Pad at seam, continue | Pad audio | `failed_total++` |
| No-audio asset | Per-asset | Silence (correct) | Pad audio, not a failure | Pad audio | `degraded_total++`, `prime_depth == 0` |
| Short segment (<500ms) | Per-schedule | Brief audio gap | Partial prime, bounded fallback | Recovery silence | `degraded_total++`, `prime_depth < 500` |
| Slow probe (large moov) | Occasional | None if absorbed | Absorbed by overlap window | None | `absorbed_total++`, `headroom_min` drops |
| Decoder hang | Rare | Pad for block | Miss, thread leaked until stop | Pad audio | `missed_total++`, `prep_duration` stuck |
| All assets broken | Catastrophic | Indefinite black+silence | All seams fail, channel lives on pad | Pad audio | `failed_total == seam_total` |
| CPU saturation | Environmental | Session death | Cannot compensate | N/A | Session terminates |
| Memory exhaustion | Environmental | Process death | Cannot compensate | N/A | Process crash |
| Clock skew | Infrastructure | Content cut short/long | Wrong fence ticks | N/A | `FENCE delta_ms` consistently non-zero |
| Segments < overlap window | Schedule-dependent | Brief audio gap | Degraded, bounded | Recovery silence | `degraded_total++` on short segments |
| Fill thread crash | Rare | Session death in ~500ms | Buffer bridges gap, then hard fault | N/A | Session terminates |
| Driver defect (ARMED->FILLING skip) | Code defect | Missed seam despite headroom | Miss | Pad audio | `missed_total++` with `headroom > 0` |
| Malformed audio timeline | Per-asset | Audible artifacts | Delivers samples as decoded | N/A | No seam metrics; viewer-reported |
