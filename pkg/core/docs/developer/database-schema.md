# 🗄️ Database Schema Design

_Related: [Data model: Broadcast schema](../data-model/broadcast-schema.md) • [Data model: Identity and referencing](../data-model/IdentityAndReferencing.md) • [Infrastructure bootstrap](../infra/bootstrap.md)_

## 🎯 Schema Version 1.2 - Media-First Architecture

Update (canonical_uri):
- The `assets` table now includes `canonical_uri` (Text, nullable) and index `ix_assets_collection_canonical_uri (collection_uuid, canonical_uri)`.
- Use Alembic to apply: `alembic upgrade head` with the appropriate `RETROVUE_DATABASE_URL` for test/prod.

### **Core Design Philosophy**

The RetroVue database schema is built on a **media-first foundation** where every record begins with a physical media file. This approach ensures that:

- **Physical Reality**: All content must have an actual playable media file as its foundation
- **Logical Wrappers**: Content items are logical wrappers around media files
- **Metadata Layering**: Rich metadata is layered on top without modifying the original
- **Playback Guarantee**: Every scheduled item can be played because it has a verified media file

### **Schema Management Methodology**

RetroVue maintains schema changes via Alembic migrations (see `alembic/versions/`).

- **Single Source of Truth**: Alembic revisions + in-code models are authoritative
- **Revisions**: Apply incremental migrations with Alembic
- **Deterministic**: Consistent revision history across environments
- **Workflow**: Update models → Generate/author migration → `alembic upgrade head`

### **Core Entities Overview**

- **plex_servers**: Plex server configurations and connections
- **libraries**: Plex library definitions and metadata
- **path_mappings**: Critical mappings from Plex paths to accessible local paths
- **media_files**: Physical representation of content with technical metadata
- **content_items**: Logical content with editorial metadata and scheduling information
- **content_editorial**: Source metadata preservation and editorial overrides
- **content_tags**: Namespaced tags for audience/holiday/brand-based scheduling

## 📊 Core Tables - Current v1.2 Schema

### **Plex Servers (Server Configuration)**

```sql
plex_servers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,                -- Human-readable server name
    base_url TEXT,                     -- Plex server base URL
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
)
```

### **Libraries (Plex Library Definitions)**

```sql
libraries (
    id INTEGER PRIMARY KEY,
    server_id INTEGER NOT NULL REFERENCES plex_servers(id) ON DELETE CASCADE,
    plex_library_key TEXT NOT NULL,    -- Plex's internal library key
    title TEXT NOT NULL,               -- Library display name
    library_type TEXT NOT NULL,        -- 'movie', 'show', 'music', etc.
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
)
```

### **Path Mappings (Critical for Streaming)**

```sql
path_mappings (
    id INTEGER PRIMARY KEY,
    server_id INTEGER NOT NULL REFERENCES plex_servers(id) ON DELETE CASCADE,
    library_id INTEGER NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
    plex_path TEXT NOT NULL,           -- Plex internal path
    local_path TEXT NOT NULL,          -- Accessible local path
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
)
```

### **Shows (TV Series Metadata)**

```sql
shows (
    id INTEGER PRIMARY KEY,
    server_id INTEGER NOT NULL REFERENCES plex_servers(id) ON DELETE CASCADE,
    library_id INTEGER NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
    plex_rating_key TEXT NOT NULL,     -- Plex's unique identifier
    title TEXT NOT NULL,               -- Show title
    year INTEGER,                      -- Year for disambiguation
    originally_available_at TEXT,      -- Original air date
    summary TEXT,                      -- Show description
    studio TEXT,                       -- Production studio
    artwork_url TEXT,                  -- Show artwork URL
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
)
```

### **Seasons (TV Season Metadata)**

```sql
seasons (
    id INTEGER PRIMARY KEY,
    show_id INTEGER NOT NULL REFERENCES shows(id) ON DELETE CASCADE,
    season_number INTEGER NOT NULL,    -- Season number
    plex_rating_key TEXT,              -- Plex's season identifier
    title TEXT,                        -- Season title
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
)
```

### **Content Items (Logical Content Wrappers)**

```sql
content_items (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('movie','episode','interstitial','intro','outro','promo','bumper','clip','ad','unknown')),
    title TEXT,                        -- Content title
    synopsis TEXT,                     -- Content description
    duration_ms INTEGER,               -- Duration in milliseconds
    rating_system TEXT,                -- Rating system (MPAA, TV, etc.)
    rating_code TEXT,                  -- Rating code (G, PG, TV-14, etc.)
    is_kids_friendly INTEGER DEFAULT 0 CHECK (is_kids_friendly IN (0,1)),
    artwork_url TEXT,                  -- Artwork URL
    guid_primary TEXT,                 -- Primary external identifier
    external_ids_json TEXT,            -- JSON of all external IDs
    metadata_updated_at INTEGER,       -- EPOCH SECONDS (editorial freshness)
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    show_id INTEGER REFERENCES shows(id) ON DELETE SET NULL,
    season_id INTEGER REFERENCES seasons(id) ON DELETE SET NULL,
    season_number INTEGER,             -- For episodes
    episode_number INTEGER             -- For episodes
)
```

### **Media Files (Physical File Storage)**

```sql
-- MEDIA FILES (polymorphic via two FKs; exactly one must be set)
media_files (
    id INTEGER PRIMARY KEY,
    movie_id   INTEGER,                -- References movies(id) if this is a movie file
    episode_id INTEGER,                -- References episodes(id) if this is an episode file
    plex_file_path   TEXT NOT NULL,    -- Plex file path
    local_file_path  TEXT,             -- Local accessible file path
    file_size_bytes  INTEGER,          -- File size in bytes
    video_codec      TEXT,             -- Video codec
    audio_codec      TEXT,             -- Audio codec
    width INTEGER,                     -- Video width
    height INTEGER,                    -- Video height
    duration_ms INTEGER,               -- Duration in milliseconds
    container TEXT,                    -- Container format (mp4, mkv, etc.)
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    CHECK ((movie_id IS NOT NULL) <> (episode_id IS NOT NULL)),
    FOREIGN KEY (movie_id)   REFERENCES movies(id)   ON DELETE CASCADE,
    FOREIGN KEY (episode_id) REFERENCES episodes(id) ON DELETE CASCADE
)
```

**Note**: The `media_files` table is polymorphic via two foreign keys (`movie_id` and `episode_id`). Exactly one of these must be set (enforced by a CHECK constraint), allowing the same table to store files for both movies and episodes while maintaining referential integrity.

### **Content Tags (Namespaced Tagging System)**

```sql
content_tags (
    content_item_id INTEGER NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
    namespace TEXT NOT NULL,           -- 'audience', 'holiday', 'brand', 'tone', 'genre', 'season'
    key TEXT NOT NULL,                -- Tag key within namespace
    value TEXT,                       -- Tag value
    PRIMARY KEY (content_item_id, namespace, key)
)
```

### **Content Editorial (Source Metadata & Overrides)**

```sql
content_editorial (
    content_item_id INTEGER PRIMARY KEY REFERENCES content_items(id) ON DELETE CASCADE,
    source_name TEXT,                 -- 'plex', 'tmm', 'manual'
    source_payload_json TEXT,         -- Complete source metadata as JSON
    original_title TEXT,              -- Original title from source
    original_synopsis TEXT,           -- Original synopsis from source
    override_title TEXT,              -- Editorial override title
    override_synopsis TEXT,           -- Editorial override synopsis
    override_updated_at INTEGER       -- EPOCH SECONDS when override was last updated
)
```

## 🎬 Media Markers & Ad Breaks

### **Media Markers (Ad Breaks & Cue Points)**

```sql
media_markers (
    id INTEGER PRIMARY KEY,
    media_file_id INTEGER NOT NULL REFERENCES media_files(id) ON DELETE CASCADE,
    marker_kind TEXT NOT NULL CHECK (marker_kind IN ('chapter','ad_break','cue')),
    start_ms INTEGER NOT NULL,         -- Start time in milliseconds
    end_ms INTEGER,                    -- End time in milliseconds (for ad breaks)
    label TEXT,                        -- Marker label/description
    source TEXT NOT NULL CHECK (source IN ('file','manual','detected')),
    confidence REAL,                   -- Confidence score for detected markers
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
)
```

## 📺 Scheduling & Playout

### **Channels**

```sql
channels (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,                -- Channel name
    number TEXT,                       -- Channel number
    callsign TEXT,                     -- Channel callsign
    is_active INTEGER DEFAULT 1 CHECK (is_active IN (0,1)),
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
)
```

### **Schedule Blocks (Programming Templates)**

```sql
schedule_blocks (
    id INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    name TEXT NOT NULL,                -- Block name (e.g., "Sitcoms at 5pm")
    day_of_week INTEGER NOT NULL CHECK (day_of_week BETWEEN 0 AND 6), -- 0=Sun..6=Sat
    start_time TEXT NOT NULL,          -- 'HH:MM:SS' format
    end_time TEXT NOT NULL,            -- 'HH:MM:SS' format
    strategy TEXT NOT NULL CHECK (strategy IN ('auto','series','specific','collection')),
    constraints_json TEXT,             -- JSON constraints for content selection
    ad_policy_id INTEGER,              -- Reference to ad policy
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
)
```

### **Schedule Instances (Specific Scheduled Content)**

```sql
schedule_instances (
    id INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    block_id INTEGER REFERENCES schedule_blocks(id) ON DELETE SET NULL,
    air_date TEXT NOT NULL,            -- 'YYYY-MM-DD' format
    start_time TEXT NOT NULL,          -- 'HH:MM:SS' format
    end_time TEXT NOT NULL,            -- 'HH:MM:SS' format
    content_item_id INTEGER REFERENCES content_items(id) ON DELETE SET NULL,
    show_id INTEGER REFERENCES shows(id) ON DELETE SET NULL,
    pick_strategy TEXT NOT NULL CHECK (pick_strategy IN ('auto','specific','series_next')),
    status TEXT NOT NULL DEFAULT 'planned' CHECK (status IN ('planned','approved','played','canceled')),
    notes TEXT,                        -- Scheduler notes
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
)
```

### **Ad Policies (Commercial Targeting Rules)**

```sql
ad_policies (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,                -- Policy name
    rules_json TEXT NOT NULL,          -- JSON rules for commercial targeting
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
)
```

### **Play Log (What Actually Aired)**

```sql
play_log (
    id INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    ts_start TEXT NOT NULL,            -- ISO8601 timestamp
    ts_end TEXT,                       -- ISO8601 timestamp
    item_kind TEXT NOT NULL CHECK (item_kind IN ('program','ad','promo','bumper','clip','unknown')),
    content_item_id INTEGER REFERENCES content_items(id) ON DELETE SET NULL,
    media_file_id INTEGER REFERENCES media_files(id) ON DELETE SET NULL,
    schedule_instance_id INTEGER REFERENCES schedule_instances(id) ON DELETE SET NULL,
    ad_block_seq INTEGER,              -- Sequence within ad block
    notes TEXT                         -- Additional notes
)
```

## 🔄 Schema Management Methodology

### **Schema-First Approach**

RetroVue uses a **schema-first approach** with no migration framework:

#### **Single Source of Truth**

- **`sql/retrovue_schema_v1.2.sql`** is the authoritative schema file
- All schema changes are made directly to this SQL file
- No migration scripts, no version tracking, no incremental changes

#### **Clean Recreate Workflow**

1. **Delete existing database**: Drop the PostgreSQL database
2. **Update schema**: Modify `sql/retrovue_schema_v1.2.sql` as needed
3. **Recreate database**: Run `scripts/db_reset.py` to create fresh database
4. **Re-import data**: Use the UI to re-sync from Plex/TMM sources

#### **Benefits of This Approach**

- **Deterministic**: Every database creation produces identical results
- **Simple**: No complex migration logic or version management
- **Reliable**: No risk of migration failures or data corruption
- **Fast**: Schema changes are immediate, no migration downtime
- **Clean**: No legacy migration artifacts or version tracking

#### **Development Workflow**

```bash
# Make schema changes
# Edit sql/retrovue_schema_v1.2.sql

# Reset database with new schema
python scripts/db_reset.py

# Re-import content
# Use UI to sync from Plex/TMM
```

#### **Production Considerations**

- **Backup First**: Always backup existing data before schema changes
- **Data Export**: Export any custom data before reset
- **Re-import**: Plan for re-importing content after schema changes
- **Testing**: Test schema changes in development first

## 🎯 Key Design Decisions - Media-First Architecture

### **1. Media-First Design**

- **Physical Foundation**: Every content item must have a verified media file
- **Logical Wrappers**: Content items are logical wrappers around media files
- **Metadata Layering**: Rich metadata is layered on top without modifying originals
- **Playback Guarantee**: Every scheduled item can be played because it has a verified media file

### **2. Unified Content Model**

- **Single Content Table**: `content_items` replaces separate movies/episodes tables
- **Content Type Field**: Distinguishes between movies, episodes, commercials, bumpers, etc.
- **Consistent Ratings**: Standardized rating system across all content types
- **Unified Scheduling**: All content types use the same scheduling system

### **3. Editorial Override System**

- **Source Preservation**: Original Plex/TMM metadata remains intact
- **Customization Layer**: Editorial changes stored separately in `content_editorial`
- **Audit Trail**: All editorial changes tracked with timestamps
- **Flexible Editing**: Users can modify metadata without losing source data

### **4. Namespaced Tagging System**

- **Structured Organization**: Tags follow `namespace:value` format
- **Flexible Targeting**: Multiple namespaces for complex scheduling rules
- **Extensible Design**: New namespaces can be added without schema changes
- **Hierarchical Control**: Tags can be combined for sophisticated content selection

### **5. Advanced Scheduling Architecture**

- **Schedule Blocks**: High-level programming templates (e.g., "Sitcoms at 5pm")
- **Schedule Instances**: Specific content scheduled for exact date/time
- **Tag-Based Selection**: Content selection based on namespaced tags
- **Rating Compliance**: Automatic content filtering based on parental ratings

### **6. Comprehensive Logging**

- **Play Log Tracking**: Records what programs and ads actually aired
- **Weekly Rotation**: Automatic log management to prevent database bloat
- **Performance Metrics**: Track system performance and resource usage
- **Error Logging**: Record playback errors and technical issues

### **7. Multi-Channel Ready**

- **Channel Abstraction**: Independent channel scheduling and control
- **Emergency System**: Priority alert injection across all channels
- **Resource Management**: CPU and memory allocation per channel
- **Scalable Architecture**: Support for multiple simultaneous streams

## 🔧 Schema Conflict Resolution

### **Rating System Standardization**

- **Unified Ratings**: All tables now use consistent rating values
- **MPAA + TV Ratings**: Support for both movie and TV rating systems
- **Migration Path**: Clear migration from old simple ratings to comprehensive system

### **Metadata Consolidation**

- **Single Source**: `content_editorial` consolidates all metadata
- **No Overlap**: Eliminated duplicate metadata fields across tables
- **Clear Separation**: Source metadata vs. editorial overrides clearly defined

### **Scheduling System Unification**

- **Single Scheduling**: `schedule_instances` replaces old `schedules` table
- **Content Items**: All scheduling references `content_item_id` instead of `media_file_id`
- **Backward Compatibility**: Old tables marked as deprecated but preserved

### **Logging System Consolidation**

- **Single Logging**: `play_log` replaces old `playout_logs` table
- **Enhanced Tracking**: More detailed logging with actual vs. scheduled timing
- **Weekly Rotation**: Built-in log management to prevent database bloat

## 🎯 Key Design Decisions - v1.2 Architecture

### **1. Plex-Centric Design**

- **Server Management**: `plex_servers` table manages multiple Plex server connections
- **Library Organization**: `libraries` table organizes content by Plex library
- **Path Mapping**: Critical `path_mappings` table enables streaming by mapping Plex paths to accessible paths
- **Plex Integration**: All content references Plex rating keys for reliable synchronization

### **2. Media-First Foundation**

- **Physical Files**: `media_files` table stores actual file information with technical metadata
- **Content Wrappers**: `content_items` provides logical content organization
- **File Mapping**: `content_item_files` links content to media files with role support
- **Playback Guarantee**: Every scheduled item has verified media file access

### **3. Flexible Content Model**

- **Content Kinds**: Support for movies, episodes, commercials, bumpers, promos, etc.
- **TV Structure**: Proper show/season/episode hierarchy with Plex integration
- **Rating Systems**: Flexible rating system and code storage
- **Kids-Friendly**: Boolean flag for quick family content filtering

### **4. Editorial Override System**

- **Source Preservation**: Complete source metadata stored as JSON in `content_editorial`
- **Override Support**: Separate fields for editorial title and synopsis overrides
- **Audit Trail**: Timestamp tracking for when overrides were last updated
- **Flexible Sources**: Support for Plex, TMM, and manual content sources

### **5. Advanced Tagging System**

- **Namespaced Tags**: `content_tags` uses namespace/key/value structure
- **Flexible Organization**: Support for audience, holiday, brand, tone, genre, season tags
- **Efficient Queries**: Indexed for fast content selection and filtering
- **Extensible**: New namespaces can be added without schema changes

### **6. Sophisticated Scheduling**

- **Schedule Blocks**: Template-based programming with day-of-week and time constraints
- **Strategy Support**: Auto, series, specific, and collection-based content selection
- **Schedule Instances**: Specific scheduled content with approval workflow
- **Ad Integration**: Built-in ad policy support for commercial management

### **7. Comprehensive Media Markers**

- **Multiple Types**: Support for chapters, ad breaks, and cue points
- **Source Tracking**: File-based, manual, or detected markers
- **Confidence Scoring**: For automatically detected markers
- **Flexible Timing**: Start/end time support for various marker types

### **8. Detailed Play Logging**

- **ISO8601 Timestamps**: Precise time tracking for all aired content
- **Item Classification**: Programs, ads, promos, bumpers, clips
- **Schedule Linking**: Links to original schedule instances
- **Ad Block Sequencing**: Support for ad block sequence tracking

## 🔧 Schema Management Benefits

### **No Migration Complexity**

- **Simple Changes**: Schema changes are made directly to the SQL file
- **No Version Tracking**: No need to manage migration versions or rollbacks
- **No Data Corruption**: No risk of migration failures or partial updates
- **Immediate Results**: Schema changes take effect immediately

### **Deterministic Database Creation**

- **Identical Results**: Every database creation produces the same structure
- **Reproducible**: Same schema file always creates identical database
- **Testable**: Easy to test schema changes in isolation
- **Reliable**: No dependency on migration state or order

### **Development Efficiency**

- **Fast Iteration**: Schema changes are immediate, no migration downtime
- **Clean Environment**: Fresh database for each development session
- **Simple Testing**: Easy to test with clean database state
- **No Artifacts**: No migration files or version tracking to maintain

## 📊 Performance Considerations

### **Indexing Strategy**

- **Primary Keys**: All tables have efficient primary key indexes
- **Foreign Keys**: CASCADE deletes for data integrity and performance
- **Unique Constraints**: Prevent duplicate data and enable fast lookups
- **Composite Indexes**: Optimized for common query patterns
- **Content Queries**: Indexed on namespace/key for fast tag-based filtering
- **Scheduling**: Indexed on date/time for efficient schedule queries

### **Query Optimization**

- **Normalized Schema**: Reduces data duplication and storage requirements
- **Efficient Joins**: Proper foreign key relationships for fast joins
- **Plex Integration**: Direct Plex rating key lookups for synchronization
- **Content Selection**: Optimized queries for tag-based content filtering
- **Schedule Queries**: Efficient date/time range queries for scheduling

### **Scalability**

- **PostgreSQL Foundation**: Centralized database with excellent performance and scalability
- **Plex Integration**: Leverages Plex's existing metadata and file organization
- **Efficient Sync**: Only updates changed content based on Plex timestamps
- **Large Libraries**: Optimized for libraries with thousands of items
- **Memory Efficient**: Proper indexing prevents full table scans

### **Schema Management Performance**

- **Fast Creation**: PostgreSQL database creation is very fast
- **No Migration Overhead**: No migration scripts to run or maintain
- **Clean State**: Fresh database ensures optimal performance
- **Deterministic**: Same schema always produces same performance characteristics
