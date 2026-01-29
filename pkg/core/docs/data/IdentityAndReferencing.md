# Identity and Referencing

_Related: [Data model: Broadcast schema](broadcast-schema.md) • [Data model README](README.md) • [Infrastructure bootstrap](../infra/bootstrap.md)_

## Domain — Identity and referencing

### Purpose

This document defines the canonical identity rules for persisted entities in the RetroVue system. These rules ensure consistent data modeling, cross-domain lineage tracking, and operational integrity across all persisted entities.

The identity model provides a dual-key approach that separates internal database operations from external identity and correlation requirements.

### Primary keys

Every persisted row has **id** (INTEGER autoincrement) as the primary key. This provides:

- Fast relational joins and foreign key references
- Efficient database operations and indexing
- Standard SQLAlchemy ORM compatibility
- Optimal performance for scheduling and playout queries

All foreign keys in other tables reference that **id** (INTEGER) field, not UUID or other identifier types.

### UUID usage

Each row also has a **uuid** column that is globally unique and indexed. The uuid serves as:

- Stable external identity across environments
- Correlation key for cross-domain lineage tracking
- Audit trail identifier for compliance and as-run reports
- Integration point for external systems and APIs

The uuid is generated once and never changes, providing stable identity even when data moves between environments or systems.

### Cross-domain lineage

Different tables representing different lifecycle stages of the same logical content will have different **id** values but intentionally share the same **uuid** value. This enables:

- **Ingest to catalog correlation**: assets.id and catalog_asset.id are different, but both reference the same uuid
- **Content lifecycle tracking**: trace content from ingest through catalog to scheduled playout
- **Compliance reporting**: correlate what was ingested with what was scheduled and what actually aired
- **Cross-domain queries**: find all records related to the same logical content item

catalog_asset also stores **source_ingest_asset_id** (INTEGER FK to assets.id) for fast relational lookup, but the authoritative logical identity across domains is the shared **uuid**.

### Operational implications

Channel uses the same pattern: **id** (INTEGER PK) for joins/scheduling, plus a **uuid** for external identity and logging.

BroadcastPlaylogEvent is expected to carry both its own **id** (INTEGER PK) and a stable **uuid** for audit of "what aired at a specific wallclock time."

This dual-key approach enables:

- Fast internal operations using INTEGER primary keys
- Stable external identity using UUID for correlation
- Cross-domain lineage tracking through shared UUID values
- Audit trails and compliance reporting
- Integration with external systems

### Naming and consistency rules

- **id** fields are always INTEGER primary keys with autoincrement
- **uuid** fields are always globally unique and indexed
- Foreign key references always use the **id** field, never UUID
- Cross-domain correlation always uses the **uuid** field
- Any code that assumes UUID primary keys for channels or EPG entries is deprecated
- The canonical channel table is **broadcast_channel** (INTEGER PK), not channels
- All new entities must follow the id (INTEGER PK) + uuid (stable external identity) pattern

### Sequence management

PostgreSQL auto-increment sequences can be reset when needed:

```sql
-- Reset assets sequence to start from 1
ALTER SEQUENCE assets_id_seq RESTART WITH 1;

-- Reset multiple sequences
ALTER SEQUENCE assets_id_seq RESTART WITH 1;
ALTER SEQUENCE catalog_asset_id_seq RESTART WITH 1;
ALTER SEQUENCE broadcast_playlog_event_id_seq RESTART WITH 1;
```

**When to reset sequences:**

- After complete collection wipe operations
- During testing and development
- When asset IDs become too large (e.g., > 100,000)
- After schema changes requiring fresh data

**Safety considerations:**

- Only reset sequences when all related tables are empty
- Always verify no data exists before resetting
- Document sequence resets for audit purposes
- Consider impact on any external systems using asset IDs
