_Related: [Architecture](../architecture/ArchitectureOverview.md) • [Runtime](../runtime/ChannelManager.md) • [Operator CLI](../cli/README.md)_

# Domain — EPG generation

## Purpose

The Electronic Program Guide (EPG) provides viewers with information about what's currently airing and what's scheduled to air on each channel. The EPG is generated dynamically from live schedule state rather than being maintained as a separate persistent data structure.

## Core model / scope

The EPG is built from the following data sources:

- **Channel**: Defines the channels and their timing policies
- **BroadcastPlaylogEvent**: Records what was actually played and when
- **Asset**: Contains the metadata for scheduled content
- **Schedule state**: Live scheduling information managed by ScheduleService

## Contract / interface

The on-screen guide (and the GuideProducer channel) is generated from live schedule state, not from a permanently maintained epg_entries table. The EPG view is built by joining BroadcastPlaylogEvent to Asset to present "now / next" with title-level metadata.

## Execution model

EPG generation follows the same identity rules as other broadcast domain entities.

## Failure / fallback behavior

If EPG data is unavailable, the system falls back to basic channel information or default programming.

## Naming rules

- **Channel.id** (INTEGER PK) is the canonical channel identity for internal operations
- **Channel.uuid** is the external identity we surface to logs/clients for correlation
- Any earlier channels table with UUID PK is deprecated
- EPG generation follows the same identity rules as other broadcast domain entities

## See also

- [Scheduling](Scheduling.md) - High-level scheduling system
- [Playlog event](PlaylogEvent.md) - Generated playout events
- [Channel manager](../runtime/ChannelManager.md) - Stream execution
- [Operator CLI](../cli/README.md) - Operational procedures
