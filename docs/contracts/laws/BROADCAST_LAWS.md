# Layer 0 - Broadcast Laws

**Status:** Canonical
**Scope:** Constitutional guarantees that cannot be overridden by contracts
**Authority:** Supreme - all contracts must conform to these laws

---

## Authority Hierarchy (Supreme)

| Rule ID | Classification | Owner | Enforcement | Test | Log |
|---------|---------------|-------|-------------|------|-----|
| **LAW-AUTHORITY-HIERARCHY** | LAW | System | ARCHITECTURE | No | No |

| Rule ID | One-Line Definition |
|---------|---------------------|
| LAW-AUTHORITY-HIERARCHY | **Clock authority supersedes frame completion for switch execution.** Clock (LAW-CLOCK) decides WHEN transitions occur. Frame boundary (LAW-FRAME-EXECUTION) decides HOW precisely cuts happen. Frame count (INV-SEGMENT-CONTENT-001) decides WHETHER content is sufficient, but clock does not wait for frame completion. |

**Rationale:** This hierarchy resolves the apparent contradiction between clock-based and frame-based rules. Without this hierarchy, code may incorrectly wait for frame completion before executing a clock-scheduled transition, causing the exact boundary timing violations observed in production.

---

## Core Laws

| Rule ID | Classification | Owner | Enforcement | Test | Log |
|---------|---------------|-------|-------------|------|-----|
| **LAW-CLOCK** | LAW | AIR | RUNTIME | Yes | No |
| **LAW-TIMELINE** | LAW | AIR | P8 | Yes | No |
| **LAW-OUTPUT-LIVENESS** | LAW | AIR | RUNTIME | Yes | Yes |
| **LAW-AUDIO-FORMAT** | LAW | AIR | INIT | No | No |
| **LAW-SWITCHING** | LAW | AIR | P8 | Yes | Yes |
| **LAW-VIDEO-DECODABILITY** | LAW | AIR | RUNTIME | Yes | Yes |
| **LAW-TS-DISCOVERABILITY** | LAW | MpegTSOutputSink | RUNTIME | No | Yes |
| **LAW-FRAME-EXECUTION** | CONTRACT | AIR | P10 | No | No |
| **LAW-RUNTIME-AUDIO-AUTHORITY** | LAW | AIR (PlayoutEngine) | RUNTIME | No | Yes |

---

## Law Definitions

### LAW-CLOCK
**MasterClock is the only source of "now"; CT never resets once established.**

- No component other than MasterClock may define or supply wall-clock "now" for playout decisions.
- Pacing, scheduling, and deadline checks use MasterClock (or values derived from it).
- Epoch is established once per session and is immutable.
- CT advances monotonically for the lifetime of the session.
- CT does not wrap, jump backward, or reset on segment switch.

Source: PlayoutInvariants-BroadcastGradeGuarantees.md §1

---

### LAW-TIMELINE
**TimelineController owns CT mapping; producers are time-blind after lock.**

- Only TimelineController assigns CT to frames.
- Producers emit media time (MT) only; CT appears only after admission.
- Segment boundaries are defined by TimelineController.
- First admitted frame in a segment locks both CT_start and MT_start.
- Once TimelineController is active and segment mapping is locked, producers do not make timing or sequencing decisions.

Source: PlayoutInvariants-BroadcastGradeGuarantees.md §2

---

### LAW-OUTPUT-LIVENESS
**ProgramOutput never blocks; if no content -> deterministic pad (black + silence).**

- The output path from buffer to OutputBus/OutputSink must not deadlock.
- ProgramOutput consumes the active buffer and delivers frames (or deterministic pad) to the sink.
- Blocking the output thread is forbidden.
- When the live producer has no frames, the sink must still receive valid output.
- Silence is emitted in the channel's house audio format.
- No gaps, no freezes, no invalid data.

Source: PlayoutInvariants-BroadcastGradeGuarantees.md §3

---

### LAW-AUDIO-FORMAT
**Channel defines house format; all audio normalized before OutputBus; EncoderPipeline never negotiates.**

- The channel's program format (sample rate, channel layout, sample format) is the single source of truth for audio.
- It is established at session start and does not change for the lifetime of the session.
- All audio delivered to the output path conforms to this house format.
- OutputBus and downstream components assume normalized input; they do not resample or reformat per-stream.
- EncoderPipeline does not discover, negotiate, or adapt to arbitrary input formats.

Source: PlayoutInvariants-BroadcastGradeGuarantees.md §4

---

### LAW-SWITCHING
**No gaps, no PTS regression, no silence during switches. Transitions MUST complete within one video frame duration of scheduled absolute boundary time.**

- **No gaps:** The output stream has no missing frames or packets at the switch boundary.
- **No PTS regression:** PTS/DTS never decrease across the switch.
- **No silence during switches:** The switch is seamless at the frame boundary.
- Switching is Core-commanded (SwitchToLive). AIR executes switches; AIR does not decide whether to switch.
- AIR does not switch autonomously except dead-man fallback (safety rail, not editorial decision).

Source: PlayoutInvariants-BroadcastGradeGuarantees.md §5

---

### LAW-VIDEO-DECODABILITY
**Every segment starts with IDR; real content gates pad; AIR owns keyframes.**

- AIR is responsible for media decodability: keyframes, SPS/PPS, IDR presence.
- CORE is NOT responsible for keyframes.
- Safety rails (pad/black frames) are NOT a continuity mechanism for decodability.
- AIR must not emit any video packets for a segment until an IDR frame has been produced.

Source: PlayoutInvariants-BroadcastGradeGuarantees.md §6

---

### LAW-FRAME-EXECUTION
**Frame index governs execution precision (HOW cuts happen), not transition timing (WHEN cuts happen). CT derives from frame index within a segment. Does not override LAW-CLOCK for switch timing.**

- Playout execution is frame-addressed.
- Segments are bounded by frame counts, not durations.
- CT is derived from frame index, never the inverse.
- This enables frame-accurate editorial cuts and deterministic padding.

Source: PlayoutInvariants-BroadcastGradeGuarantees.md §7 (Subordinate to LAW-AUTHORITY-HIERARCHY)

---

### LAW-RUNTIME-AUDIO-AUTHORITY
**When producer_audio_authoritative=true, producer MUST emit audio >=90% of nominal rate, or mode auto-downgrades to silence-injection.**

Source: Incident 2026-02-01

---

## Transport Stream Discoverability Law

| Rule ID | Classification | Owner | Enforcement | Test | Log |
|---------|---------------|-------|-------------|------|-----|
| **LAW-TS-DISCOVERABILITY** | LAW | MpegTSOutputSink | RUNTIME | No | Yes |

### LAW-TS-DISCOVERABILITY
**A transport stream MUST be self-describing to any observer that attaches at an arbitrary wall-clock time.**

A late-joining viewer tuning into an active channel MUST be able to decode the stream without having witnessed stream initialization. This is a **coordination guarantee**, not a codec requirement.

---

#### Derivation from LAW-OUTPUT-LIVENESS

**This law is a DOWNSTREAM CONSEQUENCE of LAW-OUTPUT-LIVENESS, not an independent enforcement target.**

If LAW-OUTPUT-LIVENESS is satisfied (continuous TS bytes emitted via pad when no content):
- FFmpeg's `resend_headers+pat_pmt_at_frames` flags cause PAT/PMT to be emitted with each video frame
- Since pads are emitted continuously, PAT/PMT are emitted continuously
- TS discoverability is satisfied automatically

If LAW-OUTPUT-LIVENESS is violated (no TS bytes for ≥500ms):
- No mechanism exists to emit PAT/PMT independently of media frames (FFmpeg limitation)
- TS discoverability is necessarily violated as a downstream consequence
- The root cause is the liveness violation, not a separate discoverability failure

**Therefore:** Discoverability is not independently enforceable. It is a property that emerges from output liveness compliance.

---

#### Classification: Control-Plane vs Media

| Category | Examples | Pacing Authority | May Be Gated By CT |
|----------|----------|------------------|-------------------|
| **Control-Plane** | PAT, PMT, SDT, NIT | Wall clock (bounded cadence) | **NO** |
| **Media** | Video PES, Audio PES | CT (frame timing) | Yes |

**PAT/PMT are control-plane, not media.** They describe stream structure, not stream content. However, in FFmpeg's mpegts muxer, control-plane emission is coupled to media frame writes — there is no independent control-plane heartbeat API.

---

#### Definitions

| Term | Definition |
|------|------------|
| **Emitted** | Bytes containing PAT (PID 0x0000) or PMT (PID from PAT) are observed leaving the sink — i.e., after the muxer → `WriteToFdCallback` → `SocketSink` boundary. "Scheduled", "eligible", or "queued internally by FFmpeg" do not count as emitted. |
| **Wall time** | `std::chrono::steady_clock` — the same clock used for CT pacing and deadline enforcement (LAW-CLOCK). NOT media time, NOT CT, NOT system clock. |
| **Sliding window** | At any wall-time T, the invariant is evaluated over the interval (T−500ms, T]. Not epoch-aligned, not periodic sampling. |

---

#### Formal Guarantees

1. **Periodic Table Emission:** PAT and PMT MUST be emitted periodically throughout the stream, not just at stream start. This is achieved via FFmpeg's `resend_headers+pat_pmt_at_frames` muxer flags.

2. **Bounded Discovery Time (Sliding Window):** At any wall-time T, there MUST exist a PAT and PMT **emitted** (per definition above) in the interval (T−500ms, T]. This is a continuous guarantee, not a periodic check.

3. **Liveness Dependency:** PAT/PMT emission is coupled to video frame writes. If TS bytes are not flowing (LAW-OUTPUT-LIVENESS violation), PAT/PMT cannot flow either. This is a muxer architectural constraint, not a RetroVue design choice.

---

#### Rationale

RetroVue is not a file generator or one-shot encoder. It is a **continuously observable broadcast universe**. In such a universe:
- Time must be authoritative (LAW-CLOCK)
- Output must be live (LAW-OUTPUT-LIVENESS)
- Content must be decodable (LAW-VIDEO-DECODABILITY)
- **Structure must be discoverable (this law)**

PAT/PMT is *structure*, not *data*. A stream that is "live" and "decodable" but not "discoverable" is useless to late-joiners. Since FFmpeg couples control-plane to media, the ONLY way to guarantee discoverability is to guarantee output liveness.

---

#### Anti-Patterns

| Pattern | Why It Fails |
|---------|--------------|
| PAT/PMT only at `avformat_write_header()` | Late-joiners never see structure |
| PAT/PMT only with keyframes | GOP-length stalls (2+ seconds) |
| Independent PAT/PMT enforcement via `av_write_frame(nullptr)` | FFmpeg does not emit PAT/PMT on null flush — this is a non-op |
| Raw socket writes bypassing muxer | FFmpeg's resend_headers state not triggered |

#### Correct Pattern

1. Configure muxer for periodic resend:
   ```cpp
   av_dict_set(&muxer_opts_, "mpegts_flags", "resend_headers+pat_pmt_at_frames", 0);
   ```

2. Ensure LAW-OUTPUT-LIVENESS compliance: continuous pad emission when no content ensures continuous PAT/PMT emission as a downstream consequence.

3. Detect violations: if TS emission stalls for ≥500ms, log a LAW-OUTPUT-LIVENESS violation. The discoverability failure is a symptom, not the root cause.

---

#### Subordinate Invariant

See: **INV-TS-CONTROL-PLANE-CADENCE** — detects 500ms emission gaps and logs LAW-OUTPUT-LIVENESS violations. This is a **detector**, not an enforcer — there is no independent enforcement path for control-plane cadence.

---

Source: Late-joiner incident 2026-02-04; Phase 10 compliance audit 2026-02-04; FFmpeg API analysis 2026-02-04

---

## Observability Laws

| Rule ID | Classification | Owner | Enforcement | Test | Log |
|---------|---------------|-------|-------------|------|-----|
| **LAW-OBS-001** | LAW | AIR | RUNTIME | No | Yes |
| **LAW-OBS-002** | LAW | AIR | RUNTIME | No | Yes |
| **LAW-OBS-003** | LAW | AIR | RUNTIME | No | Yes |
| **LAW-OBS-004** | LAW | AIR | RUNTIME | No | Yes |
| **LAW-OBS-005** | LAW | AIR | RUNTIME | No | Yes |

| Rule ID | One-Line Definition |
|---------|---------------------|
| LAW-OBS-001 | Intent evidence - every significant action has intent log |
| LAW-OBS-002 | Correlation evidence - related events share correlation ID |
| LAW-OBS-003 | Result evidence - every action has outcome log |
| LAW-OBS-004 | Timing evidence - significant events have timestamps |
| LAW-OBS-005 | Boundary evidence - phase/state transitions are logged |

Source: ObservabilityParityLaw

---

## Authority Model (Canonical)

```
                    LAW-AUTHORITY-HIERARCHY
         "Clock authority supersedes frame completion"
                              |
        +---------------------+---------------------+
        |                     |                     |
        v                     v                     v
+---------------+    +---------------+    +---------------+
|   LAW-CLOCK   |    | LAW-SWITCHING |    |LAW-FRAME-EXEC |
|               |    |               |    |               |
| WHEN things   |    | WHEN switch   |    | HOW precisely |
| happen        |    | executes      |    | cuts happen   |
|               |    | (+/- 1 frame) |    |               |
| [AUTHORITY]   |    | [AUTHORITY]   |    | [EXECUTION]   |
+---------------+    +---------------+    +---------------+
                              |
                              v
                    +---------------+
                    |INV-SEGMENT-   |
                    |CONTENT-001    |
                    |               |
                    | WHETHER       |
                    | content is    |
                    | sufficient    |
                    |               |
                    | [VALIDATION]  |
                    | (clock does   |
                    |  not wait)    |
                    +---------------+
```

**Key Principle:** If frame completion and clock deadline conflict, clock wins. Frame-based rules describe *how to execute* within a segment, not *whether to execute* a scheduled transition.

**Anti-Pattern (BUG):** Code that waits for frame completion before executing a clock-scheduled switch.

**Correct Pattern:** Schedule switch at clock time. If content isn't ready, use safety rails (pad/silence). Never delay the clock.

---

## Derivation Notes

| Contract | Derives From | Relationship |
|----------|--------------|--------------|
| INV-P8-001 | LAW-TIMELINE §1 | **Alias** - "only TimelineController assigns CT" restates law |
| INV-P8-005 | LAW-CLOCK §2 | **Alias** - "epoch unchanged until session end" restates law |
| INV-P8-006 | LAW-TIMELINE §2 | **Alias** - "producers do not read/compute CT" restates "time-blind after lock" |
| INV-P8-OUTPUT-001 | LAW-OUTPUT-LIVENESS | **Refines** - adds "explicit flush, bounded delivery" to liveness guarantee |
| INV-AUDIO-HOUSE-FORMAT-001 | LAW-AUDIO-FORMAT | **Test obligation** - contract test verifying the law |
| INV-STARVATION-FAILSAFE-001 | LAW-OUTPUT-LIVENESS | **Operationalizes** - defines bounded time for pad emission |
| LAW-RUNTIME-AUDIO-AUTHORITY | LAW-AUDIO-FORMAT | **Operationalizes** - defines producer-authoritative mode enforcement |
| LAW-FRAME-EXECUTION | LAW-AUTHORITY-HIERARCHY | **Subordinate** - governs execution precision (HOW), not transition timing (WHEN) |

---

## Cross-References

- [CANONICAL_RULE_LEDGER.md](../CANONICAL_RULE_LEDGER.md) - Single source of truth for all rules
- [PHASE8_SEMANTICS.md](../semantics/PHASE8_SEMANTICS.md) - Phase 8 semantic invariants
- [BROADCAST_CONSTITUTION.MD](../../architecture/BROADCAST_CONSTITUTION.MD) - Architectural principles
