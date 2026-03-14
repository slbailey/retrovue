# Runtime Assessment: “Emit PAD and Do Not Pop When Ahead”

**Contract:** [frame_selection_alignment.md](../contracts/playout/frame_selection_alignment.md)  
**Behavior:** When `front.source_frame_index > selected_src`, the pipeline emits PAD and does not pop. That satisfies the invariant `actual_src_emitted <= selected_src` but can produce black frames until the scheduler catches up.

**Log source:** `pkg/air/logs/hbo-air.log` (latest run).

---

## 1. How often is the ahead-of-scheduler path taken?

**From current logs: not measurable.**

- INV-HANDOFF-DIAG runs only for **tick < 300** and only when decision is ContentA/ContentB/Repeat. When we emit PAD (ahead path), we do not update `last_good_source_frame_index_`, so that tick is not reported in INV-HANDOFF-DIAG.
- There is **no dedicated log** for “we took the ahead path” in the run analyzed. So we cannot count how often `front > selected_src` occurred.

**Evidence from first 300 ticks:**

- **frame_gap = actual_src_emitted − selected_src:** All observed values are **0 or negative** (28 negative, rest zero). There are **zero** positive frame_gap entries, so in the first 300 ticks we never had `actual_src_emitted > selected_src` (no violation; either the fix is in place or the queue was never ahead in that window).

**To measure in future runs:** A rate-limited diagnostic was added. When the ahead path is taken, the pipeline logs:

`[PipelineManager] FRAME_ALIGNMENT_AHEAD_PAD tick=... selected_src=... front_index=... (emit PAD, do not pop; queue realigns when scheduler catches up)`

at most once per 60 ticks. Count these lines (and optionally multiply by 60 for a conservative upper bound on ahead-path ticks) to answer “how often.”

---

## 2. Does it produce repeated PAD ticks?

**By design, yes.** When the queue is ahead:

- We do not pop, so the front frame index does not change.
- The scheduler advances every tick, so `selected_src` increases.
- We emit PAD each tick until `selected_src` catches up to `front`. So we get a **run of PAD ticks** of length `front − selected_src` (when we first enter the ahead state).

**From current logs:** TAKE_PAD_ENTER/TAKE_PAD_EXIT mark any PAD interval (startup, underflow, segment seam, or ahead path). There are 524 such transitions in the run, but we cannot attribute which are from the ahead path. The new FRAME_ALIGNMENT_AHEAD_PAD log will let you correlate PAD runs with “queue ahead” in future runs.

---

## 3. Does the queue ever realign on its own after entering the ahead state?

**Yes.** Realignment is implicit and requires no extra logic:

- We **do not pop** when `front > selected_src`, so the queue head stays at the same source index.
- The **scheduler advances** every tick, so `selected_src` increases by 0 or 1 each tick (cadence).
- After `selected_src` reaches the current `front`, the next tick has `front == selected_src`, we pop, and we resume emitting content. So the queue realigns when the scheduler catches up; no discard or reset is required.

---

## 4. Do black frames / pauses increase after this change?

**Not determinable from this run alone.**

- We do not have a like-for-like run (same channel, same wall time) **without** the “emit PAD when ahead” behavior to compare.
- The run shows **28 “behind” events** (frame_gap &lt; 0, DRIFT_DETECTED) in the first 300 ticks: we repeated the previous frame because the buffer did not yet have the next one. So the dominant misalignment in this run is **decoder behind**, not decoder ahead.
- If the ahead path were taken often, we would see more black (PAD) ticks; the new FRAME_ALIGNMENT_AHEAD_PAD log will allow you to quantify that in future runs.

---

## Summary and recommendation

| Question | Answer from logs | How to improve |
|----------|------------------|-----------------|
| How often is the ahead path taken? | Not measurable (no dedicated log in this run). | Use `FRAME_ALIGNMENT_AHEAD_PAD` count (rate-limited) in future runs. |
| Repeated PAD ticks? | By design, yes, for `(front − selected_src)` ticks when ahead. | Correlate TAKE_PAD_ENTER/EXIT with FRAME_ALIGNMENT_AHEAD_PAD to see run length. |
| Queue realigns on its own? | Yes: scheduler advances, we don’t pop, so we realign when `selected_src` catches up. | No change needed. |
| More black/pauses after change? | Cannot compare; no baseline. Dominant signal in first 300 ticks is “behind” (repeat), not “ahead.” | Re-run with the new diagnostic and compare PAD run length and frequency. |

**Operational takeaway:** “Emit PAD and do not pop when ahead” is **correct** with respect to the contract and **self-correcting** (realignment when the scheduler catches up). To decide if it is **acceptable** (e.g. whether prolonged black is rare or frequent), use the next run and:

1. Count `FRAME_ALIGNMENT_AHEAD_PAD` lines (and approximate ahead-path ticks from the 60-tick rate limit).
2. Inspect TAKE_PAD_ENTER/EXIT runs that coincide with those ticks to see duration of black.
3. If prolonged black is common, consider a **deliberate realignment strategy** (e.g. discard frames until `front == selected_src` so we resume content sooner, at the cost of skipping content; that would need a product decision).

No change to the contract or tests; the new diagnostic is for assessment only.

---

## Evidence collection: correlate black-frame events with PAD cause

**Goal:** Prove whether intermittent black frames come from the **ahead-of-scheduler** PAD path or from another PAD/underflow/transition path.

### 1. Run a failing title

1. Start the channel that exhibits intermittent black (e.g. HBO or the channel whose log is `pkg/air/logs/<channel>-air.log`).
2. From repo root, start Core so it launches AIR for that channel, e.g.:
   ```bash
   source pkg/core/.venv/bin/activate
   retrovue start   # or your normal start command; ensure the failing channel is tuned/active
   ```
3. Let playout run for at least a few minutes (or until you see a black flash if reproducible).
4. Stop the run. The AIR log is at `pkg/air/logs/<channel>-air.log` (e.g. `pkg/air/logs/hbo-air.log`).

### 2. Capture evidence with the script

From repo root:

```bash
python3 pkg/air/scripts/collect_pad_evidence.py pkg/air/logs/<channel>-air.log
```

Example for HBO:

```bash
python3 pkg/air/scripts/collect_pad_evidence.py pkg/air/logs/hbo-air.log
```

For CSV (e.g. for spreadsheets or further analysis):

```bash
python3 pkg/air/scripts/collect_pad_evidence.py pkg/air/logs/hbo-air.log --csv > pad_evidence.csv
```

### 3. Log lines extracted

| Category | Log pattern | Purpose |
|----------|-------------|---------|
| **PAD_CAUSE** | `[PipelineManager] PAD_CAUSE tick=... cause=...` | **One per pad/standby tick.** Explicit cause label so "other" is eliminated. |
| **FRAME_ALIGNMENT_AHEAD_PAD** | `[PipelineManager] FRAME_ALIGNMENT_AHEAD_PAD tick=... selected_src=... front_index=...` | Ahead-of-scheduler path (hold or PAD when no last frame). |
| **TAKE_PAD_ENTER** | `[PipelineManager] TAKE_PAD_ENTER tick=... slot=...` | Start of a PAD (black) interval. |
| **TAKE_PAD_EXIT** | `[PipelineManager] TAKE_PAD_EXIT tick=... slot=... block=...` | End of a PAD interval. |
| **INV-HANDOFF-DIAG** | `[PipelineManager] INV-HANDOFF-DIAG tick=... selected_src=... actual_src_emitted=... frame_gap=...` | Alignment diagnostic (first 300 ticks when content/repeat). |
| **Underflow** | `INV-VIDEO-LOOKAHEAD-001: UNDERFLOW`, `AUDIO_UNDERFLOW_SILENCE`, `SEAM_DEBUG_UNDERFLOW` | Video/audio underflow or seam underflow. |

**Cause attribution:** When the log contains **PAD_CAUSE**, the script uses that label per interval (dominant cause in the interval). Named causes:

- **block_transition** — Block fence; B not ready (preview/segment-b handoff miss).
- **segment_transition** — Segment seam to PAD segment or PAD at segment fade-in.
- **live_buffer_empty** — A not primed (buffer warming / no frame yet).
- **startup_bootstrap** — Very early PAD (tick ≤1), cadence repeat with no frame, or probe failed.
- **ahead_no_hold** — Queue ahead of scheduler and no last frame to hold (rare).
- **unknown_fallback** — No cause set in pipeline (fallback).

For **logs without PAD_CAUSE** (legacy), the script still infers: ahead_of_scheduler, underflow, startup, pad_seam, decoder_behind, and **unknown_fallback** (replaces "other (transition/empty)").

Use the report to rank the largest remaining operational source of pauses/freezes.

---

## Ahead-of-scheduler realignment: hold last frame (Option A)

**Problem:** When `front.source_frame_index > selected_src`, the previous strategy was “emit PAD and do not pop,” which caused user-visible black-frame bursts until the scheduler caught up.

**Chosen strategy: single-frame hold.** When the queue is ahead we **hold the last valid frame** (repeat) instead of emitting PAD, so long as we have a `last_good_video_frame_`. If we have none (e.g. very first content tick), we still emit PAD.

**Why this option:**
- **Option A (hold):** Smallest change; no buffer flush, no seek; invariant preserved (we do not emit a new frame with index > selected_src; we re-emit the last frame, whose index is already ≤ selected_src). Eliminates black from the ahead path.
- **Option B (controlled flush):** Would discard frames and then need to refill; risk of more PAD or complexity.
- **Option C (re-seek):** Requires producer seek by source index; larger change and side effects (keyframes, etc.).

**Invariant:** We do not pop, so `last_good_source_frame_index_` is unchanged and remains ≤ `selected_src_this_tick`. We emit that same frame again (decision = kRepeat). No future frame is ever emitted.

**Log:** The diagnostic still logs `FRAME_ALIGNMENT_AHEAD_PAD` with the note “(hold last frame; queue realigns when scheduler catches up).” Ticks on the ahead path no longer produce TAKE_PAD_ENTER (we emit Repeat, not PAD).

---

## Quantifying “other” PAD causes (rank for next mitigation)

The evidence script sub-classifies PAD intervals so we can rank causes after ahead-of-scheduler:

| Cause | Meaning |
|-------|--------|
| **ahead_of_scheduler** | Queue ahead; we hold/repeat (no longer PAD after Option A). |
| **underflow** | Video/audio/seam underflow. |
| **startup** | PAD at tick 0 (session start). |
| **pad_seam** | Segment switch to a PAD segment (PAD_SEAM_OVERRIDE in interval). |
| **decoder_behind** | At least one INV-HANDOFF-DIAG in the interval has frame_gap &lt; 0 (scheduler wanted a frame we didn’t have yet; repeat or PAD). |
| **Named causes (PAD_CAUSE)** | When the pipeline logs PAD_CAUSE, "other" is eliminated: each interval is labeled block_transition, segment_transition, live_buffer_empty, startup_bootstrap, ahead_no_hold, or unknown_fallback. |

Run the script and use the **Cause summary (PAD intervals)** section to see counts and rank the largest remaining operational source of pauses/freezes.
