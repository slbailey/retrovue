# Phase 8.5 — Fan-out & Teardown

_Related: [Phase Model](../PHASE_MODEL.md) · [Phase 8 Overview](Phase8-Overview.md) · [Phase8-3 Preview/SwitchToLive](Phase8-3-PreviewSwitchToLive.md)_

**Principle:** Support multiple viewers and clean shutdown. One Air stream per channel; multiple HTTP readers; last viewer disconnect → Air stops writing; no leaked FDs, no zombie ffmpeg.

Shared invariants (one logical stream per channel, clean shutdown) are in the [Overview](Phase8-Overview.md).

## Document Role

This document is a **Coordination Contract**, refining higher-level laws. It does not override laws defined in this directory (see [PlayoutInvariants-BroadcastGradeGuarantees.md](../laws/PlayoutInvariants-BroadcastGradeGuarantees.md)).

## Purpose

- **Fan-out:** Multiple HTTP clients can call `GET /channels/{id}.ts` and each receives the same TS stream (or a copy). Only **one** writer (Air) per channel.
- **Teardown:** When the **last** viewer disconnects, Python signals Air (or Air infers); Air **stops** writing (stops ffmpeg, closes the stream FD, or equivalent). No ongoing work for that channel until the next tune-in.
- **No leaks:** No leaked file descriptors; no zombie ffmpeg (or child) processes after stop.

## Contract

### One Air stream per channel

- For each channel_id there is at most **one** active stream FD (write side) from Air to Python. Python may buffer and fan-out reads to multiple HTTP responses.

### Multiple HTTP readers

- Python maintains multiple subscribers fed from the same read end of the transport. Fan-out is best-effort: no per-client buffering or flow control is required. A slow or blocked client may be disconnected without affecting others. Each `GET /channels/{id}.ts` gets the same byte stream (or a logical copy).

### Backpressure and slow clients

- RetroVue uses broadcast-style delivery.
- Python is not required to buffer per client.
- If a client cannot consume data in real time, it may be disconnected.
- One slow or blocked client MUST NOT stall delivery to other clients.

### Last viewer disconnect → Air stops

- When the **last** HTTP client closes the connection (or unsubscribes), Python notifies Air (e.g. via existing tune_out / last_viewer callback or new RPC). Air then:
  - Stops writing to the stream FD.
  - Stops and cleans up ffmpeg (or whatever produces the stream).
  - Closes or releases the write end so the read end in Python sees EOF and can clean up.

### No leaked FDs; no zombie ffmpeg

- After last viewer disconnect and Air stop:
  - No open FD left for that channel's stream (except any explicitly retained for reuse by design).
  - No ffmpeg (or child) process still running for that channel.
- Clean startup: a new tune-in can create a new transport and AttachStream again.

## Execution

- ProgramDirector (or ChannelManager) tracks viewer count per channel. On tune_in: create transport and AttachStream if first viewer; subscribe HTTP response to the read side. On tune_out: unsubscribe; if count becomes 0, call Air "stop writing" / StopChannel or equivalent and close the write path.
- Air: when told "last viewer gone," stop ffmpeg, close stream FD, release resources. No background writer still attached to the FD.

## Tests

- **Multiple viewers:** Open N HTTP connections to `GET /channels/{id}.ts`; assert all receive bytes (e.g. same first K bytes or same sync pattern).
- **Last viewer disconnect:** Close all but one; then close the last; assert Air stops (no more bytes on a new connection until next StartChannel/AttachStream); assert no zombie ffmpeg (e.g. process list or cleanup hook).
- **No leaked FDs:** After last disconnect, assert FD count (or handle count) for that channel is back to baseline (e.g. 0 for that channel).

## Exit criteria

- **One Air stream per channel;** multiple HTTP readers receive the same stream.
- **Last viewer disconnect → Air stops** ffmpeg and writing.
- **No leaked FDs;** **no zombie ffmpeg** after teardown.
