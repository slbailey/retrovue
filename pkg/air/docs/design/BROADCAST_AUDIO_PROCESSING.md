# Design: Broadcast Audio Dynamic Range Processing

**Status:** IMPLEMENTED — v0.1 DRC live, v0.2 retro TV tuning in progress
**Scope:** AIR PipelineManager audio path (post-normalization, pre-encode) and FFmpegDecoder downmix
**Date:** 2026-03-12
**Revised:** 2026-03-12 (v0.2: retro TV tuning — center channel boost, tighter DRC for theatrical content)

---

## 1. Problem Statement

Theatrical film mixes (e.g., Ghostbusters 1984) produce quiet, difficult-to-hear
dialogue when played through the RetroVue playout pipeline. The content is
loudness-normalized per INV-LOUDNESS-NORMALIZED-001, yet the subjective listening
experience remains wrong: dialogue is buried, transients are harsh, and the result
does not resemble television broadcast audio.

The issue is systemic. Any source with a wide loudness range — theatrical 5.1
downmixes, concert recordings, unmastered archival content — exhibits the same
symptom. The problem is not per-asset; it is an absent processing stage.

## 2. Why Normalization Alone Is Insufficient

INV-LOUDNESS-NORMALIZED-001 applies a constant gain scalar computed from the
difference between the asset's measured integrated LUFS and the broadcast target
(-24 LUFS ATSC A/85). This corrects the long-term average loudness. It does not
alter the internal dynamics of the program material.

Integrated LUFS is a statistical summary of the entire file. A theatrical mix
with an integrated loudness of -31 LUFS and a loudness range (LRA) of 25 LU
contains dialogue passages near -40 LUFS and peak transients near -15 LUFS.
After +7 dB normalization, the average reaches -24 LUFS, but dialogue sits
near -33 LUFS (inaudible on consumer equipment) while transients approach
0 dBFS (clipping threshold).

Constant-gain normalization shifts the entire dynamic envelope uniformly. It
cannot narrow the envelope. Narrowing the dynamic envelope — bringing quiet
passages up and loud passages down relative to the average — requires
time-varying gain: dynamic range compression.

Every real broadcast playout chain includes dynamic range processing after
loudness alignment. ATSC A/85 acknowledges this explicitly: normalization
ensures the correct average; downstream processing ensures moment-to-moment
listenability. RetroVue's pipeline has the first stage but lacks the second.

## 3. Boundary Between Core and AIR

The existing authority model for loudness (INV-LOUDNESS-NORMALIZED-001) defines
a clean boundary:

- **Core** owns measurement truth. Core measures integrated LUFS at ingest,
  computes `gain_db`, persists it to asset metadata, and propagates it on
  every playout segment.
- **AIR** owns gain application. AIR applies the constant scalar to S16
  samples during real-time playout.

Dynamic range compression extends this model without violating it:

- **Core** continues to own all editorial loudness metadata. In future
  iterations, Core may additionally measure and propagate LRA (loudness
  range) per asset. Core never applies signal processing.
- **AIR** owns all sample-path signal processing. The new dynamic range
  processor is a real-time, sample-level operation that belongs exclusively
  to AIR. AIR applies it after the existing constant-gain normalization
  stage, using its own internal parameters. AIR does not require any new
  metadata from Core for the initial implementation.

No new cross-boundary contract is required for v0.1. The processor operates
entirely within AIR on already-normalized S16 audio.

## 4. Proposed Runtime Pipeline Position

Current audio path in the PipelineManager tick loop:

```
AudioLookaheadBuffer::TryPopSamples
  → ApplyGainS16 (INV-LOUDNESS-NORMALIZED-001)
  → EncoderPipeline::encodeAudioFrame
```

Proposed audio path:

```
AudioLookaheadBuffer::TryPopSamples
  → ApplyGainS16 (INV-LOUDNESS-NORMALIZED-001)
  → BroadcastAudioProcessor::Process (NEW)
  → EncoderPipeline::encodeAudioFrame
```

The processor sits between normalization and encoding. This position is
mandatory for correctness:

- It receives audio at the house format (S16 stereo interleaved, 48 kHz)
  after normalization has aligned the integrated loudness to -24 LUFS.
- It outputs audio at the same house format with reduced dynamic range.
- The encoder receives broadcast-ready audio with no format change.

## 5. BroadcastAudioProcessor Responsibilities

The BroadcastAudioProcessor is a stateful, per-session audio processing unit
that reduces dynamic range of normalized audio to broadcast-appropriate levels.

Responsibilities:

- Accept S16 stereo interleaved samples at 48 kHz (house format).
- Detect instantaneous signal level via per-sample peak measurement using
  linked stereo detection: the absolute value of each channel is computed
  per sample, and the higher of the two determines the input level for
  the envelope follower. Gain reduction derived from the linked level is
  applied equally to both channels. This preserves the stereo image
  unconditionally.
- Compute time-varying gain reduction when the detected level exceeds a
  configured threshold, governed by a compression ratio.
- Apply attack and release envelope smoothing to the gain reduction to
  prevent audible artifacts (pumping, breathing).
- Apply a fixed makeup gain to compensate for average level reduction
  caused by compression.
- Clamp output samples to int16 range with no wraparound.
- Emit S16 stereo interleaved samples at 48 kHz. Sample count and timing
  are unchanged.

The processor does NOT:

- Alter sample count, frame timing, PTS, or channel count.
- Make decisions based on editorial metadata, segment identity, or schedule
  state.
- Communicate with Core or any component outside the PipelineManager tick
  loop.
- Replace or modify the existing constant-gain normalization stage.
- Compute independent gain reduction per channel. Stereo linking is
  mandatory, not optional.

## 6. Processing Order and Why Order Matters

The processing chain is strictly ordered: normalization first, then compression.

**Why this order is correct:**

Normalization aligns all source material to a common integrated loudness
(-24 LUFS). After normalization, the compressor operates on audio that is
centered at a known, consistent level regardless of the original source
loudness. This means a single set of compressor parameters (threshold, ratio,
attack, release, makeup gain) produces correct results for all content.

This relationship also determines the correct threshold. Because normalization
centers dialogue near -24 LUFS, the compressor threshold is set above that
level (nominally -18 dBFS) so that normal dialogue passes through unaffected.
Only transients and loud passages that exceed the threshold are compressed.
A threshold at or below the dialogue norm would compress speech continuously,
producing an unnatural, over-processed sound.

**Why the reverse order is incorrect:**

If compression were applied before normalization, the compressor would operate
on audio at wildly varying absolute levels (-18 LUFS for one asset, -35 LUFS
for another). A fixed threshold would over-compress loud sources and
under-compress quiet ones. The compressor parameters would need to be
per-asset, defeating the purpose of a universal broadcast processing stage.

**Why the two stages must remain separate:**

Normalization is a stateless, per-sample scalar. Compression is a stateful,
envelope-following process. Combining them into a single stage would couple
Core's editorial metadata (gain_db) to AIR's real-time signal processing
state, violating the authority boundary defined in
INV-LOUDNESS-NORMALIZED-001.

## 7. State and Segment-Boundary Behavior

The BroadcastAudioProcessor carries internal state: the current envelope level
(smoothed RMS), which determines the instantaneous gain reduction. This state
evolves continuously across ticks within a segment.

**Segment boundaries:** On segment transition, the processor resets its
envelope state to unity (no gain reduction). This prevents the envelope from
one segment's audio characteristics (e.g., a loud explosion at the end of a
movie segment) from affecting the gain applied to the opening samples of the
next segment (e.g., a quiet interstitial). Each segment begins with the
compressor in a neutral state.

**Segment-boundary ramp:** The reset to unity is not an instantaneous step.
After reset, the envelope transitions from unity toward the level indicated
by the incoming audio over the attack window duration. This is a natural
consequence of the attack smoothing: when the envelope is at unity and the
incoming signal exceeds the threshold, the gain reduction ramps in over the
attack time rather than snapping to full compression. No additional smoothing
mechanism is required beyond the existing attack envelope. The attack window
itself provides the ramp. This eliminates the possibility of a gain
discontinuity at segment boundaries — the compressor always produces a
smooth gain trajectory from its reset state.

**Session boundaries:** The processor is constructed at session start and
destroyed at session end. No state carries across playout sessions.

**Block boundaries within a session:** Segment-boundary reset applies. Block
transitions are a superset of segment transitions; no special handling is
needed.

**Silence and padding segments:** The processor applies to all audio passing
through the tick loop, including silence/padding. For zero-valued samples,
the detected level is zero, the compressor applies no gain reduction, and
the output is identical to the input. No bypass logic is required.

## 8. Configuration Model

### v0.1 — Compiled Constants

The initial implementation uses fixed, broadcast-standard parameters compiled
into AIR. No runtime configuration, no per-segment metadata, no gRPC fields.

Target parameters (subject to empirical tuning during implementation):

| Parameter | Nominal Value | Rationale |
|-----------|---------------|-----------|
| Threshold | -18 dBFS | Above normalized dialogue level (~-24 LUFS); compresses transients and loud passages while leaving normal speech unaffected |
| Ratio | 3:1 | Moderate broadcast compression; preserves some dynamics |
| Attack | 5 ms | Fast enough to catch transients before they pass |
| Release | 100 ms | Slow enough to avoid pumping on speech cadences |
| Makeup gain | +3 dB | Compensates for average gain reduction |
| Detection | Per-sample peak | Instantaneous `max(abs(L), abs(R))` per sample; no windowed averaging needed |
| Stereo linking | Linked (max) | Gain reduction from louder channel applied to both; preserves stereo image |

**Threshold rationale:** Normalization (INV-LOUDNESS-NORMALIZED-001) centers
integrated loudness at -24 LUFS. Dialogue in normalized content typically
sits within a few dB of this target. Setting the compressor threshold at
-18 dBFS — approximately 6 dB above the dialogue norm — ensures that normal
speech does not trigger compression. Only content that exceeds the threshold
(explosions, music stings, loud effects) is gain-reduced. This produces the
characteristic broadcast sound: dialogue remains natural and present while
peaks are controlled.

A threshold at -24 dBFS (the normalization target) would engage the
compressor during ordinary dialogue, producing continuous gain reduction and
an audibly over-processed result. The 6 dB headroom between dialogue norm
and threshold is consistent with standard broadcast processing practice.

These values represent a conservative starting point derived from standard
broadcast audio processing practice. The exact values will be validated
empirically against theatrical mixes during implementation.

### Future — Per-Asset Metadata (v0.2+)

Core already runs ffmpeg ebur128 at ingest. The ebur128 filter also reports
LRA (loudness range). A future iteration may:

1. Extend the loudness enricher in Core to capture and persist LRA alongside
   integrated LUFS.
2. Propagate LRA on the playout segment (new field on BlockPlanSegment).
3. AIR uses LRA to gate the processor: assets with LRA below a broadcast
   threshold (e.g., 15 LU) bypass compression entirely, as they are already
   dynamically appropriate.

This evolution requires a proto/schema change and is explicitly out of scope
for v0.1.

### Future — Operator-Tunable Parameters (v0.3+)

If per-channel audio character proves desirable (e.g., a movie channel with
heavier compression than a sitcom channel), parameters could be propagated
from Core's channel configuration through the BlockPlan. This is speculative
and not planned.

## 9. Non-Goals

- **Multiband compression.** A single-band compressor is sufficient for
  broadcast-style dynamic range control. Multiband processing adds complexity
  without proportional benefit for the television simulation use case.
- **Brickwall limiter in v0.1.** The existing S16 clamp in ApplyGainS16 and
  the proposed processor's output clamp handle basic peak protection. A
  dedicated brickwall limiter stage — which would catch short-duration
  overshoot that escapes the compressor's attack window — is not included
  in v0.1. A limiter may be added as a separate processing stage after the
  compressor in v0.2+ if empirical testing reveals overshoot artifacts that
  the compressor alone does not adequately control.
- **Look-ahead compression.** Real broadcast compressors sometimes use
  look-ahead for transparent transient handling. This adds latency and
  buffering complexity. The fast attack time is sufficient for v0.1.
- **Per-channel or per-asset compressor tuning in v0.1.** All content
  receives identical processing. Per-asset adaptation is a future concern.
- **Modification of the house audio format.** The processor operates on and
  emits S16 stereo interleaved at 48 kHz. No format change is introduced.
- **Core-side dynamic range processing.** Signal processing belongs to AIR.
  Core will never apply compression.
- **Independent per-channel compression.** The processor uses linked stereo
  detection exclusively. Independent L/R gain reduction is not supported
  and will not be added.

## 10. Risks and Tradeoffs

**Risk: Over-compression of already-compressed material.**
Some source content (TV series, commercials) may already have broadcast-level
dynamic range. Applying additional compression narrows dynamics further,
producing a flat, lifeless sound. Mitigation: the -18 dBFS threshold sits
well above the normalized dialogue level, so content that is already
dynamically constrained rarely exceeds the threshold and receives minimal
gain reduction. The LRA-gated bypass in v0.2 eliminates this risk entirely.

**Risk: Audible artifacts at segment boundaries.**
Resetting envelope state on segment transition means the compressor starts
each segment at unity. If a segment begins with a loud transient, the
compressor ramps gain reduction in over the attack window (~5 ms) rather
than applying it instantaneously. This brief ramp is a natural property of
the attack envelope and matches real broadcast behavior — compressors do not
have foreknowledge of upcoming content. The attack time is short enough that
the transient overshoot is inaudible in practice. If overshoot proves
problematic, the brickwall limiter planned for v0.2+ would address it as
a separate stage.

**Risk: Increased CPU load per tick.**
The processor performs an RMS calculation and gain application on ~1600 samples
per tick (33 ms at 48 kHz stereo). This is approximately 3200 multiply-add
operations — sub-microsecond on modern hardware. The overhead is negligible
relative to the existing video encode path.

**Risk: Makeup gain causing clipping.**
The +3 dB makeup gain raises the overall level after compression. In rare
cases where compression reduces peaks minimally but makeup gain pushes the
full signal upward, individual samples could reach the S16 ceiling. The
output clamp (int16 range, no wraparound) handles this identically to the
existing ApplyGainS16 clamping behavior. If clipping proves frequent, the
v0.2+ limiter would provide a more graceful ceiling.

**Tradeoff: Fixed parameters vs. per-content adaptation.**
v0.1 uses one parameter set for all content. This is a deliberate tradeoff:
simplicity and predictability over optimality. Theatrical mixes will sound
significantly better; broadcast-ready content will sound marginally flatter.
The tradeoff resolves naturally when LRA-gated bypass arrives in v0.2.

**Tradeoff: No look-ahead.**
Without look-ahead, the first few milliseconds of a sudden transient pass
through unreduced. With look-ahead, the transient would be caught but the
pipeline gains latency and buffering complexity. For a television simulation
where millisecond-level transient transparency is not critical, the zero-
latency approach is preferable.

## 11. Open Questions

1. **Exact parameter tuning.** The nominal values in Section 8 are derived
   from broadcast convention. Empirical testing against the actual content
   library (theatrical films, TV series, interstitials) will determine
   final values. Should a formal A/B listening test be conducted, or is
   subjective evaluation by the operator sufficient?

2. **Telemetry.** Should the processor emit per-tick or per-segment metrics
   (e.g., peak gain reduction, average gain reduction, time spent in
   compression)? This would aid tuning and incident analysis but adds
   log volume. If yes, what invariant ID and log format?

3. **Interaction with existing BLOCK_FRAME_AUDIT.** The frame audit in
   TickProducer checks segment and block duration integrity. The audio
   processor does not alter frame count or timing, so no interaction is
   expected. Should a contract test explicitly verify this non-interaction?

## 12. Proposed Invariants

The following invariants are proposed for creation during implementation.
They are drafted here in summary form; canonical documents will be created
in `docs/contracts/invariants/` per the contracts CLAUDE.md workflow.

---

### INV-BROADCAST-DRC-001

**Behavioral Guarantee:** A broadcast dynamic range processing stage MUST
exist in the AIR audio pipeline between loudness normalization
(INV-LOUDNESS-NORMALIZED-001) and audio encoding. All playout audio MUST
pass through this stage.

The processing stage MAY apply no gain change to a given frame if bypass
policy determines that compression is unnecessary (e.g., LRA-gated bypass
in future versions). The architectural guarantee is the presence and
positioning of the stage, not that every sample is gain-modified.

**Boundary:** The stage receives and emits S16 stereo interleaved samples
at 48 kHz within AIR's PipelineManager tick loop. It is positioned after
ApplyGainS16 and before encodeAudioFrame.

**Violation:** Audio reaches the encoder without having passed through the
broadcast audio processing stage.

**Derives From:** INV-LOUDNESS-NORMALIZED-001 (extends the loudness chain
with dynamic processing).

---

### INV-BROADCAST-DRC-002

**Behavioral Guarantee:** The broadcast audio processor MUST NOT alter
sample count, channel count, sample rate, frame timing, or PTS of any
audio frame.

**Boundary:** Input and output of BroadcastAudioProcessor::Process are
identical in all metadata; only sample amplitude values may differ.

**Violation:** Any audio frame exiting the processor with different
sample count, channel count, or timing than it entered.

**Derives From:** INV-AUDIO-HOUSE-FORMAT-001,
INV-AUDIO-CONTINUITY-NO-DROP.

---

### INV-BROADCAST-DRC-003

**Behavioral Guarantee:** The broadcast audio processor MUST reset its
internal envelope state to unity (no gain reduction) on every segment
boundary. After reset, the envelope MUST transition smoothly from unity
toward the level indicated by the incoming audio via the attack envelope —
no instantaneous gain discontinuity is permitted at segment boundaries.

**Boundary:** Segment transitions within a block and block transitions
within a session both trigger reset. No compressor state carries from
one segment to the next.

**Violation:** Gain reduction computed from a prior segment's audio
characteristics is applied to a subsequent segment's samples. Or: a
measurable gain discontinuity (step change) occurs at a segment boundary.

---

### INV-BROADCAST-DRC-004

**Behavioral Guarantee:** The broadcast audio processor MUST use linked
stereo level detection. Gain reduction is computed from the louder of the
two channels and applied equally to both channels.

**Boundary:** At no point in the processing chain are left and right
channels subject to different gain reduction values.

**Violation:** Left and right channels within a single audio frame receive
different gain reduction, causing stereo image shift.

**Derives From:** INV-AUDIO-HOUSE-FORMAT-001 (stereo interleaved contract).

---

---

## 13. v0.2 — Retro TV Audio Tuning

### 13.1 Motivation

RetroVue simulates retro linear television. Theatrical content (5.1 surround,
wide dynamic range) must sound like it's being watched on a TV in the 1980s or
1990s — not in a cinema. Two processing changes are required:

1. **Center channel dialogue boost during 5.1→stereo downmix.** The center
   channel carries dialogue. ffmpeg's default ITU downmix coefficient for
   center is 0.707 (-3 dB). For retro TV, dialogue should be more prominent.
   Boosting the center mix level to 1.0 (0 dB) increases dialogue presence
   by 3 dB relative to the L/R surround field.

2. **Tighter DRC parameters for theatrical content.** The v0.1 parameters
   (-18 dBFS threshold, 3:1 ratio, 3 dB makeup) are conservative. Retro
   broadcast stations used aggressive transmission processors. The v0.2
   tuning lowers the threshold and increases the ratio to produce the
   characteristic "TV sound" — dialogue and action at similar levels.

### 13.2 Center Channel Downmix Boost (INV-DOWNMIX-CENTER-BOOST-001)

The FFmpegDecoder already uses libswresample (`swr_alloc_set_opts2`) to convert
surround audio to stereo. By default, ffmpeg uses ITU-R BS.775-1 coefficients:

```
L_out = 1.0*L + 0.707*C + 0.707*Ls
R_out = 1.0*R + 0.707*C + 0.707*Rs
```

The center channel coefficient (0.707 / -3 dB) is appropriate for cinema
reproduction but too quiet for television. Setting `center_mix_level` to 1.0
(0 dB) via `av_opt_set_double` on the SwrContext before `swr_init` changes
the downmix to:

```
L_out = 1.0*L + 1.0*C + 0.707*Ls
R_out = 1.0*R + 1.0*C + 0.707*Rs
```

This is a single option on the existing resampler — zero additional CPU cost,
no new filter graph, no format change. Stereo and mono sources are unaffected
(the coefficient only applies when the source has a center channel).

The surround mix level remains at the ITU default (0.707). Surround effects
(ambient room tone, rear-channel explosions) are already well-handled by the
DRC stage downstream.

### 13.3 DRC Parameter Tuning (v0.2)

v0.2 tightens the compressor to match the retro TV aesthetic:

| Parameter | v0.1 | v0.2 | Rationale |
|-----------|------|------|-----------|
| Threshold | -18 dBFS | -20 dBFS | Engages 2 dB earlier; catches more theatrical dynamic swings |
| Ratio | 3:1 | 4:1 | Harder compression; closer to broadcast transmission processor behavior |
| Attack | 5 ms | 3 ms | Faster transient catch; less overshoot on explosions |
| Release | 100 ms | 80 ms | Tighter recovery; dialogue comes back faster after action peaks |
| Makeup gain | +3 dB | +4 dB | Compensates for increased gain reduction at higher ratio |

These values target the "TV sound" — audibly compressed but not distorted.
Dialogue and action scenes at similar perceived loudness. The fast attack
and moderate release prevent pumping on speech cadences while controlling
theatrical transients.

### 13.4 Proposed Invariant: INV-DOWNMIX-CENTER-BOOST-001

**Behavioral Guarantee:** When the FFmpegDecoder downmixes surround audio
(3+ channels) to stereo, the center channel mix level MUST be set to a
value that prioritizes dialogue intelligibility over cinema-accurate
spatial reproduction. The center mix level MUST be at least 0 dB (linear 1.0).

**Boundary:** The center mix level is set on the SwrContext in
`FFmpegDecoder::InitializeResampler()` before `swr_init()`. It affects only
surround→stereo downmix. Stereo and mono sources pass through unchanged.

**Violation:** Surround content is downmixed with center channel at the ITU
default (-3 dB / 0.707) or lower, producing quiet dialogue relative to the
surround field.

**Derives From:** Product requirement — RetroVue simulates retro TV, not
cinema playback.

## Summary / Validation

| Check | Status |
|-------|--------|
| Document placed in existing `pkg/air/docs/design/` | PASS |
| No production code written | PASS |
| No test code written | PASS |
| No new top-level folders created | PASS |
| Core boundary preserved (no Core changes proposed for v0.1) | PASS |
| AIR boundary preserved (signal processing stays in AIR) | PASS |
| House format unchanged (S16 stereo 48 kHz) | PASS |
| Existing normalization preserved and extended, not replaced | PASS |
| No proto/schema changes required for v0.1 | PASS |
| No new cross-service contracts introduced | PASS |
| All 12 required sections present | PASS |
| Declarative spec tone, no code examples | PASS |
| Proposed invariants use outcome language, not procedure | PASS |
| **Rev1: Threshold updated to -18 dBFS with rationale** | PASS |
| **Rev1: Stereo linking moved from open question to design requirement** | PASS |
| **Rev1: Segment boundary ramp via attack envelope documented** | PASS |
| **Rev1: Limiter clarified as v0.2+ non-goal** | PASS |
| **Rev1: INV-BROADCAST-DRC-001 permits policy-based bypass** | PASS |
| **Rev1: INV-BROADCAST-DRC-004 added for linked stereo** | PASS |
