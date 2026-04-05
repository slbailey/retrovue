# EPG

**Domain:** scheduling  
**Slug:** `epg`

## What it represents

A **viewer-facing guide** derived from schedule truth: titles, times, continuity for display—not the control tape for the engine.

## Lifecycle phase

**Derived** from ScheduleDay (or equivalent canonical schedule), updated as scheduling publishes.

## Owning domain

scheduling

## What depends on it

UI, “now playing” labels, integrations (e.g. XMLTV) as allowed by contracts.

## What produces it

Scheduling / EPG generation from canonical schedule artifacts.

## What must NOT be assumed

- **Critical:** that EPG rows determine segment boundaries, asset paths, offsets, or “what plays next” in ChannelManager (forbidden).
- That EPG freshness equals execution-window freshness.
