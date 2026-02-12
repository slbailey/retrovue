# ⚠️ RETIRED — Superseded by BlockPlan Architecture

**See:** [Phase8DecommissionContract.md](../../../../docs/contracts/architecture/Phase8DecommissionContract.md)

This document describes legacy playlist/Phase8 execution and is no longer active.

---

# Phase 8.7 — Immediate Teardown & Lifecycle Ownership

_Related: [Phase Model](../PHASE_MODEL.md) · [Phase 8 Overview](Phase8-Overview.md) · [Phase8-5 Fan-out & Teardown](Phase8-5-FanoutTeardown.md) · [Phase8-6 Real MPEG-TS E2E](Phase8-6-RealMpegTsE2E.md)_

**Principle:** Strict lifecycle ownership and **immediate** teardown when viewer count drops to zero. ProgramDirector is the authoritative owner; ChannelManager and Air activity exist only while there is at least one viewer. No background work, no reconnect attempts, and no ffmpeg/libav activity after teardown.

## Document Role

This document is a **Coordination Contract**, refining higher-level laws. It does not override laws defined in this directory (see [PlayoutInvariants-BroadcastGradeGuarantees.md](../laws/PlayoutInvariants-BroadcastGradeGuarantees.md)).

## Purpose

- **Authoritative ownership:** ProgramDirector owns channel lifecycle. ChannelManager and the associated producer (Air/ffmpeg) exist only when viewer count ≥ 1.
- **Immediate teardown:** When viewer count transitions 1 → 0, the channel is torn down **immediately**. No waiting for EOF, segment completion, or drain.
- **No background activity after teardown:** Health checks, segment supervisors, and reconnect loops MUST NOT run or retry after teardown. No ffmpeg/libav processes and no UDS activity for that channel until the next tune-in.

## Contract

1. **ProgramDirector is the authoritative owner of channel lifecycle.** All decisions to create or destroy a channel’s runtime (ChannelManager, transport, producer) are made by or delegated through ProgramDirector. No other component may keep a channel “alive” when ProgramDirector has determined viewer count is zero.

2. **ChannelManager MUST be created only when viewer count transitions 0 → 1.** There must be no ChannelManager (or equivalent per-channel runtime) for a channel that has zero viewers. Creation happens on first tune-in for that channel.

3. **ChannelManager MUST be destroyed immediately when viewer count transitions 1 → 0.** On last viewer disconnect, the ChannelManager (and any handle to it used for that channel) is torn down in the same logical step. No retention of ChannelManager for “idle” or “STOPPED” state; the channel runtime is removed. “Immediately” means within 250ms (unit/integration) and within 1s (E2E), without waiting for clip/segment completion.

4. **No background loops may continue after teardown.** Health-check loops, reconnect loops, segment-supervisor logic, and any periodic or event-driven work for that channel MUST stop when viewer count becomes 0. No polling, no “next segment” restarts, and no reconnect attempts for the torn-down channel. EOF from the producer is never a reason to reconnect or restart when viewer_count == 0. When viewer_count > 0, EOF may result in switching to the next scheduled item (future phase), but must not involve reconnect loops; it is an internal state transition.

5. **Air MUST stop producing output immediately on teardown.** On receipt of teardown (e.g. StopChannel or equivalent), Air MUST stop writing to the stream FD and MUST terminate the producer (ffmpeg, EncoderPipeline, or equivalent) without waiting for EOF or segment completion. No “drain to end of segment” or “finish current frame” unless explicitly specified as a later phase.

6. **No UDS reconnect attempts after teardown.** Once the last viewer has disconnected and teardown has been signaled, no component may attempt to reconnect to the channel’s UDS (or stream endpoint). The transport is closed and not reused until a new viewer triggers 0 → 1 and a new channel runtime is created. Any log line containing “attempting reconnect” for that channel after teardown is a contract violation (testable in E2E).

7. **No encode/decode/mux pipeline activity after teardown.** No encode/decode/mux pipeline remains active for that channel after teardown (no threads, tasks, or subprocesses; no open handles to libav contexts). No such activity until the next tune-in.

## Explicit non-goals

- **Continuous broadcast with no viewers.** Phase 8.7 does NOT require (or allow) a channel to keep producing output when viewer count is zero. “Background” or “simulcast” operation with zero viewers is out of scope.
- **Graceful drain or segment completion on teardown.** Immediate stop is required; any future phase that defines a short drain window would be a separate contract.
- **Persistent channel identity or “warm” channel.** A channel’s runtime (ChannelManager, UDS, producer) is not preserved across 1 → 0; the next 0 → 1 creates a fresh runtime.

## Execution model

### Connect (viewer count 0 → 1)

1. Viewer issues `GET /channels/{channel_id}.ts` (or equivalent tune-in).
2. ProgramDirector (or its delegate) determines that viewer count for that channel is transitioning 0 → 1.
3. **Create** the channel runtime: create ChannelManager for that channel (if not already present); create or obtain transport (e.g. UDS) and stream endpoint.
4. Signal Air (or launch producer): StartChannel / AttachStream / start producer (e.g. ffmpeg) so that the stream FD receives TS output.
5. Subscribe the viewer to the stream (fan-out); respond with HTTP 200 and stream body.
6. From this point until teardown, health-check and segment-supervisor logic (if any) may run **only** while viewer count remains ≥ 1.

### Disconnect (viewer count 1 → 0)

1. Last viewer closes the connection (or unsubscribes). ProgramDirector (or delegate) detects viewer count transitioning 1 → 0.
2. **Immediately** signal teardown to Air (e.g. StopChannel or equivalent): Air MUST stop writing and MUST terminate the producer (ffmpeg/EncoderPipeline) without waiting for EOF or segment end.
3. **Immediately** destroy or deactivate the channel runtime: ChannelManager for that channel is destroyed (or removed from the set of active channel runtimes). Close the stream FD / UDS; release any handles.
4. Stop all background work for that channel: health-check must not run for this channel; reconnect loops must not run; segment-supervisor must not run. No further UDS reconnect attempts and no further ffmpeg/libav activity for this channel.
5. Subsequent requests for that channel’s stream receive no data (or a new 0 → 1 path creates a fresh runtime and producer).

**Teardown API boundary.** ProgramDirector triggers teardown via a single call (e.g. `ChannelManager.stop()` / `dispose()`) that is synchronous: it returns only after the channel runtime has stopped background tasks and released transport resources. Implementations may use async internals, but the observable contract is synchronous.

## Baseline resource invariants

After teardown, per-channel resources return to baseline:

- No open UDS socket for that channel path
- No open stream FD for that channel
- No active background tasks registered for that channel
- ChannelManager removed from ProgramDirector (or provider) registry

Tests and implementations can use this checklist; regression is obvious if any invariant fails.

## Tests

- **Unit:** Given a channel with one viewer, simulate last viewer disconnect; assert that ChannelManager (or equivalent) is destroyed/removed within 250ms and that no health-check or segment-supervisor logic is invoked for that channel after teardown.
- **Integration:** Last viewer disconnect → assert that StopChannel (or equivalent) is called; assert teardown completes within 250ms; assert that the producer pipeline is no longer running for that channel; assert that no log line contains “attempting reconnect” for that channel after teardown.
- **E2E:** Open stream in a client (e.g. VLC or HTTP client); verify bytes received; close the client (last viewer); assert teardown within 1s; assert logs show teardown and no “attempting reconnect” (or producer restarts) after teardown; assert baseline resource invariants (no UDS, no stream FD, no background tasks, ChannelManager removed). Re-open the same channel URL; assert a **new** producer is started and stream is served (fresh runtime).

## Exit criteria

- **ProgramDirector** is the authoritative owner of channel lifecycle; ChannelManager is created only on 0 → 1 and destroyed immediately on 1 → 0 (within 250ms unit/integration, 1s E2E).
- **No background activity after teardown:** no health checks, no reconnect loops, no segment supervisors for the torn-down channel; EOF is not a trigger to reconnect or restart when viewer_count == 0.
- **Air stops immediately on teardown:** no EOF wait, no segment completion wait; producer pipeline is terminated and no output is written after teardown.
- **No UDS reconnect attempts** after teardown; no log line “attempting reconnect” for that channel after teardown. **No encode/decode/mux pipeline** (threads, tasks, subprocesses, or libav handles) remains active for that channel.
- **Baseline resource invariants** hold after teardown: no open UDS for that channel path, no open stream FD, no active background tasks for that channel, ChannelManager removed from registry.
- **Phase 8.5 and Phase 8.6 tests** continue to pass; new tests for immediate teardown and lifecycle (unit, integration, e2e) pass.
