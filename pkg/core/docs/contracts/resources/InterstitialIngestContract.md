# Contract — Interstitial Ingest

## Purpose

Defines how interstitial content (commercials, promos, station IDs, and similar
short-form assets) is discovered, tagged, and ingested into the RetroVue catalog
via the filesystem importer.

Interstitials are distinct from programme content in that their metadata is
inferred primarily from their directory location rather than from filenames or
embedded tags. This contract specifies the inference algorithm, the controlled
vocabulary, and the guarantees made during ingest.

---

## Discovery

`FilesystemImporter` (`adapters/importers/filesystem_importer.py`) scans one or
more `root_paths` for media files matching the configured `glob_patterns`.
Discovery is triggered via `discover()` and produces `DiscoveredItem` objects.

`list_collections()` returns a single collection descriptor representing all
configured `root_paths`. The collection's `external_id` is a 16-character hex
prefix of the SHA-256 hash of the sorted, resolved root paths — stable across
restarts so long as root paths do not change.

```python
# list_collections() output shape
{
    "external_id": "<sha256[:16] of sorted resolved root paths>",
    "name": "<source_name>",
    "type": "interstitial",
    "locations": ["<root_path_1>", "<root_path_2>", ...],
}
```

---

## Tag Inference

### Algorithm — `_infer_tags_from_path(file_path)`

Directory-based inference walks from the file's immediate parent directory up
toward the nearest matching `root_path` and applies two independent rule sets:
`type_rules` and `category_rules`.

**Walk order:** deepest directory first (most specific wins). The first match for
each rule set terminates that search; both searches can terminate independently.

Steps:
1. Resolve all `root_paths` to absolute paths.
2. Starting at `file_path.parent`, collect directory names walking toward the
   matching root. Stop when a root path is reached.
3. Normalise each directory name to lowercase.
4. Iterate the ordered name list (deepest first):
   - If `interstitial_type` is not yet assigned and the name matches a `type_rules`
     entry, assign the type tag.
   - If `interstitial_category` is not yet assigned and the name matches a
     `category_rules` entry, assign the category tag.
   - Stop iterating once both are assigned.
5. If no `type_rules` match was found, `interstitial_type` defaults to `"filler"`.
6. If no `category_rules` match was found, `interstitial_category` is `None` (omitted
   from `editorial`).

**Example:** A file at `Commercials/PSAs/health_spot.mp4` (with root at `Commercials/`
parent):
- Directory walk: `["PSAs", "Commercials"]` (deepest first)
- `"psas"` matches `type_rules` → `interstitial_type = "psa"`
- `"commercials"` would also match `type_rules`, but the search has already terminated
- Result: `type = psa`, not `commercial`

### Precedence Rule

> **INV-INFER-DEEPEST-WINS-001:** For `type_rules` and `category_rules` independently,
> the deepest (most specific) ancestor directory match takes precedence over any
> shallower ancestor match.

### Output Fields

Inference results are set on the `DiscoveredItem` as follows:

| Field | Location | Notes |
|-------|----------|-------|
| `editorial["interstitial_type"]` | Always set | Defaults to `"filler"` if no match |
| `editorial["interstitial_category"]` | Set if matched | Absent when no category match |
| `raw_labels` | Appended | `"interstitial_type:<type>"` and `"interstitial_category:<cat>"` labels |

---

## Controlled Vocabulary

### Interstitial Types (`type_rules`)

These are the canonical `interstitial_type` values. Only these values may appear
in `editorial.interstitial_type` via inference.

| Tag | Matched Directory Names |
|-----|------------------------|
| `commercial` | commercials, commercial, ads |
| `station_id` | station id, station ids, ident, idents |
| `stinger` | stinger, stingers |
| `bumper` | bumper, bumpers |
| `promo` | promo, promos, trailer, trailers, movie trailers, special programming, specials |
| `psa` | psa, psas, public service |
| `filler` | filler *(also the default when no match)* |

### Interstitial Categories (`category_rules`)

These are the canonical `interstitial_category` values.

| Tag | Matched Directory Names |
|-----|------------------------|
| `restaurant` | restaurant, restaurants, fast food |
| `auto` | auto, auto manufacturers, cars, car dealers, car care |
| `food` | food, sodas, drinks |
| `insurance` | insurance |
| `retail` | retail, box stores |
| `travel` | travel |
| `products` | products |
| `clothing` | clothes, clothing |
| `finance` | credit cards, credit card |
| `infomercial` | infomercials, infomercial |
| `local` | local |
| `show_promo` | show adverts, show advert |
| `station_promo` | station adverts, station advert, network ads, network ad |
| `home_video` | dvds, dvd, vhsdvd, vhs dvd, vhs/dvd |
| `misc` | odd, misc, miscellaneous, health, women, kitchen, businesses |
| `adult` | adult, adult content |
| `toys` | toys, kids toys |
| `tech` | video games, games, gaming |
| `entertainment` | music |
| `music_channel` | mtv |
| `tnt_channel` | tnt |

---

## Custom Inference Rules

Operators MAY supply custom `inference_rules` via the source configuration
(`--inference-rules` CLI flag or source YAML). The custom rules replace the
defaults entirely — they are not merged.

```yaml
# Custom rules example
inference_rules:
  type_rules:
    - match: [spots, spot]
      tag: commercial
    - match: [ids]
      tag: station_id
  category_rules:
    - match: [beverages, beer]
      tag: food
```

If `inference_rules` is omitted or `null`, `DEFAULT_INFERENCE_RULES` from
`filesystem_importer.py` apply.

---

## Sidecar Metadata

After directory inference, `_create_discovered_item()` checks for a sidecar
file adjacent to the media file. Supported extensions (checked in order):

1. `.retrovue.json`
2. `.json`
3. `.yaml`
4. `.yml`

If found, the sidecar is parsed and attached as `DiscoveredItem.sidecar`.
Sidecar errors are silently suppressed; discovery continues.

Sidecar metadata is authoritative over inferred metadata when the metadata
handler merges them during ingest.

---

## Behavior Contract Rules (B-#)

- **B-1:** Directory name matching is case-insensitive. `"Commercials"`, `"COMMERCIALS"`,
  and `"commercials"` are equivalent.
- **B-2:** `interstitial_type` MUST always be set on every `DiscoveredItem` produced
  by `FilesystemImporter`. The value MUST be one of the type vocabulary tags,
  or `"filler"` as the fallback.
- **B-3:** `interstitial_category` MUST be omitted from `editorial` (not set to `null`)
  when no category match is found.
- **B-4:** The raw label `"interstitial_type:<tag>"` MUST be appended to `raw_labels`
  regardless of whether the type was inferred or defaulted.
- **B-5:** The raw label `"interstitial_category:<tag>"` MUST only be appended to
  `raw_labels` when a category match occurred.
- **B-6:** `list_collections()` MUST return exactly one collection per `FilesystemImporter`
  instance, regardless of the number of `root_paths`.
- **B-7:** The collection `external_id` MUST be stable: the same `root_paths` (after
  resolution) always produce the same `external_id`.
- **B-8:** Inference rule evaluation MUST NOT raise exceptions. Files in directories
  that match no rules are tagged `interstitial_type=filler` with no category.

---

## Integration with Traffic Management

Assets ingested via this importer populate the `Interstitials` collection in the
catalog. `DatabaseAssetLibrary.get_filler_assets()` queries `asset_editorial.payload`
to read `interstitial_type` for allowed-type filtering (see
`docs/contracts/resources/TrafficManagementContract.md`, rule B-2).

Correct directory structure at ingest time is therefore a prerequisite for correct
traffic policy enforcement at playout time.

---

## See Also

- `adapters/importers/filesystem_importer.py` — FilesystemImporter, DEFAULT_INFERENCE_RULES
- `docs/contracts/resources/CollectionIngestContract.md` — general ingest contract
- `docs/contracts/resources/TrafficManagementContract.md` — how inferred types drive traffic policy
- `docs/contracts/runtime/INV-BREAK-PAD-EXACT-001.md` — break-level pad invariant
