# Phase 8.4 — Persistent MPEG-TS Mux (Single Producer)

_Related: [Phase Model](../../contracts/PHASE_MODEL.md) · [Phase 8 Overview](Phase8-Overview.md) · [Phase8-1 Air Owns MPEG-TS](Phase8-1-AirOwnsMpegTs.md) · [Phase8-2 Segment Control](Phase8-2-SegmentControl.md) · [Phase8-3 Preview/SwitchToLive](Phase8-3-PreviewSwitchToLive.md) · [Phase8-5 Fan-out & Teardown](Phase8-5-FanoutTeardown.md) · [OutputBus & OutputSink Contract](../../contracts/architecture/OutputBusAndOutputSinkContract.md) (jitter protection)_

**Principle:** Establish a real, persistent MPEG-TS mux per channel per active stream session that converts decoded frames into a continuous, spec-compliant TS byte stream. This phase makes TS continuity real for the first time.

## Document Role

This document is a **Coordination Contract**, refining higher-level laws. It does not override laws defined in this directory (see [PlayoutInvariants-BroadcastGradeGuarantees.md](../PlayoutInvariants-BroadcastGradeGuarantees.md)).

## Purpose

- **One TS mux per channel per active stream session**
- **Feed it from one active producer** (decoded audio+video frames)
- **Write TS packets to the stream FD**
- **Mux owns:** PID map, continuity counters, PAT/PMT lifecycle, PCR/PTS timing
- **Producer:** emits decoded frames only; does not own PIDs or continuity

This phase makes the byte stream real — everything before this was scaffolding.

## Session lifetime boundary

**One TS mux per channel per active stream session.**

- **Session** begins at successful `AttachStream(channel_id, …)` and ends at `DetachStream(channel_id)` or `StopChannel(channel_id)`.

**Within a session:**

- Mux is created once (when TS output starts, e.g. on first SwitchToLive with attached stream).
- Mux persists across all segment boundaries (no restart on segment change).
- Stream endpoint/FD is fixed (the FD supplied at AttachStream is used for the whole session).

**Across sessions:**

- Mux may be destroyed and recreated (e.g. after DetachStream and a later AttachStream, or replace_existing / teardown logic in future phases).

This avoids conflict when adding replace_existing or teardown: the invariant applies per session, not forever.

## Hard invariants (non-negotiable)

- **No PID reset** within a session. No continuity_counter reset within a session.
- **PSI cadence (no PAT/PMT spam):** PAT and PMT must be emitted at least every **X ms** (e.g. 100–500 ms) or at least every **N packets**, and must also appear at stream start. They must **not** be emitted per frame or per PES packet.
- **PCR:** PCR monotonic per PCR PID; PCR PID is stable within a session; PCR/PTS timebase consistent (no jumps). (TS continuity is not just continuity counters and PTS — PCR keeps timing sane; without it, VLC can still exhibit "audio leads video" behaviour.)
- **Jitter protection:** The output path (OutputBus and/or OutputSink) must provide jitter protection per the [OutputBus & OutputSink Contract](../../contracts/architecture/OutputBusAndOutputSinkContract.md). This phase’s PCR/PTS and continuity guarantees assume that requirement is satisfied.
- **Single producer:** Producer emits **decoded audio+video frames** (not TS bytes). Mux **accepts frames and outputs TS**. The **mux owns the PID map and continuity counters**, not the producer. (Makes 8.3 obvious: switch frame source, not mux.)

## Scope (very tight)

### Air MUST

- Use libavformat (or equivalent) to create a TS mux.
- Mux: allocate and own video PID(s), audio PID(s), PCR PID; emit PAT/PMT at start and at the specified cadence (not per-frame).
- Accept **decoded frames** from the current live producer; convert frames → TS packets; write TS packets to the stream FD.
- Ensure PCR monotonicity and stable PIDs within a session.

### Air MUST NOT (in 8.4)

- Emit PAT/PMT per frame or per PES packet.
- Support fan-out, or stop on viewer disconnect.
- Put PID map or continuity counters in the producer.
- **Destroy or recreate the TS mux** as part of SwitchToLive or LoadPreview.

### Python

- **Completely unchanged.** Still a dumb byte pipe. Still just HTTP.

## Stream start and A/V behaviour (testable)

- **Decodable video quickly:** Within **T seconds** of first TS byte, a decodable video frame (IDR/keyframe) must be present, or codec config / sequence headers must be sent such that the first emitted video is decodable.
- **A/V start:** First audio PTS must **not** lead first video PTS by more than **Δ** (e.g. 100–250 ms) at stream start. (Otherwise "no audio before video surprises" is too vague to enforce.)

## Required automated tests (exact checks)

These tests **must** exist and perform the following **exact** checks:

### TS validity

- Verify **TS packet size is 188** for every packet.
- Verify **sync byte 0x47** every packet.
- **Parse PAT and PMT successfully** (not just "stream contains" — actually parse and validate structure).

### PID stability

- Extract PMT and record:
  - PMT PID
  - PCR PID
  - video PID(s)
  - audio PID(s)
- **Assert these do not change** over a window (e.g. 10–30 seconds of output or equivalent packet count for short captures).

### Continuity counters

- For each PID carrying payload:
  - **Continuity counter increments modulo 16** (next_expected = (last_cc + 1) & 0x0f).
- Allow discontinuity **only** if **discontinuity_indicator** is set, and only at session start (or never, depending on requirement). Otherwise no resets.

### Timing

- **PTS monotonic** per stream (audio and video); no backwards jumps.
- **PCR monotonic**; no backwards jumps.
- PCR/PTS timebase consistent (no jumps).

Manual VLC playability is allowed as a sanity check, but **automated TS parsing with the above checks is required**.

## Exit criteria

- **VLC plays the stream continuously** (sanity check).
- **No "audio before video" surprises** as defined above (decodable video within T s; first audio PTS does not lead first video PTS by > Δ).
- **TS parser:** stable PIDs, stable continuity counters, PAT/PMT parsed, PCR and PTS monotonic.
- **No mux restarts on segment boundaries** within a session.

## How this re-unlocks Phase 8.3 (TS semantics)

Once 8.4 exists:

- 8.3 contract becomes **enforceable**.
- Preview/SwitchToLive: switch **frame source** only; mux (and thus PIDs, continuity, PCR/PTS) is unchanged.
- You can assert: no black frames, no audio pops, no timestamp jumps, because the mux is persistent within the session and the tests above are in place.

Right now 8.3 is correct but unobservable. **8.4 makes it observable.**
