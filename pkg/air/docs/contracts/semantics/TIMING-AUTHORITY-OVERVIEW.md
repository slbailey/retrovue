# Timing Authority — Architectural Overview

**Purpose:** Single concise reference for how session time, frame mapping, audio, and seam readiness are governed. For binding contracts and test enforcement, see the linked invariants. This document does not replace them.

**Related contracts:** [INV-FPS-RESAMPLE](INV-FPS-RESAMPLE.md), [INV-FPS-MAPPING](INV-FPS-MAPPING.md), [INV-AUDIO-PRIME-002](INV-AUDIO-PRIME-002.md), [INVARIANTS-INDEX](../INVARIANTS-INDEX.md).

---

## A. Session Time Authority

Output session time is defined **exclusively** by the rational tick grid. There is no separate “wall clock” or accumulated-interval authority for when frames are due.

- **Tick time:** `tick_time_us(n) = floor(n × 1_000_000 × fps_den / fps_num)` (integer math; 128-bit intermediates where needed).
- No accumulated ms/µs rounding; no `interval_us += round(1e6/fps)`.
- **Output video PTS delta** between consecutive returned frames equals **one output tick** (e.g. 33 333 µs at 30 fps).
- **metadata.duration** for each returned video frame equals **one output tick** (same rational). Input frame duration must never leak into output duration or pacing.

---

## B. Frame Mapping Authority (OFF / DROP / CADENCE)

Source→output frame selection uses exactly one of three modes. Mode is chosen by **rational comparison only** (no float epsilon).

| Mode   | Condition | Behavior |
|--------|-----------|----------|
| **OFF**   | Exact rational equality: `in_num×out_den == out_num×in_den` | 1 decode per tick; emit as-is. |
| **DROP**  | Integer ratio: `(in_num×out_den) % (out_num×in_den) == 0`, step = ratio | Decode `step` input frames per tick; emit **one** video frame (first); **aggregate audio** from all decoded frames in the step into the single returned FrameData. |
| **CADENCE** | Non-integer ratio | Rational accumulator (e.g. decode_budget); decode when ≥ 1.0. |

- **DROP** must emit exactly **one video frame per output tick** and aggregate audio from every decoded frame in the step so audio production matches the input time advanced.
- Input frame duration must never appear in output frame duration or PTS delta (INV-TICK-AUTHORITY-001).

---

## C. Audio Authority

- Audio samples produced **per output tick** must match the tick span (house format, sample rate, one tick duration).
- Audio is produced **per decoded input frame**; in DROP, “skip” decodes still contribute their decoded audio (single push point: one FrameData per tick carries aggregated audio).
- **Priming:** Ready for seam must not be declared unless the **audio depth threshold** (e.g. min prime ms) is satisfied. The primed frame must carry ≥1 audio packet when the asset has audio (INV-AUDIO-PRIME-002).

---

## D. Seam Readiness

- Ready for seam requires **video** (primed frame in buffer) **and** sufficient **audio headroom** (depth ≥ threshold).
- The primed frame must carry **≥1 audio packet** when the asset has audio; otherwise the buffer must not be treated as ready for seam until audio is present.

---

## Index Quick Links

| Topic        | Contract / doc |
|-------------|----------------|
| Tick grid, no rounded accumulation | INV-FPS-RESAMPLE |
| OFF/DROP/CADENCE, rational only; output duration/PTS = one tick | INV-FPS-MAPPING, INV-TICK-AUTHORITY-001 |
| Output PTS = tick grid | INV-FPS-TICK-PTS |
| Primed frame audio, seam gate | INV-AUDIO-PRIME-002 |
| All invariant IDs | [INVARIANTS-INDEX](../INVARIANTS-INDEX.md) |
