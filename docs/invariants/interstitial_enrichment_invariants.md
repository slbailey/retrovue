# Interstitial Enrichment — Invariant List

Derived from: `docs/contracts/interstitial_enrichment.md`

---

### INV-INTERSTITIAL-TYPE-STAMP-001

Every interstitial asset ingested from a filesystem source MUST have `editorial.interstitial_type` set to a canonical type determined by the Collection Type Map. The collection name is authoritative. File-level inference MUST NOT override the collection-level type.

### Rationale

Without a single authoritative source for interstitial type, file-level inference and collection-level metadata could disagree, producing assets with incorrect canonical types that corrupt traffic selection.

### Enforcement Surface

- `InterstitialTypeEnricher` — overwrites `editorial.interstitial_type` using Collection Type Map lookup
- `apply_enrichers_to_collection()` — auto-injects the enricher at priority -1

### Test Coverage

- Each of the 9 collection names in the Collection Type Map MUST produce its corresponding canonical type after enrichment.
- A pre-existing file-level `interstitial_type` in editorial MUST be overwritten by the collection-level type.
- Other editorial fields (e.g. `title`, `interstitial_category`) MUST be preserved after enrichment.

---

### INV-INTERSTITIAL-TRAFFIC-VISIBILITY-001

`get_filler_assets()` MUST query for assets where `AssetEditorial.payload` contains the key `"interstitial_type"`. Assets lacking this key MUST NOT appear in traffic candidate lists regardless of state, collection membership, or duration.

### Rationale

The `interstitial_type` JSONB key is the sole signal that an asset is interstitial media. Without this gate, program content or un-enriched assets could leak into commercial breaks.

### Enforcement Surface

- `DatabaseAssetLibrary.get_filler_assets()` — JSONB key-presence filter on `AssetEditorial.payload`

### Test Coverage

- An asset with `interstitial_type` present, `state='ready'`, and valid `duration_ms` MUST appear in results when its type is in `allowed_types`.
- An asset without `interstitial_type` in payload MUST NOT appear in results regardless of state or duration.

---

### INV-INTERSTITIAL-TRAFFIC-BOUNDARY-001

`TrafficManager`, `TrafficPolicy`, and `DatabaseAssetLibrary` MUST NOT reference collection names, collection UUIDs, source names, or filesystem paths. The `interstitial_type` field in `AssetEditorial.payload` is the sole bridge between storage topology and traffic semantics.

### Rationale

Coupling the traffic layer to storage topology would make traffic selection fragile to filesystem reorganization and violate the separation between ingest-time classification and runtime selection.

### Enforcement Surface

- `TrafficManager` — selects by `interstitial_type`, not collection identity
- `TrafficPolicy` — evaluates candidates by type, cooldown, and cap; no storage references
- `DatabaseAssetLibrary` — queries by JSONB payload field, not by collection

### Test Coverage

- `get_filler_assets()` MUST NOT reference collection name or collection UUID in its query.
- `TrafficPolicy.evaluate_candidates()` MUST operate on `TrafficCandidate` objects with no collection identity fields.

---

### INV-INTERSTITIAL-ENRICHER-INJECT-001

`apply_enrichers_to_collection()` MUST auto-inject `InterstitialTypeEnricher` at priority -1 for collections whose name appears in the Collection Type Map. No manual enricher attachment is required for interstitial collections.

### Rationale

Manual enricher configuration per collection is error-prone. Auto-injection at priority -1 guarantees that canonical type stamping occurs before any user-configured enrichers, preventing type-less assets from reaching the database.

### Enforcement Surface

- `apply_enrichers_to_collection()` — checks collection name against Collection Type Map keys and prepends `InterstitialTypeEnricher`

### Test Coverage

- A collection named in the Collection Type Map MUST have `InterstitialTypeEnricher` in its enricher pipeline without explicit attachment.
- The auto-injected enricher MUST execute before all other enrichers (priority -1).

---

### INV-INTERSTITIAL-UNKNOWN-REJECT-001

If a collection name is not a key in the Collection Type Map, the `InterstitialTypeEnricher` MUST raise an error. Silent fallback to any default type MUST NOT occur.

### Rationale

A silent fallback would assign an incorrect canonical type, creating assets that appear in traffic selection under the wrong category. Failing loudly forces the operator to either add the collection to the map or correct the directory structure.

### Enforcement Surface

- `InterstitialTypeEnricher.__init__()` — raises `EnricherConfigurationError` at construction time for unmapped names
- `InterstitialTypeEnricher.enrich()` — raises `EnricherError` at enrichment time if resolution fails

### Test Coverage

- Constructing `InterstitialTypeEnricher` with an unmapped collection name MUST raise `EnricherConfigurationError`.
- Calling `enrich()` when the collection name cannot be resolved MUST raise `EnricherError`.

---

### INV-INTERSTITIAL-CONFIDENCE-DURATION-001

If `duration_ms` is missing, zero, negative, or exceeds 10,800,000ms (3 hours), confidence MUST be 0.0. The asset MUST NOT be auto-promoted to ready state.

### Rationale

An asset without valid duration cannot be placed in a timed break slot. Auto-promoting such an asset would create a scheduling hole or overflow when the traffic manager attempts to fill a break.

### Enforcement Surface

- `compute_confidence_from_labels()` — forces confidence to 0.0 when duration is invalid
- `apply_enrichers_to_collection()` — compares confidence against `auto_ready_threshold` before state promotion

### Test Coverage

- An asset missing `duration_ms` MUST receive confidence 0.0.
- An asset with `duration_ms = 0` MUST receive confidence 0.0.
- An asset with `duration_ms` exceeding 10,800,000ms MUST receive confidence 0.0.
- An asset with confidence below `auto_ready_threshold` MUST NOT be auto-promoted to ready.

---

### INV-INTERSTITIAL-ENRICHMENT-IDEMPOTENT-001

Assets whose `last_enricher_checksum` matches the current pipeline checksum MUST be skipped during re-enrichment. The pipeline checksum MUST be the SHA-256 hex digest of the JSON-serialized enricher signature list.

### Rationale

Without idempotency, re-running enrichment would redundantly reprocess every asset on every ingest cycle, wasting compute and risking unintended side effects from non-idempotent enrichers.

### Enforcement Surface

- `apply_enrichers_to_collection()` — computes pipeline checksum from enricher signatures and compares against `asset.last_enricher_checksum`

### Test Coverage

- Re-enrichment with the same pipeline checksum MUST skip already-enriched assets.
- Re-enrichment with a changed pipeline checksum MUST re-process previously enriched assets.

---

### INV-INTERSTITIAL-INFERENCE-FILLER-DEFAULT-001

When no type inference rule matches any ancestor directory of a discovered file, `interstitial_type` MUST default to `"filler"`.

### Rationale

Every discovered interstitial file must carry a canonical type to be visible to traffic selection. Defaulting to `"filler"` ensures no file is left type-less while using the least-specific type to avoid false categorization.

### Enforcement Surface

- `FilesystemImporter._infer_tags_from_path()` — applies `"filler"` when no type rule matches

### Test Coverage

- A file under a directory matching no type inference rule MUST have `editorial.interstitial_type` set to `"filler"` after discovery.

---

### INV-INTERSTITIAL-DISCOVERY-METADATA-001

Every discovered file MUST produce a `DiscoveredItem` with `editorial.title` (file stem), `editorial.size` (file stat), and `editorial.modified` (ISO timestamp from file stat).

### Rationale

These three fields are the minimum editorial metadata required for downstream enrichment and confidence scoring. Missing any of them would break the enrichment pipeline or produce un-schedulable assets.

### Enforcement Surface

- `FilesystemImporter._create_discovered_item()` — populates title, size, and modified from the filesystem

### Test Coverage

- A file matching a configured glob pattern MUST produce a `DiscoveredItem` containing all three required editorial fields.
- `title` MUST equal the file stem (filename without extension).

---

### INV-INTERSTITIAL-READY-GATE-001

An asset MUST have `state='ready'` to be eligible for traffic selection. Assets in any other state MUST NOT appear in `get_filler_assets()` results.

### Rationale

Assets that have not completed enrichment (state `new` or `enriching`) may lack valid duration, type, or technical metadata. Allowing them into traffic selection would risk scheduling assets that cannot be played out.

### Enforcement Surface

- `DatabaseAssetLibrary.get_filler_assets()` — filters on `Asset.state == 'ready'`

### Test Coverage

- An asset with `state='ready'`, valid `duration_ms`, and `interstitial_type` present MUST appear in results.
- An asset with `state='new'` MUST NOT appear in results.

---

### INV-INTERSTITIAL-DURATION-BOUND-001

An asset MUST have a non-null, positive `duration_ms` that does not exceed the requested `max_duration_ms` to be eligible for traffic selection. Assets with null `duration_ms` MUST be excluded from traffic candidate queries.

### Rationale

Break slots have finite budgets. An asset with zero, negative, or excessive duration cannot be correctly placed in a break without creating a timing violation.

### Enforcement Surface

- `DatabaseAssetLibrary.get_filler_assets()` — filters on `Asset.duration_ms` being non-null, positive, and within `max_duration_ms`

### Test Coverage

- An asset with null `duration_ms` MUST NOT appear in `get_filler_assets()` results.
- An asset with `duration_ms` exceeding `max_duration_ms` MUST NOT appear in results.
- An asset with positive `duration_ms` within bounds MUST appear in results (given other eligibility criteria are met).

---

### INV-INTERSTITIAL-COLLECTION-DEPTH-001

Collection discovery MUST enumerate only immediate subdirectories of each root path. It MUST NOT recurse beyond the first level.

### Rationale

Collections are the organizational unit for interstitial media. Recursing deeper would conflate subcategory directories with collections, producing incorrect collection-to-type mappings and duplicate collection entries.

### Enforcement Surface

- `FilesystemImporter.list_collections()` — enumerates first-level subdirectories only

### Test Coverage

- Immediate subdirectories of a root path MUST each produce one collection entry.
- Files at the root level MUST NOT produce collection entries.
- Nested subdirectories MUST NOT produce additional collection entries.

---

### INV-INTERSTITIAL-SIDECAR-FAULT-TOLERANCE-001

Discovery MUST NOT fail due to missing or malformed sidecar files. If a sidecar file does not exist or cannot be parsed, the `sidecar` field MUST be `None` and discovery MUST continue.

### Rationale

Sidecar files are optional operator-provided metadata. A parse error or missing file in one sidecar must not halt discovery of the entire collection, which could contain thousands of valid media files.

### Enforcement Surface

- `FilesystemImporter._create_discovered_item()` — catches sidecar load failures and sets `sidecar = None`

### Test Coverage

- Discovery of a media file with no adjacent sidecar MUST succeed with `sidecar = None`.
- Discovery of a media file with a malformed sidecar MUST succeed with `sidecar = None`.
- Discovery MUST NOT raise an exception due to sidecar errors.

---

### INV-INTERSTITIAL-CONFIDENCE-SCORING-001

Confidence MUST be scored as: +0.2 for `size > 0`, +0.3 for valid `duration_ms` (0 < dur <= 10,800,000ms), +0.2 for `video_codec` present, +0.1 for `audio_codec` present, +0.1 for `container` present. Maximum score is 1.0.

### Rationale

The confidence formula determines whether an asset is auto-promoted to ready state. The weights reflect the relative importance of each metadata signal: duration is the most critical (0.3), followed by size and video codec, with audio codec and container format as secondary signals.

### Enforcement Surface

- `compute_confidence_from_labels()` — applies the scoring formula to `raw_labels`

### Test Coverage

- An asset with all five signals present MUST receive the maximum confidence (0.9, clamped to 1.0 ceiling).
- An asset missing `duration_ms` MUST receive confidence 0.0 (not just a 0.3 reduction).
- An asset with `size > 0` and valid `duration_ms` but no codec labels MUST receive confidence 0.5.

---

### INV-INTERSTITIAL-COLLECTION-ID-STABLE-001

Each collection MUST receive a stable `external_id` derived from the SHA-256 hash of the subdirectory's resolved absolute path (first 16 hex characters).

### Rationale

Collection identity must be deterministic and path-dependent so that the same directory always produces the same external_id, while identically named directories at different absolute paths produce distinct identifiers.

### Enforcement Surface

- `FilesystemImporter.list_collections()` — computes `external_id` from SHA-256 of resolved absolute path

### Test Coverage

- Two invocations of `list_collections()` on the same root MUST produce identical `external_id` values for each subdirectory.
- Two different root paths containing the same subdirectory name at different absolute paths MUST produce distinct `external_id` values.
