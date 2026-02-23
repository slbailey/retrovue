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

### Phase 2 – <span style="color:#61afef">Structural Audio/Video Decoupling</span> <small>(In Progress)</small>

#### Phase 2A – <b>Packet-Level Decode Control</b>

Introduce:

