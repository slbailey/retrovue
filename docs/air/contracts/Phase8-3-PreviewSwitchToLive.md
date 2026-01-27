# Phase 8.3 — Preview / SwitchToLive (TS continuity)

_Related: [Phase Model](../../contracts/PHASE_MODEL.md) · [Phase 8 Overview](Phase8-Overview.md) · [Phase8-2 Segment Control](Phase8-2-SegmentControl.md) · [Phase8-4 Fan-out & Teardown](Phase8-4-FanoutTeardown.md) · [Phase6A-1 ExecutionProducer](Phase6A-1-ExecutionProducer.md) · [Phase6A-2 FileBackedProducer](Phase6A-2-FileBackedProducer.md)_

**Principle:** Add seamless switching to the TS pipeline. Shadow decode and PTS continuity from Phase 6A become real in the byte stream: no discontinuity, no PID reset, no timestamp jump.

Shared invariants (one logical stream per channel, segment authority) are in the [Overview](Phase8-Overview.md).

## Purpose

- Run **preview** and **live** decode pipelines under Air’s control; both produce decoded frames, but only one pipeline is admitted into the TS mux at any time.
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

- **Runs:**
  - **Preview** path: decode pipeline for the next segment; produces decoded frames; does not yet feed the TS mux.
  - **Live** path: decode pipeline whose frames are currently admitted into the TS mux; mux writes to the **stream_fd** given by Python.
- **Atomic switch at SwitchToLive:** the TS mux transitions from consuming frames from the current live producer to consuming frames from the preview producer **at a frame boundary**, without interrupting the mux or resetting state. No FD changes. No mux restart. No timestamp base reset. Preview becomes live; previous live stops producing into the mux.
- **Switch timing:** the switch occurs on the first frame from the preview producer whose PTS is ≥ the next segment’s scheduled start time, consistent with Phase 8.2 frame-admission rules.
- **Guarantees** on the byte stream seen by Python (and thus by HTTP viewers):
  - **No TS discontinuity** (continuity_counter and discontinuity_flag handled so the stream is seamless or explicitly marked per spec).
  - **No PID reset** (same PIDs across the switch).
  - **No timestamp jump** (PTS/DTS continue monotonically across the switch).

### Python

- **Still a dumb pipe reader:** reads bytes from the read end of the transport and serves `GET /channels/{id}.ts`. No TS parsing for switching; no knowledge of preview vs live.

## Execution

- LoadPreview(asset_A) → Air starts the preview decode pipeline (e.g. shadow decode for the next segment); frames are not yet admitted to the TS mux.
- SwitchToLive → Air switches the single TS mux to consume from the preview producer at the scheduled frame boundary; stops the previous live producer’s admission; TS mux continues with no restart.
- Python keeps reading the same FD; it sees one continuous byte stream.

## Tests

- **Run program → filler → program** (or equivalent sequence that triggers two switches).
- **VLC** (or automated TS parser):
  - **No black frame** at the switch (or at most one acceptable frame).
  - **No audible pop** (audio continuity).
- **TS continuity validated** (e.g. continuity_counter, PTS monotonicity, PID consistency over a window around the switch).

## Explicitly out of scope (8.3)

- Fan-out and “last viewer disconnects → stop” (8.4).
- Performance and latency targets.

## Exit criteria

- **Seamless switch** in the TS pipeline: program → filler → program with no visible/audible glitch.
- **No TS discontinuity** (or only intentional/standard-compliant marking).
- **No PID reset**; **no PTS/timestamp jump** at the switch.
