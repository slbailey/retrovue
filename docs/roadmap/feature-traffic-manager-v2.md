# Feature: Traffic Manager v2 — File-Based Ingest, AI Tagging & Contextual Placement

**Status:** Planned  
**Phase:** 02 (Ads, Promos & Packaging)  
**Priority:** Next up after segment transitions  
**Revenue potential:** AI enrichment is a paid/metered feature

---

## Overview

Traffic Manager v1 fills every ad break with a single looping filler file. v2 introduces:

1. **File-based media ingest** — scan a filesystem directory (+ subdirectories) into the asset library
2. **AI-powered enrichment** — use GPT-4o Vision to identify commercials and auto-tag them
3. **Contextual ad selection** — query tags to match commercials to programming context
4. **Placement rules** — positional triggers like "play trailer AFTER movie ends"

---

## Step 1: File-Based Ingest

### Problem
The current asset library only ingests from Plex. Commercials, trailers, bumpers, and promos live on the filesystem outside of Plex and have no ingest path.

### Solution
Add a filesystem ingest method to AssetLibrary that:
- Scans a directory (recursively) for media files (`.mp4`, `.mkv`, `.mov`, `.ts`)
- Extracts basic metadata: filename, duration, resolution, codec, file size
- Registers each file as an asset in the database
- Assigns all assets from a scan to a named **collection** (e.g. `commercials`, `movie-trailers`)
- Supports re-scan (detects new/removed/changed files by mtime + size)
- CLI: `retrovue ingest --source /path/to/commercials --collection commercials`

### Collections (examples)
| Collection | Source Path | Description |
| --- | --- | --- |
| `commercials` | `/media/commercials/` | Vintage TV commercials for ad breaks |
| `movie-trailers` | `/media/trailers/` | Movie trailers, played after feature films |
| `bumpers` | `/media/bumpers/` | Channel bumpers/idents |
| `promos` | `/media/promos/` | Show promos and teasers |

### Schema
```sql
-- New or extended table
CREATE TABLE file_assets (
    id INTEGER PRIMARY KEY,
    collection TEXT NOT NULL,        -- e.g. 'commercials', 'movie-trailers'
    file_path TEXT NOT NULL UNIQUE,
    filename TEXT NOT NULL,
    duration_ms INTEGER,
    resolution TEXT,                  -- e.g. '720x480', '1920x1080'
    codec TEXT,
    file_size_bytes INTEGER,
    file_mtime REAL,
    ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    enriched_at TIMESTAMP,           -- NULL until AI enrichment runs
    metadata_json TEXT               -- flexible JSON blob for tags, etc.
);
```

---

## Step 2: AI Enrichment (Paid Feature)

### Problem
A directory of 500 commercial files named `commercial_001.mp4` through `commercial_500.mp4` is useless without knowing what each one advertises.

### Solution
A **paid enricher** that uses GPT-4o Vision to:
1. Sample 3-5 frames from the video (evenly spaced)
2. Send frames to GPT-4o Vision with a structured prompt
3. Extract: product/brand name, category, decade/era, mood, target demographic
4. Store tags in the database (`metadata_json` or a dedicated tags table)

### Tag Schema
```json
{
    "brand": "Coca-Cola",
    "product": "Diet Coke",
    "category": "beverage",
    "subcategory": "soft-drink",
    "era": "1980s",
    "mood": ["upbeat", "summer", "youth"],
    "demographic": ["gen-x", "general"],
    "duration_class": "30sec",
    "custom_tags": ["beach", "music", "celebrity"]
}
```

### Why Paid
- GPT-4o Vision API calls cost real money (~$0.01-0.03 per commercial)
- This is a value-add feature — operators with large libraries get automatic cataloging
- Could be metered (pay per enrichment) or bundled in a pro tier
- CLI: `retrovue enrich --collection commercials --model gpt-4o`

### Enrichment Contract
- Enricher MUST be idempotent (re-running on already-enriched assets is a no-op unless `--force`)
- Enricher MUST store raw API response alongside extracted tags (audit trail)
- Enricher MUST support batch processing with rate limiting
- Enricher MUST NOT block ingest — enrichment is async/deferred
- Tags are suggestions — operator can override/edit via CLI or future UI

---

## Step 3: Contextual Ad Selection

### Problem
Traffic Manager v1 plays the same filler for every break. With tagged commercials, we can match ads to programming context.

### Solution
Query engine that selects commercials based on:
- **Show context:** genre, era, audience demographic
- **Time of day:** morning/afternoon/evening/overnight
- **Frequency caps:** don't repeat the same commercial within N breaks
- **Category affinity:** food commercials near cooking shows, toy commercials near kids content
- **Era matching:** 80s commercials with 80s programming

### Selection Priority
1. Era match + category affinity (best fit)
2. Era match only
3. Category affinity only
4. Random from pool (fallback, same as v1 but with variety)

---

## Step 4: Placement Rules

### Problem
Movie trailers should play AFTER a movie ends, not in random ad breaks. Some content has positional requirements.

### Solution
Placement rules define WHEN a collection's assets appear:

```yaml
placement_rules:
  - collection: movie-trailers
    trigger: after_program
    filter:
      program_type: movie
    count: 1-2                    # play 1-2 trailers after each movie
    
  - collection: commercials
    trigger: ad_break
    filter: {}                    # fill regular ad breaks
    selection: contextual         # use AI tags for matching
    
  - collection: bumpers
    trigger: before_program
    filter: {}                    # play bumper before every show
    count: 1
```

### Trigger Types
| Trigger | When | Use Case |
| --- | --- | --- |
| `ad_break` | During computed ad breaks (act breaks) | Commercials |
| `before_program` | Before a program block starts | Bumpers, channel idents |
| `after_program` | After a program block ends | Movie trailers, "up next" promos |
| `top_of_hour` | At :00 of each hour | News bumpers, time checks |

---

## Implementation Order

1. **File-based ingest** — filesystem scanner + collection assignment + CLI
2. **Database schema** — file_assets table + tags storage
3. **AI enrichment** — GPT-4o Vision integration + tag extraction
4. **Selection engine** — tag-based querying with affinity scoring
5. **Placement rules** — trigger system in playout log expander
6. **Traffic Manager v2** — orchestrates selection + placement into break slots

## Dependencies
- Step 1 (ingest) has no dependencies — can start immediately
- Step 2 (AI enrichment) requires OpenAI API key + billing
- Steps 3-5 require steps 1-2 to be useful but can be stubbed

---

_This feature converts RetroVue from "plays filler" to "plays the right content at the right time" — the core value proposition of a traffic system._
