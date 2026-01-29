# Canonical Key System

This document defines the canonical identity rules used by Collection Ingest and the Asset table to enforce UNIQUE (collection_uuid, canonical_key_hash).

---

## Where it's used

- `src/retrovue/infra/canonical.py` - Core implementation
- `src/retrovue/cli/commands/_ops/collection_ingest_service.py` - Ingest service integration
- `tests/contracts/test_collection_ingest_contract.py` - Contract tests

---

## Overview

The canonical key system provides a consistent, deterministic way to identify Assets across different sources (filesystem, Plex, SMB, etc.). It ensures that:
- Same logical asset from different providers maps to the same canonical identity
- Path variations (Windows vs POSIX, different casing, etc.) normalize to the same key
- Duplicate detection works correctly within a collection

---

## Canonical Form

### Structure

```
{provider}:{collection}:{relative_path}
```

Where:
- **provider**: Provider name (e.g., `plex`, `filesystem`, `smb`)
- **collection**: Collection UUID or external_id
- **relative_path**: Normalized path or external_id

### Examples

```
plex:collection:12345:plex://server/library/item-123
filesystem:collection:abc-123:/movies/the_matrix.mkv
smb://server/share:collection:abc-123:/videos/episode-01.mkv
```

---

## Normalization Rules

### Path Normalization

1. **Case**: All paths are lowercased
2. **Slashes**: Convert backslashes to forward slashes
3. **Multiple slashes**: Collapse multiple slashes to single slash
4. **Trailing slashes**: Remove except for root `/`
5. **Windows drives**: Convert `C:\path` to `/c/path`
6. **UNC paths**: Preserve `//server/share` format (don't lowercase server name)

### URI Schemes

Supported schemes:
- `file://` - Local files
- `smb://` - SMB network shares
- `nfs://` - NFS network shares
- `http://`, `https://` - HTTP resources
- Custom schemes are preserved as-is

### Collection Identifiers

Collection can be specified as:
- `collection.uuid` (UUID format)
- `collection.external_id` (external identifier)
- `collection.name` (collection name)

---

## Hash Derivation

The canonical hash is the SHA-256 hash of the canonical key in UTF-8:

```python
import hashlib
hash = hashlib.sha256(canonical_key.encode("utf-8")).hexdigest()
```

Result: 64-character hexadecimal string.

---

## Error Handling

If canonical key cannot be derived from an item, `IngestError` is raised:

```python
raise IngestError("Cannot derive canonical key from item: missing provider_key/external_id/path/uri")
```

This ensures that ingest operations fail early with a clear error message when required fields are missing.

---

## Usage

### Basic Usage

```python
from retrovue.infra.canonical import canonical_key_for, canonical_hash

# For a DiscoveredItem
canonical_key = canonical_key_for(item, collection=collection, provider="plex")
canonical_hash = canonical_hash(canonical_key)

# Result:
# canonical_key: "plex:collection:abc-123:plex://server/library/item-123"
# canonical_hash: "a1b2c3d4..." (64 hex chars)
```

### Provider Preference

1. Use `provider_key` (external_id) if present
2. Fall back to `path_uri`/`uri`/`path`
3. Build normalized canonical form

### Collection Scope

Include collection identifier to ensure uniqueness within scope:
- Different collections can have same paths without collision
- Duplicate detection works correctly per collection

---

## Examples

### Filesystem Paths

| Original | Normalized |
|----------|------------|
| `C:\Movies\The Matrix.mkv` | `/c/movies/the matrix.mkv` |
| `/mnt/data/MOVIES/THE_MATRIX.MKV` | `/mnt/data/movies/the_matrix.mkv` |
| `\\SERVER\share\video.mkv` | `//server/share/video.mkv` |
| `filesystem/collection:/path/video.mkv` | `filesystem:collection:/path/video.mkv` |

### URIs

| Original | Normalized |
|----------|------------|
| `file:///C:/Movies/video.mkv` | `file:///c/movies/video.mkv` |
| `file:////server/share/video.mkv` | `file:////server/share/video.mkv` |
| `smb://SERVER/Share/Video.mkv` | `smb://server/share/video.mkv` |
| `plex://server:32400/library/item-123` | `plex://server:32400/library/item-123` |

### Mixed Path Equivalence

These should map to the same canonical key:

| Path 1 | Path 2 | Same Key? |
|--------|--------|-----------|
| `C:\Movies\video.mkv` | `c:/movies/video.mkv` | ✅ Yes |
| `/mnt/data/MOVIES` | `/mnt/data/movies/` | ✅ Yes |
| `smb://SERVER/share` | `smb://server/share/` | ✅ Yes |

---

## Database Constraints

Canonical keys are stored in the `Asset` table:
- `canonical_key`: Text field (full canonical key)
- `canonical_key_hash`: String(64) (SHA-256 hash)

Unique constraint: `(collection_uuid, canonical_key_hash)`

This ensures no duplicates within a collection while allowing efficient lookups via hash.
