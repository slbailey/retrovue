_Related: [Infrastructure bootstrap](../infra/bootstrap.md) • [Broadcast schema](broadcast-schema.md) • [Architecture overview](../architecture/ArchitectureOverview.md)_

# RetroVue Data Model

This directory contains documentation for RetroVue's data model, organized by domain.

## Domain Separation

RetroVue enforces a strict separation between two domains:

### Library Domain

- **Owns**: Media discovery, ingest, enrichment, QC, review
- **Tracks**: Episodes, seasons, titles, sources, provider_refs, file metadata, technical metadata, markers, duration, etc.
- **Tables**: episodes, assets, provider_refs, review_queue, seasons, titles, etc.

### Broadcast Domain

- **Owns**: Channel policy, dayparting rules, broadcast-day assignment, airable catalog, and playlog_event
- **Tables**: channels, schedule_template, schedule_template_block, broadcast_schedule_day, catalog_asset, broadcast_playlog_event

## Schema Migration Note (critical)

- The tables `channels`, `templates`, `template_blocks`, `schedule_days`, and `playlog_events` have been removed.
- Those tables used to live in the Library Domain.
- They have been replaced by the Broadcast Domain tables:
  `channels`, `schedule_template`, `schedule_template_block`, `broadcast_schedule_day`, `catalog_asset`, and `broadcast_playlog_event`.
- This is enforced by Alembic migration `68fecbe0ea79`.
- Do not reintroduce scheduling tables into the Library Domain.

## Files

- `broadcast-schema.md` - Broadcast Domain table definitions and relationships

## Known Technical Debt / Pending Integrations

- **Plex Path Mapping:**  
  A mapping layer between Plex libraries and RetroVue's local playout directories will be added.  
  Each library will define `root_path` and `local_path` pairs.  
  Promotion will use this mapping to ensure that `catalog_asset.file_path` points to a real, local file.  
  Missing or deleted Plex assets will trigger catalog invalidation (`available=false`, `canonical=false`).
