# FPS/PTS normalization — multi-file validation runbook

**Status:** Validation in progress. Issue is **not** declared fixed until this pass is complete.

**Context:** 23.976 fps content on 29.97 fps sessions was playing ~1.25× fast with choppy audio. Fix: normalize all emitted frame PTS/duration to the house CT grid (INV-FPS-TICK-PTS) on every TickProducer path (primed, buffered, OFF/CADENCE/DROP). One successful case (Dreamscape) is encouraging but insufficient to close the bug.

**Goal:** Broader runtime confirmation across multiple files, including known-problem titles and a control, before marking resolved.

---

## 1. Diagnostics to keep enabled

Leave these in place for the validation pass:

| Log prefix | Source | Purpose |
|------------|--------|---------|
| `INV-FPS-TICK-PTS-DIAG` | TickProducer | source_pts_us vs emitted_pts_us, resample_mode |
| `INV-FPS-MUX-DIAG` | MpegTSOutputSink | video_pts_us, video_pts_90k, audio_samples_emitted |
| `INV-FPS-PACING-DIAG` | PipelineManager | tick_index, wall_clock_us, video_pts_us, delta_wall_us, delta_pts_us |
| **`INV-HANDOFF-DIAG`** | PipelineManager | **Source-frame selection (first 300 ticks ≈10s):** output_tick, selected_src, advance_or_repeat, actual_src_emitted, path. Use when stream plays OK at startup then speeds up. |
| **`INV-HANDOFF-SUMMARY`** | PipelineManager | **Per-window summary:** window (startup/transition/steady_state), tick_range, advance_count, repeat_count, unique_src_frames, expected_unique_24_30. Key: unique_src_frames must not track 1:1 with output ticks (would mean fast playback). |
| **`INV-HANDOFF-001`** | PipelineManager | **Invariant:** `actual_src_emitted == selected_src`. If violated, logs **Error** with output_tick, selected_src, actual_src_emitted, path. Catches source-frame misalignment (offset/gap) instantly. |

Expected for a 29.97 fps session:

- `delta_wall_us` ≈ 33366 µs
- `delta_pts_us` ≈ 33366 µs on advance ticks, 0 on repeat ticks
- `emitted_pts_us` steps ≈ 33366 µs (no ~41708 µs steps from 23.976 leakage)

---

## 2. Test matrix

Run each title as the first content segment in a 29.97 fps session (e.g. HBO or a single-asset test channel). Use the same session format (1280x720@29.97fps) for all.

### Required coverage

| Category | Count | Notes |
|----------|--------|------|
| Known-problem titles (previously played fast) | ≥ 2–3 | Prioritize these |
| 23.976 fps sources | As many as possible | Primary failure class |
| DTS audio | ≥ 1 if available | Part of original correlation |
| Control (previously known-good) | ≥ 1 | e.g. 29.97 native or already-validated file |

### Suggested titles (fill from your library)

- **Dreamscape (1984)** — 23.976, already validated once as OK after fix.
- **Other 23.976 problem titles:** _list 2–3 more_
- **DTS example:** _list one if available_
- **Control:** _e.g. filler or other 29.97 content that never misbehaved_

---

## 3. Per-title report

For **each** test title, record the following. Logs are in `pkg/air/logs/<channel>-air.log` for the run where that title was first content.

### Metadata (from ffprobe or first log lines)

| Field | Example |
|-------|--------|
| **Title** | Dreamscape (1984) |
| **Container** | mkv |
| **Video FPS** | 24000/1001 (23.976) |
| **Audio codec** | DTS, AC3, AAC, … |

### Subjective

| Field | Value |
|-------|--------|
| **Playback subjectively correct?** | Yes / No (fast, choppy, drift, etc.) |

### Log checks (from INV-FPS-PACING-DIAG and related)

| Check | How to verify |
|-------|----------------|
| **delta_wall_us ≈ 33366** | First ~120 INV-FPS-PACING-DIAG lines: delta_wall_us in 33000–34000 range (except first tick). |
| **Emitted/mux video PTS normalized** | delta_pts_us ≈ 33366 on advance ticks, 0 on repeat; no sustained 41000–42000 steps. |
| **Early-frame anomalies** | Any tick with delta_pts_us ≫ 33366 or ≪ 0 beyond tick 0/1 startup; note tick range and value. |

### Notes

Free-form: segment boundaries, seam transitions, DTS vs AAC, anything relevant.

---

## 4. Summary table (fill after all runs)

**Policy:** A row may only be marked **Pass** if the invariants logs have been explicitly reviewed for that run (`INV-FPS-PACING-DIAG`, `INV-FPS-TICK-PTS-DIAG`, and, when present, `INV-FPS-MUX-DIAG`). **Operator subjective “looks good” is not sufficient on its own.** Every positive result must include a note stating that the logs were reviewed. For failure investigation, minimal **INV-FPS-DIAG** (PipelineManager: first 120 content/repeat frames, clock vs frame PTS + asset) is enabled.

Aggregate results in this table:

| Title | Container | Video FPS | Audio codec | Pass/Fail | Notes |
|-------|-----------|-----------|-------------|-----------|-------|
| Dreamscape (1984) | mkv | 23.976 | DTS | Pass | Logs reviewed (INV-FPS-*); first validation; delta_pts ≈ 33366 from tick 2 |
| Guardians of the Galaxy Vol. 2 (2017) | mkv | 23.976 | 6ch multichannel | Pass | Logs reviewed (INV-FPS-*); CADENCE; delta_pts ≈ 33366 from tick 2; tick 1 one-off 400400 µs |
| Enola Holmes (2020) | mkv | 23.976 | (e.g. 5.1 → stereo) | Pass | Logs reviewed (INV-FPS-*); smooth playback; 23.976→29.97 normalized |
| A Bug's Life (1998) | mkv | 23.976 | (e.g. 5.1 → stereo) | Pass | Logs reviewed (INV-FPS-*); smooth playback; additional 23.976→29.97 validation title |
| The Emperor's New Groove | mkv | 23.976 | (e.g. 5.1 → stereo) | Pass | Logs reviewed (INV-FPS-*); smooth playback; additional 23.976→29.97 validation title |
| The Island (2005) | mkv | 23.976 | 6ch multichannel | Pass | Logs reviewed (INV-FPS-*); delta_pts ≈ 33366 from tick 2; tick 1 one-off 300300 µs. Subjective: slight A/V offset on first open, fine after close/reopen (transient, possibly player/session startup) |
| Star Wars – Return of the Jedi (1983, remastered) | mkv | 23.976 | (multichannel) | Pass | Logs reviewed (INV-FPS-*); CADENCE JIP segment; tick 1 one-off 400400 µs, delta_pts ≈ 33366 from tick 2; INV-MUX-DTS-TRACE present confirming audio PTS alignment |
| Close Encounters of the Third Kind (1977) | mkv | 23.976 | (TBD) | **Fail** | Tee'd TS played fast in ffplay → confirmed AIR mux. Fix: EncoderPipeline overwrites video packet PTS/DTS with caller pts90k before mux (INV-FPS-TICK-PTS). Re-validate with tee + ffplay. |

**Pass:** Playback correct **and** delta_wall_us ≈ 33366 **and** PTS normalized (no 42 ms steps).  
**Fail:** Playback fast/choppy **or** log shows delta_pts_us ≈ 42000 or other non-house PTS.

---

## 5. Tee TS stream for ffplay (exact bytes AIR writes)

To verify the stream AIR produces (independent of socket/HTTP/player), fork the TS to a file and play with ffplay:

1. **Set env and run AIR** (e.g. tune the channel so AIR starts):
   ```bash
   export RETROVUE_AIR_TEE_TS_PATH=/tmp/air_tee.ts
   # then start / tune the channel as usual
   ```
2. **Stop or change channel** when you have enough (e.g. 30–60 s). AIR closes the tee file on session end.
3. **Play the tee file:**
   ```bash
   ffplay /tmp/air_tee.ts
   ```
4. **Interpret:** If ffplay plays at correct speed, the fault is downstream (socket write, Core relay, or player). If ffplay also plays fast, the fault is in AIR’s mux/timing.

---

## 5a. Source-frame selection and handoff (INV-HANDOFF-DIAG / INV-HANDOFF-SUMMARY)

**Symptom:** Stream plays normally at startup then speeds up. The important window is **roughly 5–10 seconds** into playback, not just the initial priming. Diagnostics are **not** limited to the first 1–2 seconds.

**Coverage:** First **300 output ticks** (~10 s at 29.97 fps). Analysis is broken into three windows:

| Window       | Ticks    | Purpose |
|-------------|----------|---------|
| **startup** | 0–30     | Priming and first second |
| **transition** | 31–120 | ~1.3 s – 4 s |
| **steady-state** | 121–300 | ~4 s – 10 s (includes 5–10 s range) |

**Per-tick log (`INV-HANDOFF-DIAG`):** For each of the first 300 ticks (when resample is on and we're on live content A or Repeat):

- **output_tick** — session output tick index (0–299).
- **selected_src** — source frame index from `SourceFrameForTick` (intended frame for this tick).
- **advance_or_repeat** — `ADVANCE` or `REPEAT`.
- **actual_src_emitted** — source frame index of the frame actually emitted (from last pop or last good on REPEAT).
- **path** — `primed`, `buffered`, or `decode` (steady-state).

**Per-window summary (`INV-HANDOFF-SUMMARY`):** When crossing into tick 31, 121, and after tick 300, the log emits:

- **window** — `startup`, `transition`, or `steady_state`.
- **tick_range** — e.g. `0-30`, `31-120`, `121-300`.
- **output_ticks** — number of ticks in that window.
- **advance_count** / **repeat_count** — ADVANCE vs REPEAT in that window.
- **unique_src_frames** — count of **distinct** source frame indices emitted in that window (key metric).
- **expected_unique_24_30** — expected distinct source frames for 23.976→29.97 (≈ 0.8 × output_ticks).

**Invariant INV-HANDOFF-001:** On every content/advance/repeat tick (first 300), **actual_src_emitted == selected_src**. Full trace (where assigned, why offset/gap, “next frame wins” vs “frame matching selected_src”): [INV-HANDOFF-001-SOURCE-FRAME-TRACE.md](../design/INV-HANDOFF-001-SOURCE-FRAME-TRACE.md). If not, the pipeline logs an **Error** (`INV-HANDOFF-001 VIOLATION`). This catches the source-frame misalignment bug (stale primed index or decode running ahead) immediately.

**Phase 2 verification (after Phase 1 startup fix):** Rebuild `retrovue_air`, restart the playout session, and capture a fresh log. (1) First content tick: `actual_src_emitted` must be **0** or **1** (not 23+). (2) First 300 ticks: **zero** `INV-HANDOFF-001 VIOLATION` lines. If both hold, Phase 2 is complete. If violations remain in steady state, proceed to Phase 3 (cadence-aware fill).

**Key metric (23.976 → 29.97):** We should **not** see source_frame_index tracking 1:1 with tick_index. If **unique_src_frames** is close to the number of output ticks in a window (e.g. ~90 unique in transition, ~180 in steady-state), that means we're advancing source almost every tick and explains fast playback even if TS timing is valid. Correct behavior: **unique_src_frames** ≈ **expected_unique_24_30** (e.g. ~25 in startup, ~72 in transition, ~144 in steady-state).

**Compare failing vs known-good:** Run the **same** 5–10 second window (ticks 121–300 = steady-state window) for:

1. A **failing** 23.976→29.97 title (e.g. Close Encounters).
2. A **known-good** 23.976→29.97 title (e.g. Dreamscape, Guardians Vol. 2).

Extract `INV-HANDOFF-SUMMARY` for **steady_state** (and optionally transition) from each run. Compare **unique_src_frames** vs **expected_unique_24_30**:

- **Failing:** unique_src_frames likely ≥ output_ticks (or much higher than expected) → too many unique source frames consumed.
- **Known-good:** unique_src_frames ≈ expected_unique_24_30 → correct cadence.

### Log review: Close Encounters (hbo-air.log)

**Run:** HBO channel, first content = Close Encounters (23.976→29.97). Tick 0 = PAD (TAKE_PAD_ENTER); first content tick = 1.

**INV-HANDOFF-SUMMARY (present in log):**

| Window      | tick_range | output_ticks | advance | repeat | unique_src_frames | expected_unique_24_30 |
|-------------|------------|--------------|---------|--------|-------------------|------------------------|
| startup     | 0–30       | 31           | 24      | 6      | **24**            | 24 ✓                   |
| transition  | 31–120     | 90           | 72      | 18     | **72**            | 72 ✓                   |
| steady_state| 121–300    | —            | —       | —      | —                 | 144 (not in log; run didn’t reach tick 300) |

So **per-window unique counts match expected** (24 and 72). That suggests the *rate* of unique frames per window is correct, but the **alignment** of which source frame is shown at which output tick is wrong.

**INV-HANDOFF-DIAG (per-tick):**

- **Tick 1:** `selected_src=1` but `actual_src_emitted=27` `path=primed` → we show source frame **27** at output tick 1 when we should show source frame **1**. Offset **+26** from the first content tick.
- **Tick 2–30:** `actual_src_emitted` tracks `selected_src + 26` (e.g. tick 10 selected_src=8 actual=34; tick 30 selected=24 actual=50). So startup/buffered phase has a **constant +26 offset**.
- **From tick 52 onward (decode path):** `actual_src_emitted` runs **ahead** of `selected_src` and the gap grows:
  - Tick 52: selected=42, actual=71 (gap 29)
  - Tick 120: selected=96, actual=175 (gap 79)
  - Tick 195: selected=156, actual=293 (gap 137)

So we are **emitting source frames far ahead** of what `SourceFrameForTick` selects: the decode path is advancing source frames too aggressively. Correct 23.976→29.97 cadence would keep `actual_src_emitted` ≈ `selected_src` (with REPEAT ticks reusing the same frame). Here, the fill thread / decoder is providing frames that are already ahead of the tick-based selection, and the gap increases in steady-state.

**Conclusion:** The bug is not just “too many unique frames” (the counts 24/72 are correct) but **wrong mapping**: we show source frame N+offset (and growing) instead of source frame N at output tick N. Likely causes: (1) **Primed/buffered frames** for this segment were stamped with a **stale `source_frame_index`** (e.g. producer’s `frame_index_` not reset to 0 when this segment became live, so the first content frame is tagged 27 instead of 0). (2) **Decode path**: fill thread is calling `TryGetFrame` and the decoder is advancing faster than the tick loop consumes, so the buffer contains “future” source frames and we pop them 1:1 per tick, causing `actual_src_emitted` to run ahead of `selected_src`. Next step: ensure `frame_index_` is 0 when the first frame for the *live* segment is produced (primed/buffered), and ensure the fill loop only adds frames that match the cadence (e.g. don’t advance decode when we’re already ahead of `SourceFrameForTick`), or have the tick loop drive which source index is needed.

### Validation report (evidence from hbo-air.log)

**Run:** HBO, first content = Close Encounters (23.976→29.97). Log: `pkg/air/logs/hbo-air.log` (SESSION_BUILD build_ts=2026-03-12T21:01:54). **Note:** This report is from the run *before* the 1-based source_frame_index fix. After restart with the fixed binary, re-run and replace with new evidence.

**1. First 50 INV-HANDOFF-DIAG lines (excerpt):**

| output_tick | selected_src | advance_or_repeat | actual_src_emitted | path    |
|-------------|--------------|-------------------|--------------------|--------|
| 1           | 1            | ADVANCE           | 0                  | primed |
| 2           | 2            | ADVANCE           | 1                  | buffered |
| 3–4        | 3–4          | ADVANCE           | 2–3                | buffered |
| 5           | 4            | REPEAT            | 3                  | buffered |
| 6–10       | 5–8          | ADVANCE/REPEAT    | 4–7                | buffered |
| 11–30      | 9–24         | ADVANCE/REPEAT    | 8–23               | buffered |
| 31         | 25           | ADVANCE           | 24                 | buffered |
| 32–50      | 26–40        | ADVANCE/REPEAT    | 25–39              | decode |

**2. First 300 ticks summary**

| Metric | Value |
|--------|--------|
| **Total INV-HANDOFF-001 VIOLATION count** | **296** |
| **actual_src_emitted == selected_src for all content ticks?** | **No** |

**Mismatch pattern in this log:**

- **Ticks 1–31:** Off-by-one: `actual_src_emitted = selected_src - 1` every tick (e.g. tick 1 selected=1 actual=0).
- **Ticks 32–120:** Same off-by-one (actual = selected - 1).
- **From tick 121:** `actual_src_emitted` runs **ahead** of `selected_src`; gap grows (e.g. tick 121 selected=97 actual=147; tick 290 selected=232 actual=411).

**3. 5–10 second window (steady state)**

Transition (31–120): unique_src_frames=72, expected=72 ✓. Steady state (121–300): no INV-HANDOFF-SUMMARY in log; per-tick shows actual far ahead of selected → stream will play fast in this window.

**4. Subjective playback**

Not in log. Record for same title after restart: playback correct for 10+ s, or still speeds up after ~1 s?

**Conclusion:** This log does **not** validate the fix. Two issues: (1) off-by-one in first 300 ticks, (2) actual runs ahead of selected from tick 121. Restart with rebuilt binary; confirm zero violations and actual==selected for first 300 ticks and subjective playback OK. If steady-state violations remain, Phase 3 (cadence-aware fill) required.

---

## 5b. PCR (Program Clock Reference) — required for playback pacing

Without PCR in the TS, players have no transport clock and often decode as fast as possible, so the stream can play fast even when PTS values are correct.

**Where PCR is configured:** TS bytes are produced by **EncoderPipeline** (FFmpeg mpegts muxer). Both the blockplan path (PipelineManager → EncoderPipeline) and **MpegTSOutputSink** (which owns an EncoderPipeline) use the same muxer. MpegTSOutputSink does not write TS packets itself; it delegates to EncoderPipeline.

**EncoderPipeline** enables PCR by:
- Setting **muxrate** to the stream bitrate (CBR), so the mpegts muxer uses the **CBR PCR path** (`ts->mux_rate > 1`), which reliably writes PCR via `get_pcr(ts)` and adaptation-field insertion. The VBR path (`muxrate=0`) was not writing PCR in practice.
- Setting `pcr_period` to **20 ms** (format context and muxer opts dict) so the muxer emits PCR at least every 20 ms.

The FFmpeg mpegts muxer: in CBR mode it writes PCR in adaptation fields (PCR_flag set) on the PCR PID (typically the video PID); PCR is derived from packet count and mux_rate so it advances with the transport stream.

**Verify PCR in a captured TS:**
```bash
ffprobe -show_packets -show_entries packet=pcr,pcr_time -of csv hbo.ts
```
Expect non-empty `pcr` and `pcr_time` for some packets (e.g. on the video PID). If none appear, PCR is not being written and playback may run fast.

**Bundled mpegts muxer (force PCR):** The repo patches `pkg/air/third_party/ffmpeg/src/libavformat/mpegtsenc.c` so that in `mpegts_init`, if options did not enable PCR (`pcr_period_ms < 0` or `mux_rate <= 1`), we force `pcr_period_ms = 20` and `mux_rate = 8000000`. That makes the muxer always use the CBR PCR path. **You must rebuild the static FFmpeg** so this patch is in `libavformat.a`, then rebuild AIR. From repo root: `bash pkg/air/scripts/build_ffmpeg_static.sh` (if you hit a GCC ICE, try `cd pkg/air/third_party/ffmpeg/src && make -j1` after configure), then `cmake --build pkg/air/build --target retrovue_air`.

---

## 6. If another file still plays fast

1. **Do not change code yet.** Treat as a new failing path to document.
2. **Capture:** `INV-FPS-DIAG` lines (and, if re-enabled, `INV-FPS-TICK-PTS-DIAG` / `INV-FPS-MUX-DIAG` / `INV-FPS-PACING-DIAG`) for the run where the title plays — grep for the asset to get the relevant ticks.
3. **Compare to Dreamscape:** Same session FPS (29.97), same log format. Diff:
   - Where does delta_pts_us first diverge (e.g. primed vs buffered vs first decode)?
   - Any path (e.g. DTS, different container) that might bypass normalization?
4. **Record:** Title, container, fps, audio codec, and the tick range / values that show the anomaly. Only after that evidence do we consider a new code path or fix.

---

## 7. When to declare the bug resolved

- All titles in the matrix **Pass** (subjective + log criteria).
- At least 2–3 former problem titles and one control included.
- If any title **Fails**, complete Section 5 and do **not** mark resolved until the new path is understood and fixed and re-validated.

---

## 8. Changelog

| Date | Change |
|------|--------|
| 2026-03-12 | Added: multi-file validation runbook; issue not declared fixed. |
| 2026-03-12 | Close Encounters reported fast playback; re-enabled minimal INV-FPS-DIAG; normalized PAD frame PTS in TickProducer::GeneratePadFrame. |
| 2026-03-12 | Re-added INV-FPS-PACING-DIAG, INV-FPS-TICK-PTS-DIAG; MUX_PACKET_DIAG extended to first 60 video packets. Section 9 added: three sequences for Close Encounters. |
| 2026-03-12 | Tee TS stream: RETROVUE_AIR_TEE_TS_PATH env writes exact AIR output to a file for ffplay verification (Section 5). |
| 2026-03-12 | Close Encounters: tee'd TS played fast in ffplay → AIR mux at fault. EncoderPipeline now overwrites video packet PTS/DTS with caller pts90k before EmitPacket (fixed + dynamic receive paths) so TS has exact output clock timing. Re-test with tee + ffplay. |
| 2026-03-12 | PCR: ffprobe showed no PCR in captured TS. Without PCR, players decode as fast as possible. EncoderPipeline now adds pcr_period=20 to muxer opts dict (and keeps av_opt_set); PCR written by FFmpeg mpegts muxer into adaptation fields on video PID. Section 5b documents PCR and verification. |
| 2026-03-12 | PCR still missing after pcr_period fix. Switched to CBR muxrate (config.bitrate) so mpegts muxer uses CBR PCR path (get_pcr(ts)); VBR path was not emitting PCR. Rebuild and re-check ffprobe pcr/pcr_time. |
| 2026-03-12 | PCR still missing after CBR muxrate. Patched bundled mpegts muxer (mpegtsenc.c): in mpegts_init force pcr_period_ms=20 and mux_rate=8M if options did not set them, so PCR is always enabled. Rebuild static FFmpeg (build_ffmpeg_static.sh or make from third_party/ffmpeg/src) then rebuild AIR. |
| 2026-03-12 | INV-HANDOFF-DIAG extended to first 300 ticks (~10 s). Three windows: startup (0–30), transition (31–120), steady-state (121–300). Added INV-HANDOFF-SUMMARY per window: unique_src_frames vs expected_unique_24_30. Key: 1:1 source/tick = fast playback; compare failing vs known-good on same 5–10 s window (Section 5a). |
| 2026-03-12 | **INV-HANDOFF-001:** Invariant `actual_src_emitted == selected_src`; on violation log Error (output_tick, selected_src, actual_src_emitted, path). Catches source-frame misalignment instantly. |

---

## 9. Close Encounters — three diagnostic sequences

When investigating fast playback, capture and inspect these three log sequences (run with Close Encounters as first content, then grep `pkg/air/logs/<channel>-air.log`).

### 1️⃣ Tick pacing — `INV-FPS-PACING-DIAG`

**Look for:** `delta_wall_us ≈ 33366` (wall clock advances ~33.37 ms per tick).

**Example (from run with TICK_TIMING_DIAG; after rebuild you get INV-FPS-PACING-DIAG with explicit delta_wall_us/delta_pts_us):**

```
tick=0  deadline_us=846480399117
tick=1  deadline_us=846480432484  → delta_deadline_us = 33367 ✓
tick=2  deadline_us=846480465851  → delta = 33367 ✓
tick=3  deadline_us=846480499217  → delta = 33366 ✓
...
```

**Interpretation:** Pacing is correct (29.97 fps) when `delta_wall_us` (or `deadline_us` deltas) are in the 33300–33400 µs range.

---

### 2️⃣ Frame normalization — `INV-FPS-TICK-PTS-DIAG`

**Look for:** `emitted_pts_us` increments **≈ 33366** (house grid). If you see **≈ 41708** then the old bug (23.976 leakage) is still present on some path.

**Log line format:**  
`tick_index= … source_pts_us= … emitted_pts_us= … emitted_duration_us= … output_frame_duration_us= … resample_mode= …`

**Check:** Consecutive `emitted_pts_us` differences should be 33366 or 33367 (or 0 on repeat ticks). Any sustained 41708 step = leak.

---

### 3️⃣ Mux timestamps — `MUX_PACKET_DIAG` (video)

**Look for:** `pts_90k` increments **≈ 3003** (90 kHz units for 29.97 fps: 90000/29.97 ≈ 3003).

**Example from current log (Close Encounters as first content):**

```
video_seq=1  pts_90k=0
video_seq=2  pts_90k=3003   → delta = 3003 ✓
video_seq=3  pts_90k=6006   → delta = 3003 ✓
video_seq=4  pts_90k=9009   → delta = 3003 ✓
...
```

**Interpretation:** Mux is correct when video `pts_90k` steps by ~3003 per frame. If steps are ~3750 (90k/24) or other, the wrong timebase is reaching the mux.

---

**After re-run with the new build:** Grep for `INV-FPS-PACING-DIAG`, `INV-FPS-TICK-PTS-DIAG`, and `MUX_PACKET_DIAG.*video` in the log and compare to the above. If (1) and (3) are good but playback is still fast, the cause is likely downstream (player or delivery).
