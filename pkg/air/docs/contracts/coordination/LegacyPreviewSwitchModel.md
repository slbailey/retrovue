# ⚠️ RETIRED — Superseded by BlockPlan Architecture

**See:** [Phase8DecommissionContract.md](../../../../docs/contracts/architecture/Phase8DecommissionContract.md)

This document describes legacy playlist/Phase8 execution and is no longer active.

---

# Phase 8.3 — Preview / SwitchToLive (TS continuity)

_Related: [Phase Model](../PHASE_MODEL.md) · [Phase 8 Overview](Phase8-Overview.md) · [Phase8-2 Segment Control](Phase8-2-SegmentControl.md) · [Phase8-4 Persistent MPEG-TS Mux](Phase8-4-PersistentMpegTsMux.md) · [Phase8-5 Fan-out & Teardown](Phase8-5-FanoutTeardown.md) · [Phase6A-1 ExecutionProducer](../../archive/phases/Phase6A-1-ExecutionProducer.md) · [Phase6A-2 FileBackedProducer](../../archive/phases/Phase6A-2-FileBackedProducer.md)_

**Principle:** Add seamless switching to the TS pipeline. Shadow decode and PTS continuity from Phase 6A become real in the byte stream: no discontinuity, no PID reset, no timestamp jump.

**Authoritative definition of the switching law** (no gaps, no PTS regression, no silence during switches) **lives in [PlayoutInvariants-BroadcastGradeGuarantees.md](../laws/PlayoutInvariants-BroadcastGradeGuarantees.md).**

Shared invariants (one logical stream per channel, segment authority) are in the [Overview](Phase8-Overview.md).

## Document Role

This document is a **Coordination Contract**, refining higher-level laws. It does not override laws defined in this directory (see [PlayoutInvariants-BroadcastGradeGuarantees.md](../laws/PlayoutInvariants-BroadcastGradeGuarantees.md)).

## Purpose

- Run **preview** and **live** decode pipelines under Air's control; both produce decoded frames, but only one pipeline is admitted into the TS mux at any time.
- On **SwitchToLive**, the TS mux **atomically** transitions from consuming frames from the current live producer to consuming frames from the preview producer at a frame boundary (see below), so that:
  - The TS stream remains valid.
  - **No TS discontinuity** (no spurious discontinuity indicators unless intended).
  - **No PID reset** (PIDs stay consistent across the switch).
  - **No timestamp jump** (PTS/DTS continuity so that players do not see a visible/audible glitch).

Python remains a dumb pipe reader; all switching and continuity are enforced in Air (or the process writing to the FD).

## Contract

### Air

**Single TS muxer (hard invariant)**

There is **exactly one TS muxer per channel**. It is created once and persists across all segment switches. Continuity counters, PIDs, and timestamp bases never reset during preview/live transitions.

**Segment mapping invariants (INV-P8-SWITCH-001, INV-P8-SWITCH-002)**

These invariants govern how the TimelineController maps media time (MT) to channel time (CT) during segment switches:

- **INV-P8-SWITCH-001: Mapping must be pending BEFORE preview fills**
  - If preview exits shadow and begins writing frames before the segment mapping is pending, the mapping can lock against the wrong MT (or never lock deterministically).
  - SwitchToLive() must call `BeginSegmentPending()` before disabling shadow mode on the preview producer.

- **INV-P8-WRITE-BARRIER-DEFERRED: Write barrier waits for shadow decode ready**
  - A producer required for switch readiness MUST be allowed to write until readiness is achieved.
  - The write barrier on the live producer must NOT be set until the preview has cached its first shadow frame (IsShadowDecodeReady() == true).
  - If the barrier is set before preview is ready, both producers are blocked and CT stalls:
    - Live is barriered → cannot feed timeline
    - Preview is seeking → cannot feed timeline yet
    - Result: timeline starvation, subsequent frames rejected as "early"
  - Switch is "armed" (switch_in_progress=true) immediately, but the barrier is deferred until preview is ready.

- **INV-P8-SWITCH-002: CT and MT must describe the same instant at segment start**
  - When switching segments, we cannot precompute `CT_start` because wall clock advances between the `BeginSegmentPending()` call and when the first preview frame is admitted.
  - `BeginSegmentPending()` defers **both** CT and MT to the first admitted frame:
    - `CT_start = wall_clock_at_admission - epoch` (current CT position when frame arrives)
    - `MT_start = first_frame_media_time`
  - This ensures CT and MT describe the EXACT same instant, preventing timeline skew that would cause all subsequent frames to be rejected as "early" or "late".

- **INV-P8-SHADOW-PACE: Shadow mode must pause after first cached frame**
  - Shadow decode mode caches the first decoded frame, then **waits in place** until shadow mode is disabled.
  - The producer must NOT continue decoding frames while in shadow mode.
  - Without this invariant, the preview producer would consume the entire file before the switch occurs.
  - Implementation: After caching the first frame, the producer loops with `sleep_for(5ms)` checking `shadow_decode_mode_` and `stop_requested_` until shadow mode is disabled.
  - When shadow mode is disabled, the **same frame** (already decoded) proceeds through AdmitFrame.

- **INV-P8-AUDIO-GATE: Audio only gated while shadow_decode_mode_ is true**
  - Audio frames are gated (dropped) only while the producer is in shadow decode mode.
  - Audio is **NOT** gated based on `IsMappingPending()` — that would cause starvation.
  - Rationale: When video's `AdmitFrame()` locks the segment mapping, audio on the same decode iteration must proceed ungated. If audio checked `IsMappingPending()`, it would be gated indefinitely.
  - Implementation: `bool audio_should_be_gated = shadow_decode_mode_.load(std::memory_order_acquire);`

- **INV-P8-SEGMENT-COMMIT: Explicit segment commit with timeline ownership**
  - When a segment's mapping locks (first frame admitted), that segment **commits** and takes exclusive ownership of CT.
  - The old segment is dead at this instant and must be closed (RequestStop).
  - Commit is tracked via:
    - `current_segment_id_`: The ID of the segment that owns CT (0 = none).
    - `HasSegmentCommitted()`: Returns true if a segment has committed (state-based).
  - This models broadcast-style segment ownership: the new segment "owns the timeline" and the old segment must yield.

- **INV-P8-SEGMENT-COMMIT-EDGE: Generation counter for multi-switch support**
  - `HasSegmentCommitted()` is state-based — it returns true continuously after the first commit.
  - For 2nd, 3rd, Nth switches, we need **edge detection** (did a commit happen since we last checked?).
  - `segment_commit_generation_` increments exactly once per commit.
  - SwitchWatcher tracks `last_seen_commit_gen` and detects edges:
    ```cpp
    if (current_commit_gen > last_seen_commit_gen) {
      // Commit edge detected — close old segment
      last_seen_commit_gen = current_commit_gen;
    }
    ```
  - This ensures the old producer is closed exactly once per switch, regardless of how many switches have occurred.

- **Runs:**
  - **Preview** path: decode pipeline for the next segment; produces decoded frames; does not yet feed the TS mux.
  - **Live** path: decode pipeline whose frames are currently admitted into the TS mux; mux writes to the **stream_fd** given by Python.
- **Atomic switch at SwitchToLive:** the TS mux transitions from consuming frames from the current live producer to consuming frames from the preview producer **at a frame boundary**, without interrupting the mux or resetting state. No FD changes. No mux restart. No timestamp base reset. Preview becomes live; previous live stops producing into the mux.
- **Switch timing:** the switch occurs on the first frame from the preview producer whose PTS is ≥ the next segment's scheduled start time, consistent with Phase 8.2 frame-admission rules.
- **Guarantees** on the byte stream seen by Python (and thus by HTTP viewers):
  - **No TS discontinuity** (continuity_counter and discontinuity_flag handled so the stream is seamless or explicitly marked per spec).
  - **No PID reset** (same PIDs across the switch).
  - **No timestamp jump** (PTS/DTS continue monotonically across the switch).

### Python

- **Still a dumb pipe reader:** reads bytes from the read end of the transport and serves `GET /channels/{id}.ts`. No TS parsing for switching; no knowledge of preview vs live.

## Execution

- LoadPreview(asset_A) → Air starts the preview decode pipeline (e.g. shadow decode for the next segment); frames are not yet admitted to the TS mux.
- SwitchToLive → Air switches the single TS mux to consume from the preview producer at the scheduled frame boundary; stops the previous live producer's admission; TS mux continues with no restart.
- Python keeps reading the same FD; it sees one continuous byte stream.

## Test assets

For switch sequences (e.g. program → filler → program, or A → B → A):

- **SampleA.mp4**, **SampleB.mp4** — `assets/SampleA.mp4`, `assets/SampleB.mp4` (for LoadPreview/SwitchToLive sequences).
- **filler.mp4** — `assets/filler.mp4` (optional middle segment).

Paths are relative to repo root; tests may use `RETROVUE_TEST_VIDEO_PATH` or equivalent for override.

## Tests

- **Run program → filler → program** (or equivalent sequence that triggers two switches; e.g. LoadPreview(SampleA) → SwitchToLive → LoadPreview(SampleB) → SwitchToLive).
- **VLC** (or automated TS parser):
  - **No black frame** at the switch (or at most one acceptable frame).
  - **No audible pop** (audio continuity).
- **TS continuity validated** (e.g. continuity_counter, PTS monotonicity, PID consistency over a window around the switch).

## Explicitly out of scope (8.3)

- Fan-out and "last viewer disconnects → stop" (8.5).
- Performance and latency targets.

## Exit criteria

- **Seamless switch** in the TS pipeline: program → filler → program with no visible/audible glitch.
- **No TS discontinuity** (or only intentional/standard-compliant marking).
- **No PID reset**; **no PTS/timestamp jump** at the switch.
