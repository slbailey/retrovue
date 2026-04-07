# Day 1 Operator Experience — Walkthrough Guide

> **Purpose:** Before implementing the RETA-62 Simplified Asset Management plan, this guide walks through the complete Day 1 experience from an operator's perspective. It validates that the proposed CLI surface, state transitions, and feedback loops feel coherent and intuitive before any code is written.
>
> **Reference:** [RETA-62 plan](/RETA/issues/RETA-62#document-plan) — Simplified Asset Management

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
$ retrovue plex add --url http://plex.local:32400 --token abc123
✓ Connected to Plex server "Living Room"
  Found 3 libraries: Movies (847), TV Shows (124), Music Videos (31)
```

The system discovers Plex libraries and reports item counts. No media is ingested yet — the operator chooses what to import.

### Step 2: Import a library

```
$ retrovue plex import "Movies" --auto-approve

Importing "Movies" (847 items)...
  Ingested:   847 / 847
  Validating...
  ✅ Ready:       791  (93.4%)
  ⚠️  Warnings:    38  (4.5%)
  ❌ Failed:       18  (2.1%)

791 assets are schedulable now. 38 passed with warnings. 18 need attention.
Run `retrovue asset list --errors` to see failures.
```

**What happened under the hood:**

```
Ingest → Validate (4 core validators) → Auto-Approve → Enrich (immediate enrichers)
```

Each asset moved through the state machine:

| Count | Path | Meaning |
|-------|------|---------|
| 791 | `new → validated → ready` | Broadcast-ready, no issues |
| 38 | `new → validated (warnings) → ready` | Broadcast-ready, minor warnings (e.g., low bitrate) |
| 18 | `new → new + errors` | Failed validation, not schedulable |

### What "ready" means

An asset is **ready** when:
1. All 4 core validators pass (Duration, Codec, Container, Playability)
2. The operator (or auto-approve) has approved it

Ready assets can be scheduled on any channel. They may still have warnings (non-blocking observations) and may gain richer metadata over time via enrichment.

### What "warnings" mean

Warnings are informational. The asset is fully schedulable but the system noticed something the operator might want to know — e.g., low bitrate, unusual aspect ratio, single audio channel. Warnings never block scheduling.

### What "failed" means

At least one core validator returned an error. The asset cannot be scheduled until the error is resolved and validation passes. Errors include machine-readable codes and human-readable messages.

### UX verification

- [ ] Does the operator understand the summary without reading docs?
- [ ] Is the 80–90% auto-ready target met for typical Plex libraries?
- [ ] Is the next step obvious? (look at failures, or start scheduling)

---

## Scenario 2 — "Something failed validation"

**Operator goal:** Understand what failed and fix it without frustration.

### Step 1: List failures

```
$ retrovue asset list --status new --errors

ID     Title              Error
----   ----------------   ---------------------------
1023   Die Hard           MISSING_AUDIO_CODEC: No audio stream detected
1045   Ghostbusters       UNKNOWN_CONTAINER: Container format not recognized
1099   Aliens             INVALID_DURATION: Duration = 0
1102   The Thing          PLAYABILITY_FAIL: Stream probe could not read video
```

Every error has a machine-readable code (from INV-VALIDATOR-OUTPUT-SHAPE-001) and a human message. The operator can immediately see *what* is wrong.

### Step 2: Inspect a specific asset

```
$ retrovue asset inspect 1023

Asset: Die Hard (1023)
Status: new
Source: Plex / Movies / Die Hard (1988)
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

✅ Asset validated. Status: validated → ready (auto-approved)
```

If auto-approve is on, the asset moves straight to `ready`. Otherwise:

```
✅ Asset validated. Status: validated (awaiting approval)
   Run `retrovue asset approve 1023` to make it schedulable.
```

### Batch operations

Operators can re-validate an entire folder after fixing multiple files:

```
$ retrovue asset validate --folder "Movies"

Validating 18 assets with errors...
  ✅ Fixed:  12
  ❌ Still failing: 6
```

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
$ retrovue plex import "Movies" --auto-approve
  ✅ Ready: 791 assets

$ retrovue channel create "Movie Channel"
  ✓ Channel "Movie Channel" created (id: movie-channel)

$ retrovue schedule auto "Movie Channel"
  ✓ Auto-schedule applied to "Movie Channel"
    Using 791 eligible assets
    Schedule generated: 24h continuous rotation
    First program: The Shawshank Redemption @ 00:00:00
```

That's it. The channel is live.

### What the system does

1. **Asset eligibility:** Only assets that are `ready` (validated + approved) are considered. Failed, unapproved, and policy-blocked assets are silently excluded.
2. **Enrichment:** Lightweight enrichers (ffprobe metadata, interstitial classification) run immediately after approval. Expensive enrichers (loudness analysis) run lazily — on first schedule or via background queue. The operator doesn't need to wait.
3. **Schedule generation:** The auto-scheduler fills 24h of programming using eligible assets. It respects any active policies (if configured) and falls back to the full eligible set if policies are too restrictive.
4. **Continuous playback:** The channel advances with the wall clock. Viewers join mid-program and see content at the correct offset, as if tuning into live TV.

### What the operator does NOT need to think about

- Validation (handled automatically during import)
- Enrichment (runs in background, never blocks scheduling)
- Failed assets (silently excluded — they never appear on air)
- Policy conflicts (fallback rule prevents dead air)

### The trust contract

> **If it's marked `ready`, it will eventually air.**

The operator can trust `ready` because:
- 4 core validators confirmed the asset is playable
- The playback pipeline (ffmpeg) can demux and decode it
- It has been explicitly or auto-approved

### UX verification

- [ ] Can the operator go from zero to a running channel in under 5 minutes?
- [ ] Does the operator trust that "ready" assets will actually play?
- [ ] Does the operator need to understand validation, enrichment, or policies to get started? (Answer should be: no)

---

## Scenario 4 — "Why isn't my asset airing?"

**Operator goal:** Trace exactly why a specific asset isn't appearing on their channel, in under 10 seconds.

### The diagnostic command

```
$ retrovue asset inspect 1045
```

The system returns a complete status picture. There are exactly 4 possible reasons an asset isn't airing, and the output makes each one unambiguous:

### Case 1 — Not validated (validation error)

```
Asset: Ghostbusters (1045)
Status: new (validation failed)

Validation:
  duration:    pass
  codec:       pass
  container:   FAIL — UNKNOWN_CONTAINER: Container format "rmvb" not recognized
  playability: skipped (container failed)

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

Not schedulable: needs approval.
Run: retrovue asset approve 1045
```

**Operator reads:** "It passed validation but I haven't approved it."
**Time to answer:** ~2 seconds.

### Case 3 — Policy blocked

```
Asset: Ghostbusters (1045)
Status: ready
Approval: approved
Channel: Movie Channel

Policy blocks:
  subtitles-required — Asset has no subtitle track
     Policy applied to: Movie Channel
     Fix: Add a subtitle track, or remove the policy
     Run: retrovue policy list --channel "Movie Channel"

Eligible but blocked by policy on this channel.
The asset IS broadcast-ready. A channel-specific policy prevents scheduling.
```

**Operator reads:** "It's ready, but this channel requires subtitles and my file doesn't have them."
**Time to answer:** ~5 seconds.

**Critical distinction:** The system explicitly says this is a *policy* block, not a validation failure. The asset is broadcast-ready — a channel-specific rule is preventing it. The operator knows the fix is either to add subtitles or relax the policy.

### Case 4 — Ready but not yet scheduled

```
Asset: Ghostbusters (1045)
Status: ready
Approval: approved
Policies: all pass
Channels: not assigned to any channel

Asset is fully eligible but not assigned to any channel's asset pool.
Run: retrovue channel add-assets "Movie Channel" --folder "Movies"
```

**Operator reads:** "Nothing is wrong. I just haven't added it to a channel."
**Time to answer:** ~3 seconds.

### The 10-second test

For every possible reason an asset isn't airing, the `inspect` output must:
1. **State the reason** in plain language (not a code or status enum)
2. **Name the specific blocker** (which validator, which policy, which missing step)
3. **Show the fix** (the exact command to run or action to take)

If the operator cannot answer "Why isn't this airing?" in under 10 seconds from `inspect` output, the design needs revision.

### UX verification

- [ ] Does every case produce a single, unambiguous reason?
- [ ] Is the fix always visible in the output (command or action)?
- [ ] Are policy blocks clearly distinguished from validation failures?
- [ ] Can the operator self-serve every resolution without contacting support?

---

## End-to-End Summary

| Step | Command | Time | Outcome |
|------|---------|------|---------|
| Connect source | `retrovue plex add ...` | 5 sec | Libraries discovered |
| Import + validate | `retrovue plex import "Movies" --auto-approve` | 1–5 min | ~90% ready, ~10% need attention |
| Fix failures | `retrovue asset list --errors` then fix then `retrovue asset validate` | 5–30 min | Remaining assets resolved |
| Create channel | `retrovue channel create "Movie Channel"` | 5 sec | Channel exists |
| Schedule | `retrovue schedule auto "Movie Channel"` | 5 sec | 24h programming generated |
| Diagnose | `retrovue asset inspect <id>` | <10 sec | Root cause + fix visible |

**Total time from zero to running channel: under 10 minutes** (for a typical Plex library with ~90% clean content).

---

## Open Design Questions

These should be resolved before implementation begins:

1. **Folder vs. Plex as the primary source model:** The RETA-62 plan uses `retrovue folder add` as the canonical example, but Scenario 1 above uses `retrovue plex add`. Should both exist? Should Plex be a special case of folder? Or should `source` be the generic noun with `plex` and `folder` as source types?

2. **Auto-approve default:** Should `--auto-approve` be the default for `plex import`, or should operators opt in? The "lazy operator" path (Scenario 3) works best with auto-approve as default, but some operators may want manual review.

3. **Policy UX for Day 1:** Policies are a Phase 3 feature in the RETA-62 plan. Should the Day 1 guide mention them at all, or should Scenario 4 Case 3 be deferred until policies exist? (This guide includes it for completeness, but the implementation order matters.)

4. **Channel asset assignment:** The plan doesn't specify how assets are associated with channels for scheduling. Is it folder-based? Tag-based? Explicit assignment? The `schedule auto` command needs to know which assets to draw from.

5. **`inspect` output format:** Should `inspect` always show the full validator breakdown, or only show it when there are errors? For ready assets, the full breakdown may be noise.
