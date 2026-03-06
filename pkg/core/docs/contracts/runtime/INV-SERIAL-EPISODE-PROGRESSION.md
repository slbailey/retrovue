# INV-SERIAL-EPISODE-PROGRESSION: Deterministic Serial Episode Continuity

**Classification:** INVARIANT (Scheduling / Episode Selection)
**Owner:** ScheduleManager / EpisodeResolver
**Enforcement Phase:** Schedule day resolution (EPG horizon extension)
**Depends on:** INV-SM-002 (Deterministic outputs), INV-P3-004 (State advances at resolution only)
**Created:** 2026-03-06

---

## Problem Statement

A serial program (e.g., a daily strip of *Bonanza*) must air episodes in
strict sequential order across the channel timeline.  If the scheduler is
offline for multiple days, the next resolution must still select the episode
that *would have* aired had the scheduler been running continuously.

The current `sequential` play mode uses an in-memory counter that increments
each time the resolver runs.  This counter is lost on process restart and
does not advance during scheduler downtime.  A scheduler offline Tuesday
through Thursday would resume on Friday with the counter stuck at Tuesday's
value, selecting the wrong episode.

Serial progression must be derived from the channel timeline — the number
of calendar occurrences since a known anchor — not from resolver invocation
history.

---

## Definition

A **Serial Run** binds a specific recurring program placement on a channel
timeline to an anchor point and progression policy.  Episode selection is
a pure computation over calendar dates and the run's configuration.  No
runtime counters, playlog history, or resolution order may influence the
result.

---

## Definitions

### Serial Run

A persistent record defining serial episode progression for one recurring
program placement.  Owned by Core.  Stored in the database.  Identified
by its placement identity.

### Placement Identity

The tuple that uniquely identifies a recurring strip on the timeline:

    (channel_id, placement_time, placement_days, content_source_id)

Where:

- `channel_id` — the channel this strip airs on.
- `placement_time` — time-of-day in schedule-time (HH:MM).
- `placement_days` — 7-bit day-of-week bitmask (bit 0 = Monday,
  bit 6 = Sunday).  Common values: 127 = daily, 31 = weekday,
  96 = weekend.
- `content_source_id` — identifier of the program, collection, or pool
  that provides episodes.

Two strips with overlapping content but different placement times or day
patterns are distinct placements with independent progression.

### Occurrence

A single calendar date where the placement pattern matches.  A date is
an occurrence if and only if the day-of-week bit for that date is set in
`placement_days`.

### Occurrence Count

The number of occurrences in the half-open interval `[anchor_date, target_date)`.
The anchor date itself is occurrence zero — it is counted but does not
contribute to the offset.

Formally:

    occurrence_count = count of dates d in [anchor_date, target_date)
                       where d.weekday() matches placement_days

The anchor date MUST be an occurrence (its day-of-week bit MUST be set).
The target date, if it is an occurrence, is included in the count.

### Anchor

A `(datetime, episode_index)` pair marking the origin of a serial run.
The anchor episode airs on the anchor date.  All subsequent episode
indices are computed as offsets from this point.

### Wrap Policy

Defines behavior when the computed episode index exceeds the episode
list length.  Three policies:

- **wrap** — modulo back to the beginning.
- **hold_last** — repeat the final episode indefinitely.
- **stop** — emit no content (filler) after the last episode.

### Episode List

An ordered sequence of episodes belonging to the content source.
Ordering is determined by the content catalog (season number, episode
number, absolute episode number).  The list is flat — season boundaries
are positions within the list, not structural divisions.

---

## Placement Identity Rules

### PI-001: Placement Uniqueness

> At most one active serial run may exist for a given placement identity.
>
>     UNIQUE (channel_id, placement_time, placement_days, content_source_id)
>        WHERE is_active = TRUE

### PI-002: Placement Independence

> Two serial runs with different placement identities MUST NOT influence
> each other.  Episode selection for one strip MUST NOT read or modify
> state belonging to another strip.

### PI-003: Scheduling Model Agnosticism

> The placement identity MUST be computable from both the Phase 3
> scheduling model (Program + Zone) and the DSL scheduling model
> (block + pool).  The episode resolver MUST NOT depend on which
> scheduling model produced the placement.

---

## Occurrence Counting Rules

### OC-001: Calendar-Based Counting

> Occurrence count MUST be computed from the calendar and the
> `placement_days` bitmask.  It MUST NOT depend on:
>
> - Playlog records
> - As-run logs
> - Resolution history
> - Scheduler uptime
> - The order in which dates are resolved

### OC-002: Anchor Date Is Occurrence Zero

> The anchor date MUST be a valid occurrence (its weekday bit MUST be set
> in `placement_days`).  The anchor date itself contributes zero offset —
> the anchor episode airs on the anchor date.
>
>     count_occurrences(anchor_date, anchor_date, placement_days) == 0

### OC-003: Counting Interval

> Occurrences are counted in the half-open interval `[anchor_date, target_date)`.
>
>     count_occurrences(anchor, target, mask) =
>         number of dates d where anchor <= d < target
>         and d.weekday() bit is set in mask
>
> The anchor date is the lower bound (inclusive) but since the interval
> is `[anchor, target)`, the anchor date is only counted when target > anchor.
> The target date is excluded from the count when used as the upper bound.
>
> For episode selection, the target is the broadcast day being resolved:
>
>     occurrence_count = count_occurrences(anchor_date, target_date, mask)
>
> This means the anchor date yields occurrence_count = 0 and the next
> matching day yields occurrence_count = 1.

### OC-004: Deterministic Computation

> The function `count_occurrences(anchor, target, mask)` MUST be a pure
> function.  Same inputs MUST always produce the same output.  The
> function MUST NOT access system time, mutable state, or external
> services.

### OC-005: Efficient Computation

> Occurrence counting SHOULD use arithmetic (full weeks × bits-per-week
> plus partial-week remainder) rather than date iteration.  The
> computation MUST be bounded regardless of the distance between anchor
> and target.

---

## Episode Selection Rule

> Given a serial run and a target broadcast day:
>
>     occurrence_count = count_occurrences(
>         serial_run.anchor_datetime.date(),
>         target_broadcast_day,
>         serial_run.placement_days,
>     )
>
>     raw_index = serial_run.anchor_episode_index + occurrence_count
>
>     episode = apply_wrap_policy(
>         raw_index,
>         episode_count,
>         serial_run.wrap_policy,
>     )
>
> This computation is the sole authority for serial episode identity.

---

## Wrap Policies

### WP-001: Wrap

>     effective_index = raw_index % episode_count

Episodes cycle back to the beginning after the last episode.

### WP-002: Hold Last

>     effective_index = min(raw_index, episode_count - 1)

The final episode repeats indefinitely once reached.

### WP-003: Stop

>     if raw_index >= episode_count:
>         return FILLER
>     effective_index = raw_index

No content after the last episode.  The schedule slot is filled with
filler material.

---

## Invariants

### INV-SERIAL-001: Deterministic Episode Selection

> Given the same serial run record, target broadcast day, and episode
> list, the selected episode MUST always be identical.  No runtime
> state, resolution history, or scheduler uptime may influence the
> result.

**Why:** This is the foundational guarantee.  If episode selection is not
deterministic, EPG identity becomes unstable, playlog cannot be
reconstructed, and serial continuity breaks across restarts.

---

### INV-SERIAL-002: Scheduler Downtime Independence

> If the scheduler is offline for N calendar days, the next resolution
> MUST select the episode corresponding to the correct occurrence count
> from the anchor — not the episode that would follow the last resolved
> episode.

**Why:** The occurrence counter counts calendar days, not resolver
invocations.  A scheduler offline Tuesday through Thursday still yields
occurrence_count = 4 when resolving Friday (for a daily strip anchored
on Monday).

---

### INV-SERIAL-003: Anchor Episode Consistency

> The anchor date MUST always resolve to the anchor episode, regardless
> of when or how many times it is resolved.
>
>     resolve(serial_run, anchor_date) == episodes[anchor_episode_index]

**Why:** The anchor is the fixed reference point.  If the anchor
resolution is inconsistent, all downstream episode indices are wrong.

---

### INV-SERIAL-004: Wrap Policy Determinism

> Wrap behavior MUST be deterministic and produce identical results for
> identical inputs.  The three policies (wrap, hold_last, stop) are
> mutually exclusive and exhaustive.

**Why:** An operator who sets `hold_last` expects the final episode to
repeat.  Nondeterministic wrap behavior would cause the EPG to show
different episodes on recomputation.

---

### INV-SERIAL-005: Placement Identity Stability

> A serial run's placement identity MUST NOT change unless the operator
> explicitly modifies the run record.  Schedule plan transitions,
> schedule rebuilds, and process restarts MUST NOT alter the placement
> identity or the episode progression.

**Why:** If the placement identity is derived from transient objects
(SchedulePlan.id, Program.id, window_uuid), it would break across
plan transitions.  The identity is defined by the strip's observable
properties (time, days, content), not by internal database keys.

---

### INV-SERIAL-006: Occurrence Counting Is Calendar-Based

> The occurrence count between anchor and target MUST be computed from
> the calendar and the placement_days bitmask only.  The computation
> MUST NOT depend on:
>
> - How many times `resolve_schedule_day()` has been called
> - Whether previous days were resolved
> - The order in which days are resolved
> - Playlog or as-run records

**Why:** This is what makes serial progression survive scheduler
downtime.  The calendar is always available; resolution history is not.

---

### INV-SERIAL-007: Anchor Must Match Placement Pattern

> The anchor datetime's day-of-week MUST have its bit set in the serial
> run's `placement_days` bitmask.
>
>     assert (1 << anchor_datetime.weekday()) & placement_days != 0

**Why:** If the anchor falls on a day the strip does not air, the
occurrence count is undefined.  The anchor must be a valid occurrence.

---

### INV-SERIAL-008: Season Boundaries Do Not Affect Progression

> The episode list is a flat ordered sequence.  Season numbers are
> editorial metadata only.  Serial progression walks the list by
> index without regard to season boundaries.
>
> A series with S01E01–S01E22 followed by S02E01–S02E24 is a single
> list of 46 episodes.  Episode at index 22 is S02E01.  No special
> logic fires at the season boundary.

**Why:** Broadcast strips do not pause or reset at season boundaries.
The strip runs through the full catalog.  Wrap/hold/stop policies
apply only when the entire list is exhausted.

---

## Architectural Integration

### Scheduling Resolution

Serial episode selection occurs during `ScheduleManager.resolve_schedule_day()`,
at the same point where the existing `_select_episode()` dispatches on
`play_mode`.  A new `serial` branch delegates to the episode resolver.

This preserves:

- **INV-P3-004:** State advances only at resolution time.
- **INV-P3-008:** Resolution idempotence (resolved days are cached).
- **INV-P3-002:** EPG identity is immutable once resolved.

### EPG Stability

Because serial selection is deterministic, the EPG shows the correct
episode at resolution time and that identity never changes.  Recomputing
the same day produces the same result (INV-SERIAL-001 + INV-P3-008).

### Playlog Generation

Playlog generation (Tier 2) is downstream of schedule resolution.  It
reads already-resolved episode identities.  Serial progression does not
change the playlog pipeline.

### Scheduling Model Compatibility

Both Phase 3 and DSL scheduling models produce the same placement
identity components:

| Component          | Phase 3 source         | DSL source           |
|--------------------|------------------------|----------------------|
| channel_id         | Program.channel_id     | channel config       |
| placement_time     | Program.start_time     | block.start          |
| placement_days     | Zone.day_filters → mask| schedule layer key → mask |
| content_source_id  | Program.content_ref    | block.pool           |

The episode resolver receives a placement identity and a serial run
record.  It does not know or care which scheduling model produced them.

---

## See Also

- [ScheduleManagerContract](ScheduleManagerContract.md)
- [INV-BLOCK-WALLCLOCK-FENCE-DISCIPLINE](INV-BLOCK-WALLCLOCK-FENCE-DISCIPLINE.md)
- [PlaylogEventContract](../resources/PlaylogEventContract.md)
- [MasterClockContract](../resources/MasterClockContract.md)
