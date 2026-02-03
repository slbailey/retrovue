# 📡 RetroVue Broadcast Constitution

**Status:** _Canonical_  
**Audience:** Humans designing, refactoring, or reviewing **RetroVue AIR**  
**Scope:** **WHAT** the system is — _not_ how it is implemented  
**Authority:** _Supreme_ — every contract, invariant, and line of code must conform

---

## 1. **Prime Directive**

> **RetroVue AIR is a continuous broadcast system — _not_ a media player.**

* The system _must_ emit decodable A/V at real-time cadence, forever, regardless of:
  - Content readiness
  - Decoder state
  - Viewer presence
  - Sink attachment timing

**When forced to choose:**

- _Wait for correctness_ **vs** _Maintain continuous output_  
  **Continuous output always wins.**

_Better:_ silence, black, or pad  
_Never:_ gaps, stalls, or undecodable streams

---

## 2. **Authority Hierarchy** _(Non-Negotiable)_

Lower layers **never** delay or override higher layers.

| Order                    | Role                                   |
|--------------------------|----------------------------------------|
| 1️⃣ Clock Authority      | **WHEN:** Wall clock is supreme        |
| 2️⃣ Timeline Authority   | **WHAT:** Program schedule             |
| 3️⃣ Execution Authority  | **HOW:** Frame cutting/emit            |
| 4️⃣ Content Availability | **Content exists?**                    |

### 2.1 **Clock Authority** (_Supreme_)  
* Wall clock is **absolute**.  
* Segments change _when the clock says so_ — not when frames are ready.  
* No subsystem may stall the clock.  
* _If content is unavailable:_ **Pad fills the gap.**

### 2.2 **Timeline Authority**  
* Timeline defines **what must be on-air every instant**
* Timeline is **continuous** and **monotonic**
* Decoder EOF ≠ segment end
* Segments end _only_ on schedule  
* Timeline **never waits for:**
  - Decoder
  - Buffer
  - Sink attachment
  - Viewer

### 2.3 **Execution Authority**  
* Dictates _how_ cuts happen (_frame precision_)
* Minor imperfections (_±1 frame_) are tolerated  
* Execution _never_ delays schedule
* Execution issues are absorbed _below_ (by pad)

### 2.4 **Content Availability** (_Subordinate_)  
* Content is _opportunistic_  
* Real frames override pad when ready  
* **Absence** must _never_ affect output cadence  
* **Content does **_not_** drive time**

---

## 3. **Continuous Emission Guarantee**

> **Once channel starts, system _must_ emit:**  
> - 1 video frame per frame period  
> - Continuous monotonic audio  
> - Decodable output packets

_This applies:_  
- Before real content exists  
- During seek, decode stalls, EOF, or switches  
- With zero viewers  
- When sinks attach late  
- **There is _no_ “nothing to output” state**

---

## 4. **Pad Is First-Class Content**

_pad = black video + silence audio_

- Not a fallback: **Pad is baseline content**

### 4.1 **Pad Properties**
  - House format, frame rate, sample rate, timing, encoder rules
  - Deterministic, infinitely generatable, always safe

### 4.2 **Pad Lifecycle**
  - Exists from channel start
  - Present before sinks, before decode, between EOF and segment boundary, during failures
  - Real content **overrides** pad when possible; pad resumes otherwise

---

## 5. **Component Responsibility Model**

> _Components are single-purpose and strictly separated._

### 5.1 **Producers** _(File/Pad/etc.)_
- Generate decoded frames
- **Time-blind**
- Unaware of sinks
- Do **not** pace clock or block output

### 5.2 **ProgramOutput**
- _Not_ a generator
- _Selects_ and _forwards_ frames, resolves pad/real, enforces cadence
- **Never invents or waits for content**
- If no frames: **Forwards pad**

### 5.3 **OutputBus**
- _Routes_ frames to sinks — not a buffer manager
- **No timing decisions, never blocks, does not require sink presence**
- Frame flow and sink attachment are _orthogonal_

### 5.4 **Output Sink (Muxer)**
- Encodes, muxes, emits bytes  
- **Never waits for frames, drives timing, invents content, or backpressures**  
- If late: **Emits pad**

---

## 6. **Sink Attachment Rule**

* Sink timing is **irrelevant** to broadcast correctness.
* Frames may flow before any sink exists.
* Sinks must attach _hot_
* **No behavior** may depend on “first sink attached”
* If sink attach causes:
    - Empty queues
    - Timing resets
    - Output delay  
  _**The architecture is wrong.**_

---

## 7. **Failure Philosophy**

### 7.1 **Absorbable Failures** _(Expected)_  
Handled transparently by pad:
- Decode stalls, EOF, short content, late switches, buffer starvation  
**_These are not errors._**

### 7.2 **Structural Failures** _(Fatal)_  
Require teardown:
- Clock regressions, monotonicity violations, PTS regression, format mismatch, authority inversion  
**_These stop the channel._**

---

## 8. **Observability Principle**

Violations _must_ be:
- Logged, attributed, correlated, timed

But:
- **Never block output**
- **Never gate the system**

> **Liveness over observability.**

---

## 9. **Anti-Patterns** <span style="color:#e53935"><b>FORBIDDEN</b></span>
_The following are unconstitutional:_

- “Wait until frames arrive”
- “Buffer until ready”
- “Don’t emit until sink attached”
- “Delay boundary because content not ready”
- “ProgramOutput generating frames”
- “Mux loop waiting on queues”

> If you see these in code:  
> _**THE CODE IS WRONG**_

---

## 10. **Amendment Process**

_Editable only if:_
- A real broadcast failure demands change
- Higher-level invariant clarifies intent
- It **reduces ambiguity** (not complexity)

**All changes _must_:**
- Preserve clock authority
- Preserve continuous emission
- Reduce conditional logic

---

## 11. **Closing Statement**

> RetroVue isn’t trying to be clever.  
> It’s designed to be _boringly correct_, always on, and unbreakable by timing.

> If the system ever hesitates, stalls, or waits:  
> **_The constitution is violated._**