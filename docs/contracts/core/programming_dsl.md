# Contract: Programming DSL & Schedule Compiler

**Status:** Draft v2 – Two-tier architecture

## Purpose
Define the human-editable YAML language for describing channel programming grids and the two-tier schedule architecture that transforms DSL into playout instructions.

## Two-Tier Schedule Architecture

### Tier 1: Program Schedule (compiled from DSL)
- **Rolling horizon:** 3–4 calendar days
- **Content:** Grid-aligned program block assignments ONLY
- **Grid alignment:** Episodes MUST start on grid boundaries
  - Network TV: `:00` / `:30`
  - Premium Movie: `:00` / `:15`
- **No breaks, no commercials, no bumpers** — this is what an EPG would show
- **Produced by:** `schedule_compiler.py`

### Tier 2: Playout Log (expanded from program schedule)
- **Rolling horizon:** 3–4 program blocks ahead of "now"
- **Content:** Acts (from chapter markers) interleaved with empty ad block slots
- **Produced by:** `playout_log_expander.py` (Schedule Manager calls this)
- **Consumed by:** Channel Manager → Air

### Traffic Manager (fills ad blocks)
- Takes a program block's total remaining time (`slot_duration - episode_runtime`) and splits equally across ad block slots
- **v1:** Fills each ad block by looping `filler.mp4`; pads remainder with black frames
- **Example:** 30-min slot, 22:00 episode, 3 chapter breaks → 8:00 ads → 2:40 per block

## Program Block Concept
A **program block** is one complete content piece regardless of how many grid slots it occupies:
- 22-min sitcom = 1 program block, 1 grid slot (30 min)
- 60-min drama = 1 program block, 2 grid slots (60 min)
- 2-hour movie = 1 program block, 4+ grid slots

## Time Model
- Broadcast day runs 06:00 → next day 06:00 (local zone).
- Time math is computed in UTC; display/render happens in the channel's timezone.
- Daylight Saving shifts keep wall-clock alignment.

## Methodology Alignment
- **What:** This contract.
- **Tests:** `pkg/core/tests/runtime/test_schedule_compiler.py`, `test_playout_log_expander.py`, `test_traffic_manager.py`
- **Code:** `schedule_compiler.py`, `playout_log_expander.py`, `traffic_manager.py`
- **Runtime hookup:** ScheduleService loads compiled plans via an injected `AssetResolver`.

## Requirements

### DSL Syntax (YAML primary, JSON equivalent)
1. Regular blocks (time-of-day to program mapping)
2. Reusable templates (e.g., `weeknight_block`)
3. Selector clauses (`episode_selector`, `movie_selector`) for rule-based pulls
4. Channel templates (`network_television`, `premium_movie`) establishing grid boundaries
5. Optional namespaces (`analytics`, `sponsorships`) reserved for future add-ons
6. `notes` blocks are human-only, ignored by compiler

### Asset Resolution
- Every `program`, `collection`, etc. resolves via `AssetResolver` interface
- Tests use `StubAssetResolver`; production uses live catalog
- Missing/invalid references are fatal errors

### Validation
- Missing programs/assets (resolver miss)
- Time overlaps/gaps
- Grid alignment violations
- Asset constraints (runtime longer than slot)

### Output: Program Schedule
The compiler outputs a **Program Schedule** — grid-aligned program blocks only. No breaks, packaging, promos, or filler segments.

## Example DSL

### Weeknight Sitcom Block
```yaml
channel: retro_prime
broadcast_day: 1989-10-12
timezone: America/New_York
notes:
  vibe: "Water-cooler Thursday"

templates:
  weeknight_sitcom_block:
    start: "20:00"
    slots:
      - title: "Cosby Show"
        program: p.coz_s3
        episode_selector:
          collection: col.cozby_show_s3
          mode: sequential
      - title: "Cheers"
        program: p.cheers_s6
        episode_selector:
          collection: col.cheers_s6
          mode: random
      - title: "Taxi"
        program: p.taxi_s2
        episode_selector:
          collection: col.taxi_s2
          mode: random

schedule:
  weeknights:
    use: weeknight_sitcom_block
```

### Weekend Movie Night
```yaml
channel: retro_movies
broadcast_day: 1989-10-14
timezone: America/New_York
template: premium_movie

schedule:
  saturday:
    - start: "20:00"
      movie_selector:
        collections:
          - col.movies.blockbusters_70s_90s
          - col.movies.family_adventure
        rating:
          include: [PG, PG-13]
        min_cooldown_days: 21
        max_duration_sec: 7200
    - start: "22:30"
      movie_selector:
        collections:
          - col.movies.late_night_thrillers
        rating:
          include: [R]
        min_cooldown_days: 45
        max_duration_sec: 9000
```

## Program Schedule Output Schema (v2)
```json
{
  "version": "program-schedule.v2",
  "channel_id": "retro_prime",
  "broadcast_day": "1989-10-12",
  "timezone": "America/New_York",
  "source": {
    "dsl_path": "programming/retro_prime/weeknights.yaml",
    "git_commit": "abc1234",
    "compiler_version": "2.0.0"
  },
  "program_blocks": [
    {
      "title": "The Cosby Show",
      "asset_id": "asset.episodes.coz_s3e01",
      "start_at": "1989-10-12T20:00:00-04:00",
      "slot_duration_sec": 1800,
      "episode_duration_sec": 1320,
      "collection": "col.cozby_show_s3",
      "selector": {
        "mode": "sequential",
        "seed": 42
      }
    }
  ],
  "hash": "sha256:..."
}
```

## Playout Log Expansion
Given a program block + asset metadata with chapter markers:
1. Read chapter markers from asset metadata (`chapter_markers_sec`)
2. If no chapter markers: approximate by dividing episode evenly
3. Split episode into acts at chapter boundaries
4. Calculate total ad time = `slot_duration_sec - episode_duration_sec`
5. Distribute ad time equally across inter-act breaks
6. Output: `[act1, ad_block, act2, ad_block, ..., actN]`

## Traffic Manager v1
For each empty ad block in the playout log:
1. Loop `filler.mp4` to fill the ad block duration
2. If filler doesn't fill precisely, pad remainder with black frames
3. Output: playout log with filled ad blocks

## Channel Templates
- **Network Television** – 30-minute grid, ad-supported
- **Premium Movie** – 15-minute grid, no commercial breaks in program schedule

## Selector Semantics
- **Episode selectors:** `collection` + `mode` (`sequential`, `random`, `weighted`)
- **Movie selectors:** `collections`, `rating` filters, duration constraints, cooldown knobs

## Asset Resolver Contract
- `AssetResolver.lookup(asset_id) -> AssetMetadata`
- `AssetMetadata` includes `chapter_markers_sec: tuple[float, ...] | None` for playout expansion

## Next Steps
- [ ] Review with Steve; capture sign-off date
- [ ] Implement playout log expansion in Schedule Manager
- [ ] Implement Traffic Manager v1
