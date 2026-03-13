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

**Policy:** A row may only be marked **Pass** if the invariants logs have been explicitly reviewed for that run (`INV-FPS-PACING-DIAG`, `INV-FPS-TICK-PTS-DIAG`, and, when present, `INV-FPS-MUX-DIAG`). **Operator subjective “looks good” is not sufficient on its own.** Every positive result must include a note stating that the logs were reviewed.

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

**Pass:** Playback correct **and** delta_wall_us ≈ 33366 **and** PTS normalized (no 42 ms steps).  
**Fail:** Playback fast/choppy **or** log shows delta_pts_us ≈ 42000 or other non-house PTS.

---

## 5. If another file still plays fast

1. **Do not change code yet.** Treat as a new failing path to document.
2. **Capture:** Full `INV-FPS-TICK-PTS-DIAG`, `INV-FPS-MUX-DIAG`, and `INV-FPS-PACING-DIAG` lines for the affected run (or at least first 120 ticks).
3. **Compare to Dreamscape:** Same session FPS (29.97), same log format. Diff:
   - Where does delta_pts_us first diverge (e.g. primed vs buffered vs first decode)?
   - Any path (e.g. DTS, different container) that might bypass normalization?
4. **Record:** Title, container, fps, audio codec, and the tick range / values that show the anomaly. Only after that evidence do we consider a new code path or fix.

---

## 6. When to declare the bug resolved

- All titles in the matrix **Pass** (subjective + log criteria).
- At least 2–3 former problem titles and one control included.
- If any title **Fails**, complete Section 5 and do **not** mark resolved until the new path is understood and fixed and re-validated.

---

## 7. Changelog

| Date | Change |
|------|--------|
| 2026-03-12 | Added: multi-file validation runbook; issue not declared fixed. |
