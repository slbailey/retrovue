# Timeline Invariant Test Scenarios

These scenarios define the expected behavior of the broadcast timeline engine
according to INV-TIMELINE-* invariants. Each test is designed to FAIL under
the current implementation, proving the invariant violation.

Test file (when implemented): `pkg/core/tests/contracts/test_inv_timeline_authority.py`

---

## Test: restart_during_longform_preserves_program

### Invariant Covered
INV-TIMELINE-RESTART-IDENTICAL-001, INV-TIMELINE-LONGFORM-INVIOLATE-001

### Setup
Channel HBO. Asset catalog contains "In Search of Darkness Part III" (342 minutes) and 50+ other movies. Channel DSL uses `progression: random`. The schedule for broadcast day March 23 is compiled at 01:30 UTC with a day-varying seed. The compilation places "In Search of Darkness Part III" in the last slot, starting at 09:30 UTC on calendar March 24 and ending at ~15:12 UTC. The process is PID 1281. A viewer is watching.

### Action
At 13:54 UTC (while the movie is at the 4-hour-24-minute mark), the process dies and restarts as PID 49387. `_build_initial()` runs. Local time is 09:54 EDT. `day_start_hour` is 6. Since 9 >= 6, `start_date` = March 24 (today). March 23 is not in the compilation window. `_build_initial` compiles March 24, 25, and 26.

### Expected Result
After restart, querying "what block covers 14:00 UTC on March 24" returns "In Search of Darkness Part III" with start time 09:30 UTC and duration 342 minutes. The movie continues from its current offset. The viewer reconnects and resumes watching at the 4.5-hour mark.

### Why It Fails Today
`_build_initial()` recompiles March 24 from the DSL YAML with a fresh `CatalogAssetResolver`. Since `_get_cached_schedule()` always returns `None`, the prior active `ScheduleRevision` for March 24 is not read — it is superseded and replaced. The new compilation uses `progression: random` with the same day-seed but against a potentially different asset catalog, producing a different movie selection. Even if the catalog is unchanged, the new March 24 schedule starts at 10:00 UTC (its `effective_day_open_ms` is derived from `_load_prior_day_carry_in_end_ms`, which reads March 23's revision — but the prior March 24 revision's first slot at 10:00 now covers time where the carry-in movie was playing). The 09:30–15:12 window that belonged to "In Search of Darkness" is overwritten. The viewer gets "Lilo & Stitch" at 13:30 instead.

---

## Test: carry_in_survives_restart_when_prior_day_outside_window

### Invariant Covered
INV-TIMELINE-CARRY-IN-PRESERVED-001, INV-TIMELINE-BOUNDARY-IMMUTABLE-001

### Setup
Channel HBO. March 23 broadcast day's active `ScheduleRevision` has its last `ScheduleItem` starting at 09:30 UTC with `duration_sec = 21600` (360 minutes, ending at 15:30 UTC on calendar March 24). This revision was created by PID 1281 and remains `status = 'active'` in the database.

### Action
Process restarts at 13:00 UTC. `_build_initial()` determines `start_date = March 24` (local hour 9 >= day_start_hour 6). The compilation loop covers March 24, 25, 26. March 23 is not compiled.

`_load_prior_day_carry_in_end_ms()` reads March 23's active revision and finds the last item ends at 15:30 UTC. It returns this as `active_carry_in_end_ms`. `_compute_effective_day_open_ms("2026-03-24", 6, "America/New_York", 15:30_utc_ms)` returns 15:30 UTC (since 15:30 > 10:00 day start).

March 24's compilation begins at 15:30 UTC, and no block starts before that time.

### Expected Result
March 24's first block starts at or after 15:30 UTC. No block from March 24 occupies any time between 10:00 and 15:30 UTC. The carry-in movie's window is preserved.

### Why It Fails Today
The carry-in boundary is now correctly computed (after the `_load_prior_day_carry_in_end_ms()` fix), so March 24's blocks do not overlap the carry-in window. However, the carry-in movie itself is not present in the post-restart in-memory `_blocks` list. `_build_initial` does not load the carry-in block from March 23's revision into `_blocks` — it only prevents March 24 from overlapping it. If a viewer queries "what is playing at 14:00 UTC", `_find_in_memory_block(14:00)` returns `None` because no in-memory block covers that time. The carry-in movie is a gap in the timeline.

---

## Test: recompilation_replaces_existing_timeline

### Invariant Covered
INV-TIMELINE-APPEND-ONLY-001

### Setup
Channel HBO. At 06:00 UTC, the process compiles March 24 and produces blocks covering 10:00–10:00+24h with specific movie selections: Hell Night at 10:00, The Grinch at 12:00, Lilo & Stitch at 13:30, etc. These are persisted as ScheduleRevision `rev-A` with `status = 'active'` and stored in `_blocks`.

### Action
At 14:00 UTC, the process restarts. `_build_initial()` runs again. It calls `_compile_day("2026-03-24")`, which reads the DSL YAML, calls `compile_schedule()` with the same day-seed but a freshly-loaded `CatalogAssetResolver`. Between the two compilations, one new movie was ingested and approved, changing the candidate pool. `progression: random` with the same seed but a different pool size produces a different shuffle order. The new compilation produces: Road House at 10:00, Beauty and the Beast at 12:00, Superman at 14:00. This is persisted as `rev-B`, superseding `rev-A`.

### Expected Result
The blocks covering 10:00–14:00 UTC remain unchanged because they are in the past and have already aired. Only blocks from 14:00 onward (the boundary) may contain new content.

### Why It Fails Today
`_compile_day()` recompiles the entire broadcast day from the DSL with no regard for which time ranges have already aired. `_get_cached_schedule()` returns `None`, so it never reads `rev-A`. `write_active_revision_from_compiled_schedule()` supersedes `rev-A` in its entirety — past, present, and future blocks are all replaced. The blocks from 10:00–14:00 now contain different movies than what actually aired. The EPG retroactively displays Road House at 10:00 instead of Hell Night, contradicting the as-run log.

---

## Test: epg_matches_playout_after_restart

### Invariant Covered
INV-TIMELINE-EPG-PLAYOUT-AGREE-001, INV-TIMELINE-SINGLE-AUTHORITY-001

### Setup
Channel HBO. Before restart, the active `ScheduleRevision` for March 24 (`rev-A`) shows Hell Night at 10:00. The in-memory `_blocks` list also has Hell Night at 10:00. EPG and playout agree.

### Action
Process restarts at 11:00 UTC. `_build_initial()` recompiles March 24 from DSL. The asset catalog now includes a newly-ingested movie. The new compilation produces Road House at 10:00 instead of Hell Night. This is persisted as `rev-B`, superseding `rev-A`. The in-memory `_blocks` list contains Road House at 10:00.

Query the EPG for 10:30 UTC on March 24. Query the playout block for 10:30 UTC on March 24.

### Expected Result
EPG and playout return the same program for 10:30 UTC. Both reflect the same timeline.

### Why It Fails Today
After restart, EPG and playout agree with each other (both reflect `rev-B` / the new `_blocks`), but they disagree with what actually aired. The as-run log at `/opt/retrovue/data/logs/asrun/hbo/2026-03-24.asrun.jsonl` records Hell Night at 10:00 (from `rev-A`). The EPG now claims Road House at 10:00. There are two distinct failure modes:

**Mode A (immediate post-restart):** EPG and playout agree with each other but disagree with historical truth. The single-authority invariant is satisfied in the narrow sense (one timeline), but the EPG-playout-asrun triangle is inconsistent.

**Mode B (mid-restart race):** If the EPG is served from the database (`get_canonical_epg()` reads `ScheduleRevision`) while playout is served from in-memory `_blocks`, and a query arrives during the brief window where `_blocks` is rebuilt but the revision write has not yet committed, the EPG returns `rev-A` content while playout returns `rev-B` content. This window is narrow (sub-second) but structurally present.

---

## Test: past_time_ranges_rewritten_on_restart

### Invariant Covered
INV-TIMELINE-APPEND-ONLY-001, INV-TIMELINE-BOUNDARY-IMMUTABLE-001

### Setup
Channel HBO. At 08:00 UTC, the schedule is compiled. March 24 covers 10:00–10:00+24h. The first three blocks are: Hell Night 10:00–12:00, The Grinch 12:00–13:30, Lilo & Stitch 13:30–15:00. These blocks have aired (or are currently airing). The as-run log records Hell Night and The Grinch as played.

### Action
At 14:30 UTC, the process restarts. `_build_initial()` recompiles March 24. The new compilation produces different content starting at 10:00. Record the `ScheduleRevision` for March 24 before and after the restart.

### Expected Result
All `ScheduleItem` rows with `start_time < 14:30 UTC` remain unchanged. The recompilation only affects times ≥ 14:30 UTC. A boundary at 14:30 UTC separates the immutable past from the mutable future.

### Why It Fails Today
No boundary concept exists in the compilation path. `_compile_day()` produces a complete schedule for the entire broadcast day. `write_active_revision_from_compiled_schedule()` supersedes the prior revision atomically — all 12+ `ScheduleItem` rows from the prior revision become invisible (their parent revision is `superseded`), replaced by 12+ new rows covering the same time range. The `ScheduleItem` for 10:00 (Hell Night, already aired 4.5 hours ago) is replaced by a `ScheduleItem` for 10:00 with a different movie. There is no check of `start_time < now()` before writing. There is no boundary parameter in `_compile_day()` that preserves past rows.

---

## Test: timeline_gap_during_carry_in_after_restart

### Invariant Covered
INV-TIMELINE-CONTINUITY-001

### Setup
Channel HBO. March 23's last block is "In Search of Darkness Part III" covering 09:30–15:30 UTC (calendar March 24). March 24's schedule (compiled before restart) starts at 15:30 UTC with The Queen. The in-memory `_blocks` list contains both the March 23 carry-in block and the March 24 blocks. Timeline is contiguous.

### Action
Process restarts at 13:00 UTC. `_build_initial()` sets `start_date = March 24`. It loads March 23's carry-in end (15:30 UTC) from the database. It compiles March 24 starting at 15:30. The resulting `_blocks` list contains March 24 blocks starting at 15:30 UTC.

Query the timeline for all times between 09:30 and 15:30 UTC.

### Expected Result
Every time T between 09:30 and 15:30 UTC is covered by "In Search of Darkness Part III". There is no gap.

### Why It Fails Today
`_build_initial()` does not load the carry-in block from March 23's `ScheduleRevision` into the in-memory `_blocks` list. It only uses March 23's data to compute `effective_day_open_ms` — a boundary that prevents March 24 blocks from overlapping the carry-in window. But the carry-in block itself (the "In Search of Darkness" entry from March 23) is not added to `_blocks`. The time range 09:30–15:30 UTC is a gap in the runtime timeline. `_find_in_memory_block(14:00_utc_ms)` returns `None`. If a viewer tunes in during this window, `get_block_at()` returns `None`, which triggers a `NoScheduleDataError` — the channel returns a 503 instead of playing the movie.

---

## Test: multiple_compilations_same_day_do_not_fork_timeline

### Invariant Covered
INV-TIMELINE-SINGLE-AUTHORITY-001, INV-TIMELINE-APPEND-ONLY-001

### Setup
Channel HBO. March 24 has been compiled once, producing `rev-A`. The in-memory `_blocks` list reflects `rev-A`. `rev-A` is `status = 'active'` in the database. Time is 16:00 UTC.

### Action
`_maybe_extend_horizon()` fires because the remaining horizon has fallen below 6 hours. It calls `_compile_day("2026-03-25")`. As part of this, March 25's schedule is compiled and persisted. No action is taken on March 24.

Separately, a config reload (`POST /admin/reload-config`) invalidates the DSL cache. The next viewer request triggers `get_block_at()`, which calls `_maybe_extend_horizon()`. Since `_compiled_days` contains March 25, the extension is skipped. But if `_blocks` was cleared by the cache invalidation, `_build_initial()` runs again, recompiling March 24 from DSL. This produces `rev-B` for March 24, superseding `rev-A`.

### Expected Result
March 24's timeline from 10:00–16:00 UTC is unchanged. The config reload does not retroactively alter already-compiled and partially-aired content.

### Why It Fails Today
`_build_initial()` has no concept of "this day was already compiled and partially aired." It checks `if self._blocks: return` — but if `_blocks` was cleared by the config invalidation, the idempotency gate does not protect. The full recompilation runs, supersedes `rev-A`, and produces potentially different content for times that already aired. The EPG retroactively changes. The playout timeline changes. If a viewer was mid-movie, the movie is replaced.

---

## Test: join_in_progress_offset_consistent_across_restart

### Invariant Covered
INV-TIMELINE-RESTART-IDENTICAL-001, INV-TIMELINE-LONGFORM-INVIOLATE-001

### Setup
A longform program is scheduled from Tₛ to Tₑ on channel HBO. Duration is 342 minutes. A viewer joins at time T₁ where Tₛ < T₁ < Tₑ. The system calculates a join-in-progress offset of (T₁ - Tₛ) and begins playing the program at that offset. The viewer is watching.

### Action
The process restarts at time T₂ where T₁ < T₂ < Tₑ. The viewer reconnects at T₂.

### Expected Result
The viewer resumes the same program at offset (T₂ - Tₛ). The program identity, start time Tₛ, and duration (Tₑ - Tₛ) remain unchanged. The JIP calculation produces a correct, larger offset reflecting the additional elapsed time since the first join.

### Why It Fails Today
After restart, `_build_initial()` recompiles the schedule from the DSL YAML. The block covering T₂ may be a different program with a different Tₛ. Three failure modes:

**Mode A (different program):** The recompilation selects a different movie for the time slot covering T₂. The viewer reconnects and gets a completely different film. The JIP offset is calculated against the new program's Tₛ, which bears no relationship to the original program.

**Mode B (same program, different start time):** The recompilation happens to select the same movie but places it at a different grid slot. The new Tₛ' differs from the original Tₛ. The JIP offset (T₂ - Tₛ') is wrong — the viewer sees the movie at an incorrect position (too early or too late in the film).

**Mode C (gap — no block):** If the program was a carry-in from the prior day and the prior day is outside the compilation window, the carry-in block is not loaded into `_blocks`. `_find_in_memory_block(T₂)` returns `None`. The system returns a 503 error instead of resuming the program. The JIP calculation never executes.
