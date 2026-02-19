# Tier-2 miss at join (utc_ms=1771507800000) — root cause

**Evidence:** Tier-2 miss at utc_ms=1771507800000; unfilled block blk-782b9972c889 (segs=7) fed; immediately after, filled block blk-3d62a604ef41 (segs=28) fed.

---

## One-sentence root cause

**The PlaylogHorizonDaemon never wrote a Tier-2 row for the block covering 1771507800000 because when it extended the horizon, `cursor_ms` was already ≥ 1771509600000 (wall clock at or past 14:00 UTC), so it skipped that block under the rule “skip if block_end <= cursor_ms” and only filled blocks starting at 14:00 UTC and later.**

---

## Step 1 — DB state for the missing block

**Query 1:** Rows where `channel_slug='cheers-24-7'` AND `start_utc_ms <= 1771507800000 < end_utc_ms`  
**Result:** count = **0** (no row covers join time)

**Query 2:** Row with `block_id='blk-782b9972c889'`  
**Result:** **NONE** (block was never written to TransmissionLog)

**Query 3:** Row with `block_id='blk-3d62a604ef41'`  
**Result:** **EXISTS** — start_utc_ms=1771509600000, end_utc_ms=1771511400000, segs=28

**Query 4:** All TransmissionLog rows for channel in [1771506000000, 1771513200000):  
**Result:** Only 2 rows — both start at or after 1771509600000 (no row for 1771507800000 or 1771506000000)

**Query 5:** Max `end_utc_ms` in TransmissionLog for channel with `end_utc_ms < 1771509600000`  
**Result:** **None** — no Tier-2 row ends before 14:00 UTC; the first row written in this range starts at 1771509600000.

---

## Step 2 — Why the daemon didn’t fill it

The daemon never *attempted* to fill blk-782b9972c889. In `_extend_to_target()` it:

1. Sets `cursor_ms = max(self._farthest_end_utc_ms, now_ms)`.
2. For each Tier-1 block: **if `block_end <= cursor_ms`: continue** (skip).
3. Only then does it check `_block_exists_in_txlog(block_id)` and, if missing, fill and write.

So if `cursor_ms >= 1771509600000` (the end of the missing block), the block [1771507800000, 1771509600000) is skipped as “in the past” and is never filled. There is no “filled block” or “failed to fill” log for blk-782b9972c889 because that block is never considered.

**Why was cursor_ms ≥ 1771509600000?**  
`_farthest_end_utc_ms` is the max `end_utc_ms` in TransmissionLog for the channel. We proved there is no row with `end_utc_ms < 1771509600000`. So the first time the daemon wrote any Tier-2 row in this window, `cursor_ms` could only be ≥ 1771509600000 if **`now_ms` was already ≥ 1771509600000**. So the daemon’s first extension run for this horizon happened when wall clock was already at or past 14:00 UTC, so it skipped the 13:30–14:00 block and only filled from 14:00 onward.

---

## Step 3 — Broadcast-day mapping (post-fix)

- **utc_ms = 1771507800000** → UTC 2026-02-19 13:30:00 → America/New_York 2026-02-19 08:30:00.
- **Broadcast date** (programming_day_start_hour=6): **2026-02-19** (08:30 is after 06:00).
- Block end: 1771509600000 → 2026-02-19 14:00 UTC (09:00 Eastern).
- Tier-1 for 2026-02-19 would contain both the 13:30–14:00 and 14:00–14:30 blocks. Daemon scan uses `scan_date = _broadcast_date_for(cursor_dt) - 1 day` through `end_date = _broadcast_date_for(target_dt) + 1 day`, so 2026-02-19 is included. The missing block is not missing because of broadcast-day or scan range; it is missing because it was skipped by the cursor rule.

---

## Step 4 — schedule_service query vs TransmissionLog write

- **Read** (`_get_filled_block_at`): `channel_slug == channel_id`, `start_utc_ms <= utc_ms`, `end_utc_ms > utc_ms` (half-open [start, end)).
- **Write** (`_write_to_txlog`): `channel_slug=self._channel_id`, `start_utc_ms=block.start_utc_ms`, `end_utc_ms=block.end_utc_ms` (same units and semantics).

Same `channel_slug`, same boundaries, same milliseconds. No off-by-one at exact `start_utc_ms` or `end_utc_ms`; the miss is not due to a query/write boundary mismatch.

---

## Step 5 — Why the next block was filled

- Tier-2 **does** have a row for blk-3d62a604ef41 (start_utc_ms=1771509600000, end_utc_ms=1771511400000).
- That block starts exactly when the missing block ends (14:00 UTC). When the daemon ran with `cursor_ms >= 1771509600000`, it skipped the 13:30–14:00 block (block_end 1771509600000 <= cursor_ms) and then considered the 14:00–14:30 block (block_end 1771511400000 > cursor_ms), so it filled and wrote it.
- So we get a **one-block gap**: no row for [1771507800000, 1771509600000), then rows for [1771509600000, …). The gap is caused solely by the “skip if block_end <= cursor_ms” logic when the daemon first extended the horizon after 14:00 UTC.

---

## Summary

| Question | Answer |
|----------|--------|
| **DB proof for missing block** | Zero rows cover 1771507800000; no row for block_id blk-782b9972c889; max end_utc_ms before 1771509600000 is None. |
| **Daemon behavior** | Daemon never attempted to fill that block; it skips it because `block_end <= cursor_ms` when cursor_ms ≥ 1771509600000. |
| **Why only that block missed** | Cursor was already past the block’s end when the daemon extended, so the 13:30–14:00 block was skipped and the 14:00–14:30 block was filled, producing a one-block gap. |

Diagnostic script: `scripts/diagnose_tier2_miss.py` (run from pkg/core with venv and PYTHONPATH=src).
