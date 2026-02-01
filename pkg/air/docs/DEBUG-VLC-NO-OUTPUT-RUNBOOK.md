# VLC "No Output" Debug Runbook

## Instrumentation Summary

All instrumentation is **DBG-only** and reversible. Log tags: `[DBG-BUS]`, `[DBG-ENQUEUE]`, `[DBG-DROP]`, `[DBG-MUXSTATE]`, `[DBG-OUTPUT]`, `[DBG-PACING]`, `[DBG-BOOTSTRAP]`, `[DBG-SWITCH]`, `[DBG-PO]`.

## Environment Variables

| Variable | Effect |
|----------|--------|
| `RETROVUE_NO_PCR_PACING=1` | Disables PCR pacing sleeps. Use to prove pacing is not blocking. |
| `RETROVUE_DBG_BOOTSTRAP_WRITE=1` | Repeats magic string every second until first real TS packet. Confirms reader is consuming bytes. |

## Deterministic Runbook (no socat)

### Steps

1. **Start HTTP listener** (your existing setup that accepts UDS and serves MPEG-TS over HTTP).
2. **Start Air engine** (retrovue_air or your launcher).
3. **Attach stream** (gRPC `AttachStream`).
4. **SwitchToLive** (gRPC `SwitchToLive`; may retry on NOT_READY).
5. **Open stream in VLC** (GET the HTTP URL).
6. **Watch logs** — collect 10–15 seconds of `[DBG-*]` lines.

### Optional: PCR pacing bypass

```bash
RETROVUE_NO_PCR_PACING=1 ./retrovue_air ...
```

### Optional: Bootstrap write (confirm reader consumes)

```bash
RETROVUE_DBG_BOOTSTRAP_WRITE=1 ./retrovue_air ...
```

## Decision Tree / Interpretation Table

| Observation | Diagnosis |
|-------------|-----------|
| `[DBG-BUS]` v_routed increases, `[DBG-ENQUEUE]` v_enq stays 0 | OutputBus → Sink wiring bug (sink not called, or IsRunning() false). |
| `[DBG-ENQUEUE]` v_enq increases, mux stays `WAITING_FOR_VIDEO` with vq=0 | Queue visibility or dequeue bug (different queues, or MuxLoop not draining). |
| `[DBG-MUXSTATE]` READY_TO_EMIT, but `[DBG-OUTPUT]` bytes=0 | Encoder not producing packets, or write blocked. |
| `[DBG-OUTPUT]` bytes increases, VLC shows nothing | Downstream demux issue. Capture to file and ffprobe. |
| `[DBG-BUS]` v_routed=0 forever | ProgramOutput not calling RouteVideo (no bus, or frames not flowing). |
| `[DBG-PO] SetOutputBus bus=no` | ProgramOutput never received bus; FinalizeLiveOutput not called. |
| `[DBG-SWITCH] auto_completed=true sink_attached=no` | Late-attach path: sink attached after switch; TryAttachSinkForChannel must run on AttachStream. |
| `[DBG-DROP]` appears | Queue full; producer too fast or mux too slow. |
| `[DBG-BOOTSTRAP]` magic repeat, but no `[DBG-OUTPUT]` TS bytes | Reader is consuming; mux never emits real TS. |

## Log Reference

| Tag | Format | Rate |
|-----|--------|------|
| `[DBG-BUS]` | v_routed=… a_routed=… sink=yes/no running=yes/no | 1/sec when RouteVideo called |
| `[DBG-ENQUEUE]` | v_enq=… a_enq=… vq_size=… aq_size=… | 1/sec when ConsumeVideo/ConsumeAudio called |
| `[DBG-DROP]` | video_drop=1 / audio_drop=1 reason=QUEUE_FULL | On each drop |
| `[DBG-MUXSTATE]` | WAITING_FOR_VIDEO / WAITING_FOR_PCR_TIME / READY_TO_EMIT vq=… aq=… head_ct=… head_pts=… | On state change |
| `[DBG-OUTPUT]` | bytes=… packets=… ms_since_last_write=… | 1/sec (MuxLoop heartbeat) |
| `[DBG-PACING]` | RETROVUE_NO_PCR_PACING=1: pacing DISABLED | Once at startup |
| `[DBG-BOOTSTRAP]` | Magic string repeat (n bytes) fd=… | 1/sec when enabled and WAITING_FOR_VIDEO |
| `[DBG-SWITCH]` | auto_completed=… bus_connected=… sink_attached=… | On SwitchToLive completion |
| `[DBG-PO]` | SetOutputBus channel=… bus=yes/no | On SetOutputBus |
| `[DBG-BUS]` | sink attached / sink detached | On AttachSink / DetachSink |

## Files Modified (for rollback)

- `pkg/air/include/retrovue/output/OutputBus.h` — dbg counters, heartbeat time
- `pkg/air/src/output/OutputBus.cpp` — RouteVideo/RouteAudio heartbeat, attach/detach logs
- `pkg/air/src/output/MpegTSOutputSink.cpp` — enqueue heartbeat, drop detection, mux state, write heartbeat, bootstrap write
- `pkg/air/src/runtime/PlayoutEngine.cpp` — `[DBG-SWITCH]` auto_completed logs
- `pkg/air/src/renderer/ProgramOutput.cpp` — `[DBG-PO]` SetOutputBus (already present)
