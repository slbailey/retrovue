# RetroVue Phase 0 Runtime Contract (Canonical)

---

## Invariants

- **Channels exist in time** — even when not streaming.
- **Per-channel playout engines** only run when at least one viewer is present.
- **Playback is linear only** — no rewind, no pause, no history, and no file segments.

---

## Scope

- **Channels:** 1 (`test-1`)
- **Program asset:** 1 (reused)
- **Filler asset:** 1 (looped)
- **Schedule:** Fixed 30-minute grid
- **Viewing:** Join-in-progress via time offset

---

## Required Surfaces

### **ProgramDirector** (system control plane)

- `GET /channels`
- `GET /channel/{id}.ts`
- `POST /admin/emergency` <span style="color: #999999;">*(no-op for now)*</span>

**Responsibilities:**
- Owns in-memory `FanoutBuffer` per channel
- Routes viewers to `ChannelManager` instances
- Enforces global mode/policy

---

### **ChannelManager** (per-channel runtime executor)

**Public API:**
- `tune_in(viewer_id)`
- `tune_out(viewer_id)`
- `on_first_viewer()`
- `on_last_viewer()`

**Responsibilities:**
- Calculate grid alignment & offsets
- Determine when program vs. filler is active
- Issue `PlayoutRequest`s to internal playout engine
- Spawn and supervise its per-channel playout engine process

---

### **Internal Playout Engine** (per channel)

- `StartChannel(channel_id, plan, offset, output_endpoint)`
- `StopChannel(channel_id)`

**Responsibilities:**
- Preload assets into preview buffer
- Emit MPEG-TS bytes to the `FanoutBuffer`

---

## Non-goals

- No ingest UI
- No metadata editing
- No schedule UI
- No ads
- No persistence
- No pooled engines
- No shared Air fabric
