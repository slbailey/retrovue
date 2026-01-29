# MPEG-TS Playout Sink Timing Contract

_Related: [MPEG-TS Sink Contract](MpegTSPlayoutSinkDomainContract.md) · [Playout Engine Contract](PlayoutEngineContract.md) · [Phase 6A Overview](Phase6A-Overview.md)_

**Applies starting in:** Phase 7+ (MPEG-TS serving)  
**Status:** Deferred during Phase 6A; Enforced when TS sink timing is in scope

## Phase 6A Deferral

**This contract is not enforced during Phase 6A.** Phase 6A explicitly defers MPEG-TS serving; sink timing applies only when the TS output path exists. All guarantees below are **preserved** as institutional knowledge and **future intent**. Nothing is deleted — only scoped to post-6A enforcement.

---

## Purpose

Define the timing guarantees for the **MPEG-TS Playout Sink** — specifically when frames are output relative to MasterClock. This contract specifies **what** timing guarantees the sink provides, not how they are achieved internally.

---

## Timing Guarantees

### T-001: MasterClock Authority

**Guarantee:** Sink uses MasterClock as sole time source.

**Observable behavior:**
- All timing decisions based on MasterClock
- No direct system clock usage
- Sleep durations derived from MasterClock delta

**Verification:** Inject fake MasterClock; verify sink follows it exactly.

---

### T-002: PTS to Station Time Mapping

**Guarantee:** Frame PTS maps to station time via anchored transform.

**Observable behavior:**
- First frame anchors PTS zero to current MasterClock time
- Subsequent frames scheduled relative to anchor
- PTS values are monotonically increasing

**Verification:** Feed frames with known PTS; verify output times match expected station times.

---

### T-003: On-Time and Early Frame Handling

**Guarantee:** Frames are held until their scheduled time.

**Observable behavior:**
- Frame with future PTS causes wait until scheduled time
- Frame output occurs at scheduled time (±1ms tolerance)
- No frames output ahead of schedule

**Verification:** Verify frame output time equals target time within tolerance.

---

### T-004: Underrun Handling

**Guarantee:** Empty buffer causes backoff, not crash.

**Observable behavior:**
- `buffer_underruns` counter increments
- Sink backs off briefly (2-5ms)
- Sink retries and resumes when frames available
- No infinite loops or high CPU spin

**Verification:** Start with empty buffer; verify counter increments and worker remains alive.

---

### T-005: Late Frame Detection and Drops

**Guarantee:** Frames beyond late threshold are dropped.

**Observable behavior:**
- Frames within tolerance: output immediately
- Frames beyond threshold: dropped
- `late_frame_drops` counter increments
- Sink continues to next frame (catch-up)

**Verification:** Advance clock past frame deadline; verify frame dropped and counter updated.

---

### T-006: Monotonic Output Order

**Guarantee:** Frames never output out of PTS order.

**Observable behavior:**
- All output frames have PTS >= previous frame
- Even with drops, order preserved
- No reordering regardless of timing

**Verification:** Record output PTS sequence; verify strictly increasing.

---

### T-007: Graceful Stop

**Guarantee:** Stop exits timing loop within bounded time.

**Observable behavior:**
- Stop flag checked every iteration
- Thread exits within 100ms of stop request
- No frames output after stop

**Verification:** Call stop; verify thread joins within timeout; verify no subsequent outputs.

---

## Behavioral Rules Summary

| Rule | Guarantee |
|------|-----------|
| T-001 | MasterClock is sole time source |
| T-002 | PTS maps to station time |
| T-003 | Frames held until scheduled time |
| T-004 | Empty buffer causes backoff |
| T-005 | Late frames dropped |
| T-006 | Output order is monotonic |
| T-007 | Stop exits within 100ms |

---

## Test Coverage

| Rule | Test |
|------|------|
| T-001 | `test_sink_timing_clock_usage` |
| T-002 | `test_sink_timing_pts_mapping` |
| T-003 | `test_sink_timing_early_frames` |
| T-004 | `test_sink_timing_underrun` |
| T-005 | `test_sink_timing_late_drops` |
| T-006 | `test_sink_timing_order` |
| T-007 | `test_sink_timing_stop` |

---

## See Also

- [MPEG-TS Sink Contract](MpegTSPlayoutSinkDomainContract.md) — encoding and streaming
- [Playout Engine Contract](PlayoutEngineContract.md) — control plane
- [Phase Model](../../contracts/PHASE_MODEL.md) — phase taxonomy
- [Phase 6A Overview](Phase6A-Overview.md) — deferral of MPEG-TS
- [Contract Hygiene Checklist](../../standards/contract-hygiene.md) — authoring guidelines
