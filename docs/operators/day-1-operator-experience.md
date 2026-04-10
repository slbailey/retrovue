# Day 1 Operator Experience — Walkthrough Guide

> **Purpose:** Before implementing the RETA-62 Simplified Asset Management plan, this guide walks through the complete Day 1 experience from an operator's perspective. It validates that the proposed CLI surface, state transitions, and feedback loops feel coherent and intuitive before any code is written.
>
> **Reference:** [RETA-62 plan](/RETA/issues/RETA-62#document-plan) — Simplified Asset Management (v10, revised for RETA-69)

---

## Prerequisites

The operator has:
- A running RetroVue instance with Postgres and ffmpeg available
- Media files accessible on a local or network path (or a Plex server)
- The `retrovue` CLI installed

---

## Scenario 1 — "I added my Plex server"

**Operator goal:** Connect Plex and have content just show up.

### Step 1: Connect the source

```
$ retrovue source add --type plex --url http://plex.local:32400 --token abc123
✓ Connected to Plex server "Living Room"
  Found 3 containers: Movies (847), TV Shows (124), Music Videos (31)
```

The system discovers Plex containers (libraries in Plex's terminology) and reports item counts. No media is ingested yet — the operator chooses what to import.

> **Under the hood:** `source add` delegates to the `SourceIngestService` workflow, which registers the source and runs container discovery. No domain logic lives in the CLI command (INV-CLI-NO-BUSINESS-LOGIC-001).

### Step 2: Import a container

```
$ retrovue source import "Movies"

Importing "Movies" from source "Living Room" (847 items)...
  Ingested:   847 / 847
  Validating...
  ✅ Ready:       791  (93.4%)
  ⚠️  Warnings:    38  (4.5%)
  ❌ Failed:       18  (2.1%)

791 assets are schedulable now. 38 passed with warnings. 18 need attention.
Run `retrovue asset list --errors` to see failures.
```

> **Disambiguation:** If multiple sources contain a container named "Movies", the CLI returns a hard error listing the matches and suggests adding `--source <name-or-id>` to specify which source. For example: `retrovue source import "Movies" --source "Living Room"`. No interactive prompting — the CLI stays scriptable.

**What happened under the hood:**

```
ContainerIngestService → Validate (4 core validators) → Auto-Approve → Enrich (immediate enrichers)
```

Each asset moved through the state machine:

| Count | Path | Meaning |
|-------|------|---------|
| 791 | `new → validated → approved → ready` | Broadcast-ready, no issues |
| 38 | `new → validated (warnings) → approved → ready` | Broadcast-ready, minor warnings (e.g., low bitrate) |
| 18 | `new → validation failed` | Failed validation, not schedulable |

Auto-approve is the default. The `validated → approved → ready` transition happens in one pass. To require manual approval instead, use `--manual-approve` — assets will stop at `validated` and await explicit approval.

### What "ready" means

An asset is **ready** when:
1. All 4 core validators pass (Duration, Codec, Container, Playability) — per INV-VALIDATOR-OUTPUT-SHAPE-001
2. The operator (or auto-approve) has approved it — per the approval model

Ready assets can be scheduled on any channel. They may still have warnings (non-blocking observations) and may gain richer metadata over time via enrichment. Enrichment is orthogonal to readiness — an asset with zero enrichments complete is still fully schedulable (INV-CATALOG-READY-SCHEDULABLE-001).

### What "warnings" mean

Warnings are informational. The asset is fully schedulable but the system noticed something the operator might want to know — e.g., low bitrate, unusual aspect ratio, single audio channel. Warnings never block scheduling.

### What "failed" means

At least one core validator returned an error. The asset cannot be scheduled until the error is resolved and validation passes. Errors include machine-readable codes and human-readable messages (INV-VALIDATOR-OUTPUT-SHAPE-001).

### UX verification

- [ ] Does the operator understand the summary without reading docs?
- [ ] Is the 80–90% auto-ready target met for typical Plex libraries?
- [ ] Is the next step obvious? (look at failures, or start scheduling)

---

## Scenario 2 — "Something failed validation"

**Operator goal:** Understand what failed and fix it without frustration.

### Step 1: List failures

```
$ retrovue asset list --errors

ID     Title              Status   Error
----   ----------------   ------   ---------------------------
1023   Die Hard           new      MISSING_AUDIO_CODEC: No audio stream detected
1045   Ghostbusters       new      UNKNOWN_CONTAINER: Container format not recognized
1099   Aliens             new      INVALID_DURATION: Duration = 0
1102   The Thing          new      PLAYABILITY_FAIL: Stream probe could not read video
```

Every error has a machine-readable code (from INV-VALIDATOR-OUTPUT-SHAPE-001) and a human message. The operator can immediately see *what* is wrong.

> **Note:** `--errors` shows all assets with validation errors regardless of status. The output includes the status column so the operator can see where each asset is in the state machine. Assets that failed validation remain in `new` status — they never advance to `validated`.

### Step 2: Inspect a specific asset

```
$ retrovue asset inspect 1023

Asset: Die Hard (1023)
Status: new
Source: plex / Movies / Die Hard (1988)
File:   /media/movies/Die Hard (1988)/Die.Hard.1988.mkv

Validation:
  duration:    pass
  codec:       FAIL — MISSING_AUDIO_CODEC: No audio stream detected
  container:   pass
  playability: pass

Warnings: none
Enrichment: not started (requires validation + approval)
```

The output tells the operator:
- **Which** validator failed (`codec`)
- **Why** it failed (`MISSING_AUDIO_CODEC`)
- **What** the message means (`No audio stream detected`)

### Step 3: Fix and re-validate

The operator replaces the file with a corrected version (or re-encodes it):

```
$ retrovue asset validate 1023

Validating Die Hard (1023)...
  duration:    pass
  codec:       pass (was: FAIL)
  container:   pass
  playability: pass

✅ Asset validated. Status: validated → approved → ready (auto-approved)
```

If auto-approve is on, the asset moves straight through to `ready`. Otherwise:

```
✅ Asset validated. Status: validated (awaiting approval)
   Run `retrovue asset approve 1023` to make it schedulable.
```

### Batch operations

Operators can re-validate all assets with errors at once:

```
$ retrovue asset validate --errors

Validating 18 assets with errors...
  ✅ Fixed:  12
  ❌ Still failing: 6
```

> **Disambiguation:** To scope re-validation to a specific container, use `--container "Movies"`. If the container name exists in multiple sources, add `--source "Living Room"` to disambiguate. The CLI returns a hard error on ambiguity — no silent guessing.

### UX verification

- [ ] Is every error message understandable without documentation?
- [ ] Is the next step (fix file, re-validate) obvious from the output?
- [ ] Does the operator feel *guided* rather than blocked?
- [ ] Can an operator go from "18 failures" to "0 failures" in a single focused session?

---

## Scenario 3 — "I just want stuff to show up on TV"

**Operator goal:** Minimum effort → content airs on a channel.

### The 3-command path

```
$ retrovue source import "Movies"
  ✅ Ready: 791 assets

$ retrovue channel create "Movie Channel"
  ✓ Channel "Movie Channel" created (id: movie-channel)

$ retrovue schedule auto "Movie Channel" --container "Movies"
  ✓ Generated schedule YAML: channels/movie-channel.yaml
    Default pool: "Movies" (791 eligible assets)
    Schedule: 24h continuous rotation
    First program: The Shawshank Redemption @ 00:00:00
```

That's it. The channel is live.

> **Note on `schedule auto`:** This is the quick-start exception, not the standard channel development methodology. `schedule auto` generates a YAML file containing a default pool and a 24-hour rotation schedule. The YAML file is editable and modifiable — this just gets the ball rolling. Full channel development (custom pools, editorial scheduling, zone-based grids) is covered separately.

> **Note:** The `--container` flag specifies which container to draw assets from. If the container name is ambiguous across sources, add `--source "Living Room"` to disambiguate (per RETA-78).

### What the system does

1. **Asset eligibility:** Only assets that are `ready` (validated + approved) are considered. Failed and unapproved assets are silently excluded.
2. **YAML generation:** `schedule auto` creates a channel YAML file with a default pool definition and a 24-hour rotation schedule. The pool draws from the specified container and filters by readiness.
3. **Enrichment:** Immediate enrichers (ffprobe metadata, interstitial classification) run as soon as the asset reaches `ready`. Background enrichers (loudness analysis) run via a worker queue. The operator doesn't need to wait — enrichment never blocks scheduling (INV-CATALOG-READY-SCHEDULABLE-001, INV-ENRICHER-EXECUTION-MODE-001).
4. **Schedule generation:** The auto-scheduler fills 24h of programming using eligible assets from the pool.
5. **Continuous playback:** The channel advances with the wall clock. Viewers join mid-program and see content at the correct offset, as if tuning into live TV.

### What the operator does NOT need to think about

- Validation (handled automatically during import)
- Enrichment (runs in background, never blocks scheduling)
- Failed assets (silently excluded — they never appear on air)

### The trust contract

> **If it's marked `ready`, it will eventually air.**

The operator can trust `ready` because:
- 4 core validators confirmed the asset is playable
- The playback pipeline (ffmpeg) can demux and decode it
- It has been explicitly or auto-approved

### UX verification

- [ ] Can the operator go from zero to a running channel in under 5 minutes?
- [ ] Does the operator trust that "ready" assets will actually play?
- [ ] Does the operator need to understand validation, enrichment, or pools to get started? (Answer should be: no — `schedule auto` handles pool creation via YAML)

---

## Scenario 4 — "Why isn't my asset airing?"

**Operator goal:** Trace exactly why a specific asset isn't appearing on their channel, in under 10 seconds.

### The diagnostic command

```
$ retrovue asset inspect 1045
```

The system returns a complete status picture. There are exactly 4 possible reasons an asset isn't airing on Day 1 (policies add a 5th reason in a future phase), and the output makes each one unambiguous:

### Case 1 — Not validated (validation error)

```
Asset: Ghostbusters (1045)
Status: new (validation failed)

Validation:
  duration:    pass
  codec:       pass
  container:   FAIL — UNKNOWN_CONTAINER: Container format "rmvb" not recognized
  playability: skipped (container failed)

Enrichment: not started (requires validation + approval)

Not schedulable: fix the container format and re-validate.
Run: retrovue asset validate 1045
```

**Operator reads:** "Container isn't supported. Replace the file."
**Time to answer:** ~3 seconds.

### Case 2 — Validated but not approved

```
Asset: Ghostbusters (1045)
Status: validated (awaiting approval)

Validation: all pass
Approval: pending

Enrichment: not started (requires approval)

Not schedulable: needs approval.
Run: retrovue asset approve 1045
```

**Operator reads:** "It passed validation but I haven't approved it."
**Time to answer:** ~2 seconds.

### Case 3 — Ready but not in a pool for this channel

```
Asset: Ghostbusters (1045)
Status: ready
Approval: approved

Enrichment:
  ffprobe:           complete
  interstitial_type: complete
  loudness:          complete

Pools: none (not assigned to any pool)

Asset is fully eligible but not in any pool connected to a channel.
Run: retrovue pool add-assets "Movie Pool" --asset 1045
```

**Operator reads:** "Nothing is wrong. I just haven't added it to a pool."
**Time to answer:** ~3 seconds.

### Case 4 — Ready, in pool, but not yet scheduled

```
Asset: Ghostbusters (1045)
Status: ready
Approval: approved
Pools: Movie Pool

Enrichment:
  ffprobe:           complete
  interstitial_type: complete
  loudness:          running (background)

Schedule: not yet selected by auto-scheduler
The asset is eligible and in a pool. It will be scheduled in a future rotation.
```

**Operator reads:** "It's queued up. It just hasn't come up in the rotation yet."
**Time to answer:** ~3 seconds.

### The 10-second test

For every possible reason an asset isn't airing, the `inspect` output must:
1. **State the reason** in plain language (not a code or status enum)
2. **Name the specific blocker** (which validator, which missing step)
3. **Show the fix** (the exact command to run or action to take)

If the operator cannot answer "Why isn't this airing?" in under 10 seconds from `inspect` output, the design needs revision.

### UX verification

- [ ] Does every case produce a single, unambiguous reason?
- [ ] Is the fix always visible in the output (command or action)?
- [ ] Is the pool layer transparent enough that operators don't get confused by "ready but not in pool"?
- [ ] Can the operator self-serve every resolution without contacting support?

---

## Scenario 5 — "I want my folder to auto-update when I add files"

**Operator goal:** Set up a watched source so new files are automatically ingested.

### Step 1: Set up path mapping (if needed)

If the source's file paths don't match RetroVue's expected paths (e.g., Plex stores paths as `/plex/media/...` but the files are mounted at `/mnt/media/...`):

```
$ retrovue source path-map add "Living Room" /plex/media /mnt/media
✓ Path mapping added: /plex/media → /mnt/media
```

Path mappings are source-scoped — they apply to all containers from this source automatically (INV-PATH-MAPPING-SOURCE-SCOPED-001). Container-level overrides can be added if specific containers need different mappings.

### Step 2: Start watch mode

```
$ retrovue source watch "My Folder"

Watching /mnt/media for changes (debounce: 5s)...
```

The system monitors the source's paths for filesystem changes. When files are added, modified, or removed, the system waits for the debounce period (default 5 seconds) before re-ingesting the affected container (INV-WATCH-DEBOUNCE-001).

```
  [2026-04-09 14:32:15] Change detected: 3 files modified
  Re-ingesting container "My Folder"...
  Ingested:   3 / 3
  ✅ Ready:   3  (100%)
```

Watch mode continues running until stopped with Ctrl+C. It delegates all ingest logic to the standard container ingest workflow (INV-WATCH-DELEGATES-001) — watch mode adds no business logic of its own.

> **Under the hood:** `source watch` creates a `SourceWatchService` with a debounced file observer. Each filesystem event resets the debounce timer. When the timer expires, the full ingest workflow runs. Errors during ingest are logged but do not stop the watcher.

### Step 3: Verify path mappings

To see the effective path mappings for a source:

```
$ retrovue source path-map list "Living Room"

Source: Living Room
Mappings:
  /plex/media → /mnt/media

Container overrides: none
```

If paths are misconfigured, import-time validation catches it (INV-PATH-VALIDATION-ON-IMPORT-001):

```
$ retrovue source import "Movies"

Importing "Movies"...
  ❌ Path validation failed:
     12 / 12 sampled paths could not be resolved.
     Source prefix /plex/media has no mapping to a local path.
     
  Suggested fix:
     retrovue source path-map add "Living Room" /plex/media /mnt/media
```

### UX verification

- [ ] Can the operator set up watch mode without understanding path mapping? (Answer: yes, if paths match already)
- [ ] Does path validation catch misconfigurations at import time, not at playout time?
- [ ] Is the debounce behavior transparent enough that operators trust it?

---

## Scenario 6 — "How do I manage programming pools?"

**Operator goal:** Create pools to organize assets for scheduling.

### Step 1: Create a pool

```
$ retrovue pool create "Comedies" --match '{"tags": ["genre.comedy"]}' --description "All comedy content"
✓ Pool "Comedies" created
```

Pools define named queries against the asset catalog. They are used by the DSL scheduler to select assets for programming.

### Step 2: Inspect pool contents

```
$ retrovue pool inspect "Comedies"

Pool: Comedies
Description: All comedy content
Match criteria: {"tags": ["genre.comedy"]}

Matched assets: 142
  By type:  feature=98, episode=44
  By state: ready=140, enriching=2
```

Pool inspection resolves the match criteria against the live catalog and shows a diagnostic breakdown (INV-POOL-RESOLUTION-VISIBILITY-001).

### Step 3: Assign pool to a channel

```
$ retrovue pool assign "Comedies" "Comedy Channel"
✓ Pool "Comedies" assigned to channel "Comedy Channel"
```

Pool assignments are advisory — they help operators understand which content is available for each channel. The DSL schedule itself references pools by name.

### Step 4: List all pools

```
$ retrovue pool list

Name        Assets  Channels    Description
--------    ------  ----------  ---------------------------
Comedies    142     Comedy Ch   All comedy content
Movies      791     Movie Ch    Feature films
```

### UX verification

- [ ] Is the pool concept intuitive without prior DSL knowledge?
- [ ] Does `pool inspect` give enough information to debug "why isn't my asset in this pool"?
- [ ] Is the relationship between pools and DSL scheduling clear?

---

## End-to-End Summary

| Step | Command | Time | Outcome |
|------|---------|------|---------|
| Connect source | `retrovue source add --type plex ...` | 5 sec | Containers discovered |
| Path mapping (if needed) | `retrovue source path-map add ...` | 5 sec | Paths resolved |
| Import + validate | `retrovue source import "Movies"` | 1–5 min | ~90% ready, ~10% need attention |
| Fix failures | `retrovue asset list --errors` then fix then `retrovue asset validate` | 5–30 min | Remaining assets resolved |
| Create pool | `retrovue pool create "Movies" --match ...` | 5 sec | Pool defined |
| Create channel | `retrovue channel create "Movie Channel"` | 5 sec | Channel exists |
| Schedule | `retrovue schedule auto "Movie Channel" --container "Movies"` | 5 sec | YAML generated, 24h rotation, default pool |
| Watch (optional) | `retrovue source watch "My Folder"` | ongoing | Auto-ingest on changes |
| Diagnose | `retrovue asset inspect <id>` | <10 sec | Root cause + fix visible |

**Total time from zero to running channel: under 10 minutes** (for a typical Plex library with ~90% clean content).

---

## Resolved Design Questions

| Question | Resolution | Source |
|----------|------------|--------|
| Folder vs. Plex as primary source model | `source` is the generic noun with `--type` flag. Plex, folder, etc. are source types. | RETA-62 Design Decision #1 |
| Channel asset assignment model | Pools are the Asset-to-Channel abstraction. | RETA-62 Design Decision #3 |
| Where does new logic live? | `workflows/` or domain packages. Never CLI or API handlers. | RETA-69 invariants |
| Auto-approve default | Auto-approve is the default for `source import`. Operators opt in to manual review with `--manual-approve`. | Board direction (RETA-77) |
| Policy UX for Day 1 | Deferred. Policies are a Phase 4 feature; the Day 1 guide does not cover them. | Board direction (RETA-77) |
| `inspect` output format | Show the full validator breakdown and enrichment progress by default. Revisit if it becomes noisy in practice. | Board direction (RETA-77) |
| Pool creation in auto-schedule | `schedule auto` generates a YAML file that includes a default pool definition and a 24-hour rotation schedule. The YAML is editable. This is the quick-start exception; full channel development methodology is separate. | Board direction (RETA-77) |
| Container/source disambiguation | Optional `--source` flag with error-on-ambiguity for source-level disambiguation. `schedule auto` uses `--container` for the container filter (not `--source`, which would conflict). If container name is unique across sources: resolve normally. If ambiguous: hard error listing matches, suggest `--source <name-or-id>`. No interactive prompting (CLI must stay scriptable). No path syntax (parsing ambiguity with `/` in names). Applies to `source import`, `asset validate --container`, `schedule auto --container`. | CEO decision (RETA-78, RETA-79) |
| `--errors` status scope | `asset list --errors` shows validation failures only — assets stuck in `new` due to failed validators. Retired assets are a separate concern via `asset list --state retired`. Rationale: `--errors` = "what broke that I can fix"; retired = terminal, not actionable the same way. | CEO decision (RETA-78) |
