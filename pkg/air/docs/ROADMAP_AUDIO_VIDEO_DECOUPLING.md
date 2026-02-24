<div align="center">

# <img src="https://emojicdn.elk.sh/🎼🎞️" width="36" style="vertical-align:middle;"> Audio/Video Decoupling Roadmap

<em>Last updated: 2026-02-22</em>

---

</div>

## ✨ Executive Goal

**Make <span style="color:#3a6ea5">audio liveness</span> structurally independent of:**

- <span style="color:#c678dd">Video cadence</span> <small>(repeat / skip)</small>
- <span style="color:#c678dd">Video backpressure</span> <small>(buffer full / lookahead full)</small>
- <span style="color:#c678dd">Presentation timing</span> <small>(TickLoop output rate)</small>

> <b>Audio must remain continuous and stable—even when video advancement is throttled, repeated, or stalled.</b>

This document summarizes the vision, architecture, and rollout path for proper decoupling.  
*Let’s never regress into coupling bugs again.*

---

## 🕰️ Root Problem (Historical)

Historically, **audio production was coupled to video decode and advancement**.

<details>
<summary><b>Symptoms included:</b></summary>

- 🔇 Audio starvation when video buffer filled
- 🚰 Audio bursts after video stalls
- 🦿 Burst thresholds / boost logic creeping in
- 🤫 Silence padding for compensation
- ⏩ Over-decoding during upsampling (e.g., 23.976 → 29.97)
- 🧐 Hard-to-reason timing behavior
</details>

**The architectural flaw:**

> Decoder execution was <u>implicitly driven</u> by video advancement and buffer state.

**We are eliminating that.**

---

## 🧭 Architectural Principle

### Separation of Responsibilities

<details open>
<summary><b>• <span style="color:#e06c75">FillLoop</span> <small>(Producer Layer)</small></b></summary>

- Decodes and maintains buffer health.
- <u>Driven by:</u>
    - Audio buffer depth
    - Video lookahead health
- <span style="color:#d19a66">NOT</span> driven by presentation cadence.
- Must decode audio packets even when video cannot advance.
</details>

<details open>
<summary><b>• <span style="color:#98c379">TickLoop</span> <small>(Presentation Layer)</small></b></summary>

- Runs at output cadence (e.g., 29.97fps).
- Decides:
    - Repeat last video frame
    - Advance to next frame
- <b>Repeats must NOT pop video buffer.</b>
- Video cadence logic belongs here—not in FillLoop.
</details>

<details open>
<summary><b>• <span style="color:#56b6c2">Decoder Layer</span> <small>(Packet Level)</small></b></summary>

- Operates at packet granularity.
- Audio packet processing must <b>not</b> require video advancement.
- Should support:
    - <code>PumpDecoderOnce()</code>
    - Deferred video packet handling
    - (Future) <code>DrainAudioOnly</code> mode
</details>

---

## 🚦 Phase Roadmap

---

### Phase 1 – <span style="color:#be5046">Stabilization</span> <small>(Historical / Complete)</small>

**Goal:**  
Prevent catastrophic audio starvation.

*Techniques introduced:*
- Audio depth thresholds
- Bootstrap gating
- Burst thresholds
- Silence padding
- Hysteresis logic

**Status:**  
Functional but compensatory.  
*Not architecturally clean.*

---

#### Incident: Post-fence video lookahead underflow (2026-02-22)

**Log:** `pkg/air/logs/cheers-24-7-air.log`

**Observed:**

1. **PREROLL_OWNERSHIP_VIOLATION** at fence tick 4161: expected next block `blk-e35a0f020482`, actual `blk-1f042ade1207` (session block_b). Preroll had armed fed blocks; the block actually taken was the session’s initial block_b — a queue vs session ordering mismatch (diagnostic only; correct block was played).
2. **TICK_GAP** from ~tick 5168: inter-frame gaps 50–603 ms (tick loop or system late).
3. **INV-VIDEO-LOOKAHEAD-001: UNDERFLOW** at frame 5942: `buffer_depth=0`, `total_pushed=1781`, `total_popped=1781`. Post-fence buffer was filled by the fill thread for block `blk-1f042ade1207`; exactly 1781 frames were pushed and consumed (~59 s at 30 fps). Decode ran at ~real-time, so the buffer never built headroom; a small stall drained it and triggered underflow.

**Hypothesis:** Decode rate matched consumption (no headroom). With default lookahead depth ~0.5 s (15 frames), any brief stall (TICK_GAP) led to underflow.

**Mitigations applied:**

- Default video lookahead target depth increased from ~0.5 s to ~1 s at output FPS (e.g. 30 frames at 30 fps) so decode can build headroom when it barely keeps up.
- UNDERFLOW log extended with `low_water` and `target` for diagnostics.
- Post-fence buffer creation (fallback swap and PADDED_GAP) uses the same config as session start so headroom is consistent.

---

### Phase 2 – <span style="color:#61afef">Structural Audio/Video Decoupling</span> <small>(In Progress)</small>

#### Phase 2A – <b>Packet-Level Decode Control</b>

Introduce:

