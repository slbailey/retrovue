# Running the Program Director

How to start RetroVue with the Program Director (HTTP server + channel routing). This is the main way to run a channel for local testing and mock-schedule / Phase 8 flows.

## Mock A/B schedule (Air harness)

Alternating two assets on channel `test-1` (used for Air/playout testing):

```bash
retrovue program-director start --port 8000 \
  --mock-schedule-ab \
  --asset-a /opt/retrovue/assets/SampleA.mp4 \
  --asset-b /opt/retrovue/assets/SampleB.mp4
```

- **HTTP:** `http://localhost:8000/channel/{channel_id}.ts` (TS stream), `http://localhost:8000/channellist.m3u` (channel list). **Use this URL in VLC** (Media → Open Network Stream). Do not use the UDS socket path (`/run/user/.../retrovue/air/channel_*.sock`); that socket is an internal pipe and is closed after the playout engine connects.
- **Playout engine:** **Air only.** The C++ playout engine (`retrovue_air`) is the only backend. There is no ffmpeg fallback. If Air cannot be started, GET returns **503 "Air playout engine unavailable"**.

**Requirements:** Built `retrovue_air` (see Building below) or set `RETROVUE_AIR_EXE`. Asset paths must exist.

**If you see:** `Air playout engine unavailable: retrovue_air binary not found` or `Producer failed to start in mode 'normal'`:

1. Build the Air binary (see **Building the Air binary** below), then run the same command again; or  
2. Set the binary path explicitly:  
   `export RETROVUE_AIR_EXE=/path/to/retrovue_air`  
   then start Program Director. The launcher looks for, in order: `RETROVUE_AIR_EXE`, `pkg/air/build/retrovue_air`, `pkg/air/out/build/linux-debug/retrovue_air` (relative to repo root when run from the repo).

## Mock grid schedule (program + filler)

Single program + filler on a 30-minute grid:

```bash
retrovue program-director start --port 8000 \
  --mock-schedule-grid \
  --program-asset /path/to/program.mp4 \
  --program-duration 1200 \
  --filler-asset /path/to/filler.mp4
```

## Phase 8.8 behaviour (no EOF-driven stop)

**Phase 8.8** says: producer EOF must not stop the stream; the stream must continue until the last frame is rendered. That behaviour is implemented in the **Air (C++) playout engine** (producer stays running after EOF, sink drains the buffer).

Program Director is **Air-only**. The same mock A/B command uses the Air playout engine; Phase 8.8 behaviour (no EOF-driven stop) is the norm. **Ffmpeg fallback has been removed**; if Air is unavailable, the system fails fast with 503.

## Building the Air binary (default backend)

To use the default Air backend (recommended for Phase 8.8):


```bash
# From repo root; vcpkg and protos set up (see pkg/air README)
cmake -S pkg/air -B pkg/air/build \
  -DCMAKE_TOOLCHAIN_FILE="$VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake" \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build pkg/air/build
```

The binary is `pkg/air/build/retrovue_air`. Program Director looks for it (or `RETROVUE_AIR_EXE`); it runs the binary, talks gRPC, and consumes the TS stream via the accepted UDS connection.

## How to run Air-only and verify

1. **Build Air** (see above). Ensure `pkg/air/build/retrovue_air` exists and is executable, or set `RETROVUE_AIR_EXE` to its path.
2. **Start Program Director** with mock A/B:
   ```bash
   retrovue program-director start --port 8000 \
     --mock-schedule-ab \
     --asset-a /path/to/SampleA.mp4 \
     --asset-b /path/to/SampleB.mp4
   ```
3. **Check logs** for `Playout engine: AIR (no fallback)` when the first viewer connects. If you see any mention of ffmpeg being launched for playout, that is a bug (ffmpeg fallback is removed).
4. **Request the stream:** `curl -N http://localhost:8000/channel/test-1.ts | head -c 188 | xxd | head -2`  
   The first byte must be **0x47** (MPEG-TS sync). If you see `HELLO` or other non-TS data, the wrong path is active.
5. **Optional (debug):** Enable debug logging for `retrovue.runtime.channel_stream` to see the first 16 bytes (hex) of each connection; they must start with `47` (TS sync).
6. **If Air is missing or fails:** GET `/channel/{id}.ts` returns **503** with body `Air playout engine unavailable`. No placeholder stream; no reconnect loops.

## Summary

| Goal                    | Command / note                                          |
|-------------------------|----------------------------------------------------------|
| Run mock A/B (Air harness) | Command above; Air-only (no ffmpeg fallback).         |
| Phase 8.8 (no EOF stop) | Default; Air keeps running until last frame rendered.    |
| Verify real TS          | First byte of stream must be 0x47 (see runbook above).   |
| Build Air               | Build `pkg/air`; required for GET /channel/{id}.ts.      |
