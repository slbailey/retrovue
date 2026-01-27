# Phase 8.3 — Preview / SwitchToLive (TS continuity)

_Related: [Phase Model](../../contracts/PHASE_MODEL.md) · [Phase 8 Overview](Phase8-Overview.md) · [Phase8-2 Segment Control](Phase8-2-SegmentControl.md) · [Phase8-4 Fan-out & Teardown](Phase8-4-FanoutTeardown.md) · [Phase6A-1 ExecutionProducer](Phase6A-1-ExecutionProducer.md) · [Phase6A-2 FileBackedProducer](Phase6A-2-FileBackedProducer.md)_

**Principle:** Add seamless switching to the TS pipeline. Shadow decode and PTS continuity from Phase 6A become real in the byte stream: no discontinuity, no PID reset, no timestamp jump.

Shared invariants (one logical stream per channel, segment authority) are in the [Overview](Phase8-Overview.md).

## Purpose

- Run **preview** ffmpeg (or decoder) and **live** ffmpeg (or decoder) under Air’s control.
- On **SwitchToLive**, **atomically** switch the write source to the stream FD so that:
  - The TS stream remains valid.
  - **No TS discontinuity** (no spurious discontinuity indicators unless intended).
  - **No PID reset** (PIDs stay consistent across the switch).
  - **No timestamp jump** (PTS/DTS continuity so that players do not see a visible/audible glitch).

Python remains a dumb pipe reader; all switching and continuity are enforced in Air (or the process writing to the FD).

## Contract

### Air

- **Runs:**
  - **Preview** path: decodes (e.g. ffmpeg) for the next segment; may produce TS or internal frames; does not yet feed the live output.
  - **Live** path: produces TS and writes to the **stream_fd** given by Python.
- **Switches write source atomically** at **SwitchToLive** (preview becomes live; previous live stops).
- **Guarantees** on the byte stream seen by Python (and thus by HTTP viewers):
  - **No TS discontinuity** (continuity_counter and discontinuity_flag handled so the stream is seamless or explicitly marked per spec).
  - **No PID reset** (same PIDs across the switch, or a single well-defined handoff).
  - **No timestamp jump** (PTS/DTS continue monotonically across the switch).

Implementation may use a single muxer fed by two producers with a cut-over, or two ffmpeg instances with a handoff that preserves continuity; the contract is on the observable TS, not the implementation.

### Python

- **Still a dumb pipe reader:** reads bytes from the read end of the transport and serves `GET /channels/{id}.ts`. No TS parsing for switching; no knowledge of preview vs live.

## Execution

- LoadPreview(asset_A) → Air starts “preview” (e.g. shadow decode / TS generation for next segment).
- SwitchToLive → Air makes the preview output the live stream; stops the previous live writer; new TS continues with continuity.
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
