_Related: [Architecture](../overview/architecture.md) • [Asset](Asset.md) • [Ingest Pipeline](IngestPipeline.md)_

# Domain — Source Collection Hierarchy

## Purpose

This document establishes the official mapping of the content hierarchy in RetroVue. It defines the relationship between Sources, Collections, and Assets, and serves as the high-level ingestion model reference.

## Hierarchy Definition

### Source

A **source** is an origin of media content. Sources represent external systems or locations where content can be discovered.

**Examples:**

- Plex library (e.g., "Movies", "TV Shows")
- Filesystem path (e.g., `/media/shows`, `/media/commercials`)
- Capture pipeline (e.g., live TV recording)
- Ad library API (e.g., commercial content provider)

### Collection

A **collection** groups related content inside a source. Collections organize content into broadcast-relevant categories within their parent source.

**Examples:**

- "Transformers Season 1" (within a TV Shows source)
- "Commercials_90s" (within a Commercials source)
- "Station IDs" (within a Promos source)
- "Classic Movies" (within a Movies source)

**TV Show Collections:**

Collections of TV shows typically have a hierarchical structure before reaching individual assets:

```
Collection (TV Show) → Title → Season → Episode → Asset
```

For example:

- **Collection**: "The Simpsons" (TV Show collection)
- **Title**: "The Simpsons" (show title)
- **Season**: "Season 1", "Season 2", etc.
- **Episode**: "Bart the Genius", "Homer's Odyssey", etc.
- **Asset**: Individual episode file

This hierarchy allows for:

- **Collection-level operations**: Ingest entire collection (`retrovue collection ingest "TV Shows"`)
- **Title-level operations**: Ingest specific show (`retrovue collection ingest "TV Shows" --title "The Simpsons"`)
- **Season-level operations**: Ingest specific season (`retrovue collection ingest "TV Shows" --title "The Simpsons" --season 1`)
- **Episode-level operations**: Ingest specific episode (`retrovue collection ingest "TV Shows" --title "The Simpsons" --season 1 --episode 1`)
- **Asset-level operations**: Individual playable files are managed through asset operations

### Asset

An **asset** is a playable unit within a collection. Assets represent individual pieces of content that can eventually be broadcast.

**Examples:**

- Individual episode files
- Individual movie files
- Individual commercial spots
- Individual bumper/promo files

## Relationship Cardinality

### Basic Hierarchy

```
Source (1) → (N) Collections
Collection (1) → (N) Assets
```

- **One source** can contain **many collections**
- **One collection** can contain **many assets**
- **Each asset** belongs to exactly **one collection**
- **Each collection** belongs to exactly **one source**

### TV Show Hierarchy

For TV show collections, the hierarchy is more complex:

```
Source (1) → (N) Collections
Collection (1) → (N) Titles
Title (1) → (N) Seasons
Season (1) → (N) Episodes
Episode (1) → (N) Assets
```

- **One source** can contain **many collections**
- **One collection** can contain **many titles** (TV shows)
- **One title** can contain **many seasons**
- **One season** can contain **many episodes**
- **One episode** can contain **many assets** (different formats, qualities, etc.)

**Note:** Movies and other content types typically follow the simpler Collection → Asset hierarchy.

## Ingestion Model

> **We ingest sources, which yield collections, which yield assets.**

### Ingestion Flow

1. **Source Discovery**: RetroVue connects to and discovers available sources
2. **Collection Enumeration**: For each source, RetroVue enumerates available collections
3. **Content Structure Discovery**: For TV show collections, RetroVue discovers the Title → Season → Episode hierarchy
4. **Asset Registration**: For each collection (or episode for TV shows), RetroVue registers individual assets
5. **Asset Enrichment**: Registered assets progress through the lifecycle state machine

### Bulk vs Surgical Operations

**Bulk Operations** (Source-level):

- `retrovue source ingest "My Plex Server"` - Processes ALL enabled collections in a source
- Used for scheduled/sanctioned sync operations
- Requires collections to be `sync_enabled=true` AND ingestible

**Surgical Operations** (Collection-level):

- `retrovue collection ingest "TV Shows" --title "The Simpsons" --season 1` - Processes specific content
- Used for manual/targeted operations
- Can run even if collection is not `sync_enabled=true`
- Supports hierarchical narrowing: collection → title → season → episode

### State Progression

Assets progress through states as they are processed:

```
new → enriching → ready → retired
```

- **`new`**: Recently discovered, minimal metadata
- **`enriching`**: Being processed by enrichers
- **`ready`**: Fully processed, approved for broadcast
- **`retired`**: No longer available or approved

## Implementation Model

### Database Relationships

```sql
-- Simplified schema representation
Source {
  id: Integer (PK)
  uuid: UUID
  name: String
  type: String
  -- source-specific configuration
}

Collection {
  uuid: UUID (PK)
  source_id: Integer (FK → Source.id)
  name: String
  -- collection-specific metadata
}

Asset {
  uuid: UUID (PK)
  collection_uuid: UUID (FK → Collection.uuid)
  state: String
  -- asset-specific metadata
}
```

### API Surface

The hierarchy is exposed through the CLI and API:

- **Source operations**:
  - `retrovue source add` - Create new sources _(Contract: [SourceAdd](../contracts/resources/SourceAddContract.md))_
  - `retrovue source delete` - Delete sources _(Contract: [SourceDelete](../contracts/resources/SourceDeleteContract.md))_
  - `retrovue source discover` - Discover collections _(Contract: [SourceDiscover](../contracts/resources/SourceDiscoverContract.md))_
  - `retrovue source ingest` - Bulk ingest all collections _(Contract: [SourceIngest](../contracts/resources/SourceIngestContract.md))_
  - `retrovue source list`, `retrovue source show`, `retrovue source update` _(Contracts: Planned)_
- **Collection operations**:
  - `retrovue collection ingest` - Targeted collection ingest _(Contract: [CollectionIngest](../contracts/resources/CollectionIngestContract.md))_
  - `retrovue collection wipe` - Complete collection cleanup _(Contract: [CollectionWipe](../contracts/resources/CollectionWipeContract.md))_
  - `retrovue collection list`, `retrovue collection update`, `retrovue collection delete` _(Contracts: Planned)_
- **Asset operations**:
  - `retrovue assets select` _(Contract: [AssetsSelect](../contracts/resources/AssetsSelectContract.md))_
  - `retrovue assets delete` _(Contract: [AssetsDelete](../contracts/resources/AssetsDeleteContract.md))_

## Operator Mental Model

Operators should understand that:

1. **Sources are discovered** - RetroVue connects to external systems
2. **Collections are enumerated** - Sources reveal their content groupings
3. **TV Show structure is discovered** - For TV collections, the Title → Season → Episode hierarchy is mapped
4. **Assets are registered** - Individual playable units are cataloged
5. **Assets are enriched** - Content progresses through processing states
6. **Ready assets are schedulable** - Only `ready` assets can be broadcast

## See also

- [Asset](Asset.md) - Individual content units
- [Ingest Pipeline](IngestPipeline.md) - Content discovery workflow
- [Architecture](../overview/architecture.md) - System overview
