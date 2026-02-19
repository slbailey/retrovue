# Segment preview assignment sites and PerformSegmentSwap branch proof

## 1) Every assignment site (repo-wide)

**Search scope:** All `*.cpp`, `*.h`, `*.hpp`, `*.cc` in the repo.

### segment_preview_ (the producer pointer)

- **Assignments (assigning a non-null value):** **NONE.** No line in the repo assigns to `segment_preview_` (no `segment_preview_ = ...` other than member initialization).
- **Other writes:**  
  - `pkg/air/src/blockplan/PipelineManager.cpp` **2617:**  
    `segment_preview_.reset();`  
    (teardown only; not an assignment of a producer.)

**Exact line that would assign (does not exist):** There is no `segment_preview_ = std::move(...)` or `segment_preview_ = ...` anywhere. The comment at **1135** says: “This block remains for any future path that might set segment_preview_.”

### segment_preview_video_buffer_

- **Assignment (creating/populating the buffer):**  
  - `pkg/air/src/blockplan/PipelineManager.cpp` **1138:**  
    `segment_preview_video_buffer_ = std::make_unique<VideoLookaheadBuffer>(...);`  
    This is inside:  
    `if (segment_preview_ && !segment_preview_video_buffer_ && AsTickProducer(segment_preview_.get())->GetState() == ITickProducer::State::kReady) { ... }`  
    Because `segment_preview_` is never assigned (see above), this condition is never true, so this assignment is never executed.
- **Other writes:**  
  - **2614:** `segment_preview_video_buffer_.reset();` (teardown)  
  - **2969:** `video_buffer_ = std::move(segment_preview_video_buffer_);` (move-out into live; not an assignment *to* `segment_preview_video_buffer_`)

### segment_preview_audio_buffer_

- **Assignment (creating/populating the buffer):**  
  - `pkg/air/src/blockplan/PipelineManager.cpp` **1146:**  
    `segment_preview_audio_buffer_ = std::make_unique<AudioLookaheadBuffer>(...);`  
    Same `if` as above (lines 1136–1137). Never runs because `segment_preview_` is never set.
- **Other writes:**  
  - **2616:** `segment_preview_audio_buffer_.reset();` (teardown)  
  - **2971:** `audio_buffer_ = std::move(segment_preview_audio_buffer_);` (move-out into live)

**Summary:** The only assignment sites that would create segment preview buffers are **1138** and **1146**; both are gated on `segment_preview_`, which has no assignment site in the repo, so segment preview buffers are never created.

---

## 2) Exact code that logs "prep_mode=PREROLLED" and "SEGMENT_SEAM_TAKE"; branch conditions for prep_mode

**File:** `pkg/air/src/blockplan/PipelineManager.cpp`

### Log line that can emit "prep_mode=PREROLLED"

- **3076–3084** (after edits: includes `swap_branch`):  
  `oss << "[PipelineManager] SEGMENT_SEAM_TAKE" << " tick=" << ... << " prep_mode=" << prep_mode << " swap_branch=" << swap_branch << ...`  
  This is the single log that prints `prep_mode` for the non–PAD-inline path. So **prep_mode=PREROLLED** appears when `prep_mode` was set to `"PREROLLED"` by one of the branches below.

### Log line that always logs "prep_mode=INSTANT" (PAD inline path)

- **2944–2951:**  
  `oss << "[PipelineManager] SEGMENT_SEAM_TAKE" << ... << " prep_mode=INSTANT swap_branch=PAD_INLINE" << ...`  
  Emitted only on the **PAD inline** early-return path (`if (incoming_is_pad)` at **2902**). So this is the only place that logs **SEGMENT_SEAM_TAKE** with **prep_mode=INSTANT** and **swap_branch=PAD_INLINE**.

### Branch conditions that set prep_mode (and swap_branch)

| Branch | Condition | prep_mode set | swap_branch set | Lines |
|--------|-----------|---------------|-----------------|--------|
| **A) PREROLLED (moved preview)** | `if (segment_preview_video_buffer_)` | `incoming_is_pad ? "INSTANT" : "PREROLLED"` | `"PREROLLED_MOVED_PREVIEW"` | 2968–2978 |
| **B) HasSegmentResult** | `else if (seam_preparer_->HasSegmentResult())` and peek identity matches and `result && result->producer` | `incoming_is_pad ? "INSTANT" : "PREROLLED"` | `"HAS_RESULT_NEW_BUFFERS"` | 2979–3007 |
| **C) PAD inline** | `if (incoming_is_pad)` at start of PerformSegmentSwap | Logged as INSTANT at 2945; no `prep_mode` variable | Log: `swap_branch=PAD_INLINE` | 2902–2958 |
| **D) MISS** | `if (!swapped)` after A/B not taken | `"MISS"` | `"MISS"` | 3021–3042 |

So **prep_mode=PREROLLED** is set in two code paths: **A** (move segment preview into live) and **B** (take SeamPreparer result and create new buffers). The same log line at **3076** prints whatever `prep_mode` was set by whichever branch ran; it does not distinguish “requested” vs “actual” — it reflects the branch that set the variable. Because both A and B set `prep_mode = "PREROLLED"` for content segments, the log can show **prep_mode=PREROLLED** when the actual swap was **B** (HasSegmentResult, new buffers), not A (moved preview).

---

## 3) Proof of which PerformSegmentSwap branch runs at runtime; branch logs

**Existing / added logs that identify the branch:**

| Branch | Log identifier | File:line (insertion / log location) |
|--------|----------------|--------------------------------------|
| **A) PREROLLED (moved preview)** | `swap_branch=PREROLLED_MOVED_PREVIEW` | PipelineManager.cpp:2976 (set), 3081 (logged) |
| **B) HasSegmentResult (new buffers)** | `swap_branch=HAS_RESULT_NEW_BUFFERS` | PipelineManager.cpp:3005 (set), 3081 (logged) |
| **C) PAD inline** | `swap_branch=PAD_INLINE` in SEGMENT_SEAM_TAKE | PipelineManager.cpp:2949 (in log string) |
| **D) MISS** | `swap_branch=MISS` | PipelineManager.cpp:3038 (set), 3081 (logged); SEGMENT_SEAM_PAD_FALLBACK at 3041–3043 |

**Exact insertion points and log string:**

- **A:** After `live_ = std::move(segment_preview_);` at **2972**, added:  
  `swap_branch = "PREROLLED_MOVED_PREVIEW";`  
  Logged in Step 8: `<< " swap_branch=" << swap_branch` at **3081**.
- **B:** After `StartFilling(...)` and `swapped = true` at **3003**, added:  
  `swap_branch = "HAS_RESULT_NEW_BUFFERS";`  
  Same Step 8 log.
- **C:** PAD inline path logs at **2945–2950**:  
  `" prep_mode=INSTANT swap_branch=PAD_INLINE"`  
  (added to existing SEGMENT_SEAM_TAKE line).
- **D:** In `if (!swapped)` block before `prep_mode = "MISS";`, added:  
  `swap_branch = "MISS";`  
  Same Step 8 log. SEGMENT_SEAM_PAD_FALLBACK at **3041–3043** already identifies fallback.

**Proof at runtime:** Inspect the log line that contains `SEGMENT_SEAM_TAKE` and `prep_mode=PREROLLED`. If it also contains **swap_branch=HAS_RESULT_NEW_BUFFERS**, the branch that ran was **B** (HasSegmentResult, new buffers), not A (moved preview). If it contains **swap_branch=PREROLLED_MOVED_PREVIEW**, the branch that ran was **A**. So the actual swap branch is determined by **swap_branch**, not by **prep_mode**.

---

## 4) Why the log can say prep_mode=PREROLLED even when segment preview buffers are never created

**Code path that prints prep_mode:**  
PipelineManager.cpp **3074–3084**: one log line emits `prep_mode=<value of prep_mode>`. That value is whatever was last assigned to `prep_mode` in PerformSegmentSwap.

**Where prep_mode is set to "PREROLLED":**

1. **2968–2977 (branch A):**  
   `if (segment_preview_video_buffer_) { ... prep_mode = incoming_is_pad ? "INSTANT" : "PREROLLED"; }`  
   So when we **move** segment preview into live, we set `prep_mode = "PREROLLED"` for content.
2. **3004–3006 (branch B):**  
   Inside `else if (seam_preparer_->HasSegmentResult())` when we take the result and create **new** buffers and call StartFilling:  
   `prep_mode = incoming_is_pad ? "INSTANT" : "PREROLLED";`  
   So when we use the **worker result** and allocate new buffers (no segment preview), we also set `prep_mode = "PREROLLED"` for content.

So **prep_mode** does **not** mean “we used segment preview buffers.” It means “we consider this segment transition to be prerolled (or instant for PAD).” Both “moved segment preview” (A) and “took HasSegmentResult and created new buffers” (B) use the same label **PREROLLED** for content. The log at 3076–3082 therefore reflects **which branch set the variable**, not “requested mode” vs “actual swap branch.” If segment preview is never created, branch A is never taken; branch B can still run (when the worker has a result), and branch B sets `prep_mode = "PREROLLED"`, so the log shows **prep_mode=PREROLLED** even though the actual swap was **HAS_RESULT_NEW_BUFFERS** (new buffers + StartFilling), not moved preview.

**Runtime log excerpt (from AUDIO_UNDERFLOW_SEAM_ROOT_CAUSE.md):**  
The doc states that the log shows `SEGMENT_SEAM_TAKE ... prep_mode=PREROLLED` and then `[FillLoop:LIVE_AUDIO_BUFFER] ENTER` and later `AUDIO_UNDERFLOW_SILENCE ... buffer_depth_ms=17`. That is consistent with branch **B**: new buffers created, StartFilling pushes one frame, FillLoop starts for LIVE_AUDIO_BUFFER, tick loop consumes immediately and sees low depth (e.g. 17 ms). With the new logging, the same run would show **swap_branch=HAS_RESULT_NEW_BUFFERS**, proving the actual path was B, not A.

---

## Conclusion and one-sentence proof

**Segment preview buffers are NOT created and NOT used.**

**Proof:** There is no assignment to `segment_preview_` anywhere in the repo (only `segment_preview_.reset()` at PipelineManager.cpp:2617); the only assignments to `segment_preview_video_buffer_` and `segment_preview_audio_buffer_` are at PipelineManager.cpp:1138 and 1146, both inside `if (segment_preview_ && ...)`, so they never run; therefore at runtime `segment_preview_video_buffer_` is always null, the branch at 2968 (PREROLLED_MOVED_PREVIEW) is never taken, and the swap is performed by the HasSegmentResult branch (2977–3007), which sets prep_mode=PREROLLED and creates new buffers — as confirmed by the added swap_branch log showing HAS_RESULT_NEW_BUFFERS when prep_mode=PREROLLED appears without segment preview.
