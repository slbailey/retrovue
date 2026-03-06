# RetroVue Operator's Manual

## Overview

RetroVue is a linear television simulation platform that operates multi-channel broadcast networks. Channels run 24/7 on deterministic schedules, delivering MPEG-TS streams to viewers on demand. The system models how real broadcast stations operate: schedules advance with the wall clock regardless of whether anyone is watching, and viewers join programs already in progress.

The `retrovue` CLI is the primary tool for operators to inspect, diagnose, and correct scheduling behavior across all channels.

### Scheduling Tier Model

RetroVue processes schedules through three tiers. Each tier transforms editorial intent into progressively more concrete playout instructions.

| Tier | Name | Description |
|------|------|-------------|
| **Tier-1** | Editorial Schedule | The compiled broadcast schedule for a channel and broadcast day. Defines what airs, when, and for how long. Produced from channel programming definitions. |
| **Tier-2** | Playout Segments | The fully segmented, playout-ready block list. Each editorial slot is expanded into ordered segments (intros, content, filler) with resolved asset paths and durations. |
| **Tier-3** | Runtime Execution | The real-time byte stream delivered to viewers. The playout engine reads Tier-2 segments and emits MPEG-TS frames at the correct offsets and timing. |

Operators primarily interact with Tier-1 and Tier-2. Tier-3 is managed by the playout engine and requires no direct operator intervention under normal conditions.

---

## Operator Workflow Overview

The standard troubleshooting workflow follows three steps:

1. **Explain** the scheduling decision for a channel at a specific time.
2. **Preview** the playout segments that will be generated for that time slot.
3. **Rebuild** Tier-2 segments if the preview reveals incorrect behavior.

This sequence allows operators to diagnose issues without modifying any state (steps 1 and 2 are read-only), and to apply targeted corrections only when necessary (step 3).

```
Investigate              Validate                 Correct
+-----------------+      +-----------------+      +-----------------+
| schedule explain| ---> | schedule preview| ---> | schedule rebuild |
+-----------------+      +-----------------+      +-----------------+
   (read-only)              (read-only)             (writes Tier-2)
```

---

## Command Reference

### `retrovue schedule explain`

#### Purpose

Displays the editorial scheduling decision for a channel at a specific time. Shows which Tier-1 schedule revision is active, which slot covers the requested time, and how the block will be expanded into playout segments.

This is the first command to use when investigating unexpected scheduling behavior.

#### Syntax

```
retrovue schedule explain \
    --channel CHANNEL \
    --time TIMESTAMP \
    [--json]
```

#### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--channel`, `-c` | Yes | -- | Channel identifier (e.g., `hbo-classics`) |
| `--time` | Yes | -- | Time to inspect. Use `now` for the current time, or an ISO-8601 timestamp (e.g., `2026-03-06T14:30:00+00:00`) |
| `--json` | No | `false` | Output in JSON format for scripting or further analysis |

#### Examples

Explain what is currently airing on a channel:

```
retrovue schedule explain --channel hbo-classics --time now
```

Explain what was scheduled for a specific time:

```
retrovue schedule explain --channel hbo-classics --time 2026-03-06T20:00:00+00:00
```

Output as JSON for integration with other tools:

```
retrovue schedule explain --channel hbo-classics --time now --json
```

#### Example Output

**Template block (modern scheduling path):**

```
=== Schedule Explain: hbo-classics at 2026-03-06T20:15:00+00:00 ===

Tier 1 (ScheduleRevision)
  Revision ID:    a3f8c912-44b1-4e7a-9c2d-18e5f3a7b6d0
  Broadcast day:  2026-03-06
  Status:         active
  Created by:     dsl_schedule_service

ScheduleItem (slot 4)
  Title:          Weekend at Bernie's
  Template:       hbo_feature_with_intro
  Content type:   movie
  Slot:           2026-03-06 20:00 UTC -> 2026-03-06 22:00 UTC
  Duration:       7200s
  Asset ID:       c7e2a1f4-9b3d-4f8e-a612-5d4c3b2a1e0f

Expansion path:   compiled_segments (template)

Compiled segments (2):
  0: [intro] intro-hbo-001  dur=30000ms  source=collection:Intros
  1: [content] movie-001  dur=5400000ms  source=pool:hbo_movies  [PRIMARY]
```

**Legacy block (older scheduling path):**

```
=== Schedule Explain: cheers-24-7 at 2026-03-06T14:30:00+00:00 ===

Tier 1 (ScheduleRevision)
  Revision ID:    f1d2e3c4-5a6b-7c8d-9e0f-1a2b3c4d5e6f
  Broadcast day:  2026-03-06
  Status:         active
  Created by:     dsl_schedule_service

ScheduleItem (slot 12)
  Title:          Cheers S03E12
  Template:       (none - legacy block)
  Content type:   episode
  Slot:           2026-03-06 14:00 UTC -> 2026-03-06 14:30 UTC
  Duration:       1800s
  Asset ID:       d8f3b2a1-6c5e-4d7f-8a9b-0c1d2e3f4a5b

Expansion path:   expand_program_block (legacy)

Legacy expansion info:
  Asset ID (raw): cheers-s03e12
  Episode dur:    1320s
  Note:           Block will be expanded at runtime via heuristic expansion
```

#### Operational Importance

`schedule explain` answers the question: *"Why is this program airing right now?"* It reveals the full editorial chain from the active schedule revision down to the specific slot and template structure. When a channel is behaving unexpectedly, this command shows whether the issue originates in the editorial schedule (wrong asset, wrong time slot) or in the segment expansion path (wrong template, missing compiled segments).

---

### `retrovue schedule preview`

#### Purpose

Generates and displays the Tier-2 playout segments for the block covering a specified time, without writing anything to the database. This shows exactly what the playout engine will receive for a given time slot.

#### Syntax

```
retrovue schedule preview \
    --channel CHANNEL \
    --time TIMESTAMP \
    [--json]
```

#### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--channel`, `-c` | Yes | -- | Channel identifier (e.g., `hbo-classics`) |
| `--time` | Yes | -- | Time within the block to preview. Use `now` or an ISO-8601 timestamp |
| `--json` | No | `false` | Output in JSON format |

#### Examples

Preview the current playout block:

```
retrovue schedule preview --channel hbo-classics --time now
```

Preview a future block:

```
retrovue schedule preview --channel hbo-classics --time 2026-03-06T22:00:00+00:00
```

#### Example Output

```
=== Segment Preview: hbo-classics at 2026-03-06T20:15:00+00:00 ===

Block:    blk-a1b2c3d4e5f6
Start:    2026-03-06 20:00 UTC
End:      2026-03-06 22:00 UTC
Duration: 7200000ms
Segments: 3

IDX   TYPE         START                      DURATION     ASSET
------------------------------------------------------------------------------------------
0     intro        2026-03-06 20:00 UTC       30s          /media/intros/hbo-intro.mp4
1     content      2026-03-06 20:00 UTC       1h30m00s     /media/movies/weekend-bernies.mp4
2     filler       2026-03-06 21:30 UTC       29m30s       /media/filler/hbo-filler.mp4
```

#### Operational Importance

`schedule preview` answers the question: *"What segments will the playout engine actually play for this block?"* It shows the fully expanded segment list including intros, content, filler, and any ad break placements. This is essential for validating that template changes, segment compilation fixes, or editorial corrections produce the expected playout behavior before they reach viewers.

---

### `retrovue schedule rebuild`

#### Purpose

Regenerates Tier-2 playout segments for a channel within a specified time window. This replaces existing Tier-2 data with freshly computed segments derived from the current Tier-1 editorial schedule.

Tier-2 rebuilds are the primary mechanism for applying scheduling logic fixes (such as template compilation corrections) to channels that are already running, without restarting any services or modifying the editorial schedule.

#### Syntax

```
retrovue schedule rebuild \
    --channel CHANNEL \
    --tier TIER \
    [--from TIMESTAMP] \
    [--to TIMESTAMP] \
    [--live-safe] \
    [--dry-run]
```

#### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `--channel`, `-c` | Yes | -- | Channel identifier (e.g., `hbo-classics`) |
| `--tier`, `-t` | Yes | -- | Scheduling tier to rebuild. Currently only `2` is supported |
| `--from` | No | `now` | Start of the rebuild window. Use `now` or an ISO-8601 timestamp |
| `--to` | No | `horizon` | End of the rebuild window. Use `horizon` (3 hours from start) or an ISO-8601 timestamp |
| `--live-safe` | No | `false` | If the start time falls within a currently playing block, shift the rebuild window forward to avoid interrupting active playout |
| `--dry-run` | No | `false` | Report what would be changed without modifying any data |

#### The Rebuild Window

The rebuild window defines the range of Tier-2 blocks that will be deleted and regenerated. Only blocks whose start time falls within `[--from, --to)` are affected. Blocks before the window (including past blocks) and blocks after the window are untouched.

```
Past                Now          Rebuild Window              Future
  |---played----|----playing----|====REBUILD====|-------------|
                                ^               ^
                              --from           --to
```

When `--to` is set to `horizon` (the default), the rebuild window extends 3 hours from the start time. This matches the playout horizon maintained by the system's background scheduling process.

#### Examples

Rebuild Tier-2 segments from now forward (default 3-hour horizon):

```
retrovue schedule rebuild --channel hbo-classics --tier 2 --from now
```

Rebuild a specific time range:

```
retrovue schedule rebuild \
    --channel hbo-classics \
    --tier 2 \
    --from 2026-03-06T18:00:00+00:00 \
    --to 2026-03-07T06:00:00+00:00
```

Preview what a rebuild would change without making modifications:

```
retrovue schedule rebuild \
    --channel hbo-classics \
    --tier 2 \
    --from now \
    --dry-run
```

Rebuild from now, but protect the currently playing block:

```
retrovue schedule rebuild \
    --channel hbo-classics \
    --tier 2 \
    --from now \
    --live-safe
```

#### Example Output

**Standard rebuild:**

```
Rebuilding Tier-2 for hbo-classics
  Window: 2026-03-06T16:44:45.517371+00:00 -> 2026-03-06T19:44:45.517371+00:00
  Deleted: 4 Tier-2 block(s)
  Rebuilt: 4 Tier-2 block(s)
```

**Dry run:**

```
DRY RUN: Tier-2 rebuild for hbo-classics
  Window: 2026-03-06T16:44:45.517371+00:00 -> 2026-03-06T19:44:45.517371+00:00
  Would delete: 4 Tier-2 block(s)
  No changes written.
```

**Live-safe with active playout:**

```
Rebuilding Tier-2 for hbo-classics
  Window: 2026-03-06T16:44:45.517371+00:00 -> 2026-03-06T19:44:45.517371+00:00
  Live-safe: enabled (will skip currently playing block)
  Deleted: 3 Tier-2 block(s)
  Rebuilt: 3 Tier-2 block(s)
  Live-safe: start shifted past currently playing block
```

#### Operational Importance

`schedule rebuild` is the corrective action tool. After confirming a scheduling issue with `explain` and `preview`, operators use `rebuild` to regenerate the affected Tier-2 segments. The key properties are:

- **Non-disruptive**: Tier-1 editorial data is never modified. Only Tier-2 playout segments are replaced.
- **Targeted**: Only blocks within the specified window are affected. Past blocks and unrelated channels are untouched.
- **Safe**: The `--live-safe` flag prevents modification of a block that is currently being streamed to viewers. The `--dry-run` flag allows previewing the impact before committing.
- **Instant**: Rebuilds only process blocks within the specified window, not the entire schedule. Completion is near-instant even for channels with large schedules.

---

## Example Troubleshooting Scenario

### Problem: Channel inserting commercial breaks mid-movie

An operator receives a report that the HBO Classics channel is inserting commercial breaks in the middle of feature films. Movies should play uninterrupted with only an intro bumper before the feature.

#### Step 1: Explain the scheduling decision

```
retrovue schedule explain --channel hbo-classics --time now
```

```
=== Schedule Explain: hbo-classics at 2026-03-06T20:45:00+00:00 ===

Tier 1 (ScheduleRevision)
  Revision ID:    a3f8c912-44b1-4e7a-9c2d-18e5f3a7b6d0
  Broadcast day:  2026-03-06
  Status:         active
  Created by:     dsl_schedule_service

ScheduleItem (slot 4)
  Title:          Caddyshack
  Template:       hbo_feature_with_intro
  Content type:   movie
  Slot:           2026-03-06 20:00 UTC -> 2026-03-06 22:00 UTC
  Duration:       7200s
  Asset ID:       b4e7d2c1-8a3f-4b6e-9d1c-5f2a8e7b3c0d

Expansion path:   compiled_segments (template)

Compiled segments (2):
  0: [intro] intro-hbo-001  dur=30000ms  source=collection:Intros
  1: [content] movie-002  dur=5880000ms  source=pool:hbo_movies  [PRIMARY]
```

**Finding**: The Tier-1 schedule is correct. The block uses the `hbo_feature_with_intro` template with two compiled segments (intro + content). There should be no commercial breaks.

#### Step 2: Preview the playout segments

```
retrovue schedule preview --channel hbo-classics --time now
```

```
=== Segment Preview: hbo-classics at 2026-03-06T20:45:00+00:00 ===

Block:    blk-d4e5f6a7b8c9
Start:    2026-03-06 20:00 UTC
End:      2026-03-06 22:00 UTC
Duration: 7200000ms
Segments: 74

IDX   TYPE         START                      DURATION     ASSET
------------------------------------------------------------------------------------------
0     content      2026-03-06 20:00 UTC       7m20s        /media/movies/caddyshack.mp4
1     ad_break     2026-03-06 20:07 UTC       2m00s        /media/filler/hbo-filler.mp4
2     content      2026-03-06 20:09 UTC       7m20s        /media/movies/caddyshack.mp4
3     ad_break     2026-03-06 20:17 UTC       2m00s        /media/filler/hbo-filler.mp4
...
```

**Finding**: The Tier-2 segments show the movie broken into 74 segments with commercial breaks every few minutes. This indicates the Tier-2 data was generated before the template compilation fix was applied. The stale Tier-2 data is using the legacy expansion path (which treats movies as network episodes with ad breaks) instead of honoring the compiled template segments.

#### Step 3: Rebuild Tier-2 segments

First, preview the rebuild to confirm scope:

```
retrovue schedule rebuild \
    --channel hbo-classics \
    --tier 2 \
    --from now \
    --dry-run
```

```
DRY RUN: Tier-2 rebuild for hbo-classics
  Window: 2026-03-06T20:45:00+00:00 -> 2026-03-06T23:45:00+00:00
  Would delete: 3 Tier-2 block(s)
  No changes written.
```

Apply the rebuild with live-safe to protect the currently playing block:

```
retrovue schedule rebuild \
    --channel hbo-classics \
    --tier 2 \
    --from now \
    --live-safe
```

```
Rebuilding Tier-2 for hbo-classics
  Window: 2026-03-06T20:45:00+00:00 -> 2026-03-06T23:45:00+00:00
  Live-safe: enabled (will skip currently playing block)
  Deleted: 2 Tier-2 block(s)
  Rebuilt: 2 Tier-2 block(s)
  Live-safe: start shifted past currently playing block
```

#### Step 4: Verify the fix

```
retrovue schedule preview --channel hbo-classics --time 2026-03-06T22:00:00+00:00
```

```
=== Segment Preview: hbo-classics at 2026-03-06T22:00:00+00:00 ===

Block:    blk-e5f6a7b8c9d0
Start:    2026-03-06 22:00 UTC
End:      2026-03-07 00:00 UTC
Duration: 7200000ms
Segments: 3

IDX   TYPE         START                      DURATION     ASSET
------------------------------------------------------------------------------------------
0     intro        2026-03-06 22:00 UTC       30s          /media/intros/hbo-intro.mp4
1     content      2026-03-06 22:00 UTC       1h46m00s     /media/movies/ghostbusters.mp4
2     filler       2026-03-06 23:46 UTC       13m30s       /media/filler/hbo-filler.mp4
```

**Result**: The next block now shows the correct template structure: intro, uninterrupted movie, and post-content filler. The currently playing block (Caddyshack with commercial breaks) was protected by `--live-safe` and will complete as-is. All subsequent blocks use the corrected template expansion.

---

## Best Practices

**Always use `--dry-run` before large rebuilds.** Preview the scope of a rebuild before committing changes. This is especially important when rebuilding wide time windows or during peak viewing hours.

**Use `--live-safe` when rebuilding during active playout.** Without this flag, the currently playing block may be replaced mid-stream, which can cause a brief interruption for connected viewers. The `--live-safe` flag automatically shifts the rebuild window past the active block.

**Use `preview` to validate template changes before rebuilding.** After making changes to channel programming definitions, run `schedule preview` on a few representative time slots to confirm the segments are structured correctly before triggering a rebuild.

**Investigate before rebuilding.** Always run `schedule explain` first. If the Tier-1 editorial data is wrong (incorrect asset, wrong time slot), a Tier-2 rebuild will reproduce the same error. Tier-1 issues require recompilation of the channel programming definition, not a Tier-2 rebuild.

**Rebuild the smallest necessary window.** Use `--from` and `--to` to target only the affected time range. The default 3-hour horizon is appropriate for most corrections. Expanding the window unnecessarily increases the number of blocks processed and replaced.

**Use JSON output for automation.** The `--json` flag on `explain` and `preview` produces machine-readable output suitable for integration with monitoring dashboards, alerting systems, or batch correction scripts.

---

## Glossary

| Term | Definition |
|------|------------|
| **Channel** | A persistent broadcast entity with a 24/7 schedule. Channels advance with wall-clock time regardless of whether viewers are connected. |
| **Block** | A contiguous time slot in the schedule, typically 30 minutes to 3 hours. Each block contains one or more segments. |
| **Segment** | An individual playout unit within a block. Segments have a type (intro, content, filler), an asset reference, a duration, and a start offset. |
| **Template** | A reusable segment structure that defines the composition of a block (e.g., "intro followed by movie"). Templates are resolved at compile time into explicit segment lists. |
| **Tier-1** | The editorial schedule. Defines what airs on each channel for each broadcast day. Produced by compiling channel programming definitions. |
| **Tier-2** | The playout segment list. Each Tier-1 slot is expanded into an ordered sequence of segments with resolved assets and precise durations. Tier-2 is what the playout engine reads. |
| **Tier-3** | Runtime playout execution. The playout engine reads Tier-2 segments and emits MPEG-TS frames to viewers in real time. |
| **Playout horizon** | The amount of Tier-2 data maintained ahead of the current time. The system continuously ensures at least 3 hours of Tier-2 coverage for each active channel. |
| **Broadcast day** | A logical scheduling day, typically starting at 06:00 local time. Programs airing between midnight and 06:00 belong to the previous broadcast day. |
| **Compiled segments** | A pre-resolved segment list attached to template-derived blocks at Tier-1 compile time. Compiled segments bypass runtime heuristic expansion and are used directly by Tier-2 generation. |
