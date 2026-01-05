## Metadata Handler Contract

### Purpose
Defines the request/response shapes and responsibilities for `retrovue.usecases.metadata_handler.handle_ingest(...)`.

### Input shape

```json
{
  "importer_name": "plex",
  "asset_type": "movie",
  "source_uri": "plex://39593",
  "editorial": { },
  "probed": { },
  "sidecars": [ { }, { } ]
}
```

Notes:
- `editorial`, `probed`, and `sidecars` are optional; omit when not available.
- `sidecars` is a list; the handler validates/merges sidecars, enforcing precedence rules.

### Output shape

```json
{
  "canonical_uri": "file:///R:/media/anime-movies/akira (1988)/akira (1988) webdl-480p.mkv",
  "editorial": { },        
  "probed": { },           
  "station_ops": { },      
  "relationships": { },    
  "sidecar": { }           
}
```

Notes:
- `editorial` is the unified, merged view from importer + enrichers + sidecar.
- `probed` is the unified technical block (e.g., ffprobe), merged across sources.
- `station_ops` and `relationships` are optional domains that may be resolved by the handler.
- `sidecar` is the final validated canonical sidecar (single object), after merge/validation.

### Responsibilities
- The caller (ingest orchestration) is responsible for persisting each non-empty block to its dedicated table:
  - `asset_editorial(payload jsonb)`
  - `asset_probed(payload jsonb)`
  - `asset_station_ops(payload jsonb)`
  - `asset_relationships(payload jsonb)`
  - `asset_sidecar(payload jsonb)`
- Dry-run mode should execute the full handler and include resolved blocks in CLI output but must not commit.
