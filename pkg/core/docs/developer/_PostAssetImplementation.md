New command (resource contract)

retrovue collection purge <collection_id>

What it does (by design, not DB CASCADE):

Enumerates all assets in that collection.

Validates safety rules.

Deletes them in the correct order (and related rows), then deletes the collection.

All inside a single Unit of Work.

Safety rails (non-negotiable):

Dry-run required on first run (unless --no-dry-run).

Typed confirmation: --confirm <exact UUID>.

Multiple flags to make intent unmistakable:

--purge-assets (required)

--hard (hard delete; otherwise soft delete)

--force (bypass prompts after confirmation)

Environment guards:

In prod: default refuse; allow only with --prod-override AND ALLOW_COLLECTION_PURGE=1 env var present.

In test-db: fully allowed (enable fast dev iteration).

Historical integrity:

Never delete assets referenced by playout/AsRun in prod (hard stop).
In test-db, allow for speed.

Examples

# Dev/test: full nuke (hard delete)

retrovue collection purge <id> --purge-assets --hard --test-db --confirm <id>

# Dev/test: preview only

retrovue collection purge <id> --purge-assets --dry-run

# Prod: refuse by default

retrovue collection purge <id> --purge-assets

# -> Error: Purge disallowed in production.

# Prod: explicit override (still blocks if assets are referenced by playout)

ALLOW_COLLECTION_PURGE=1 retrovue collection purge <id> \
 --purge-assets --hard --prod-override --confirm <id>

Also add a “fast dev” helper

retrovue collection reset <collection_id>

For development: soft-delete all assets in that collection, set collection to ingestible=true/sync_enabled=true (optional), clear last_ingest_time, and leave the collection row.

Next ingest is a clean slate without recreating the collection record.

In prod, this command would still be allowed (it’s reversible and safe).
