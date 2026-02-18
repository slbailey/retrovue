# Contract — Traffic Management

## Purpose

Defines the behavioral rules for the traffic management system: how interstitial
assets are selected, scheduled into ad breaks, and tracked across channels.

The system is split along a clean **policy / state** boundary:

- **Policy** (what is allowed) is declared in human-editable YAML channel config files
  under `/opt/retrovue/config/channels/`.
- **State** (what has aired) is machine-tracked in the `traffic_play_log` database table.

This separation means operators edit YAML to change channel rules; the database
accumulates the audit trail automatically.

---

## Architecture Overview

```
Channel YAML (policy)          DatabaseAssetLibrary           traffic_play_log (state)
  _defaults.yaml          ──▶  get_filler_assets()       ──▶   cooldown exclusions
  <channel>.yaml               log_play()               ──▶   daily cap counts
                               get_duration_ms()
                               get_markers()
```

**`DatabaseAssetLibrary`** (`catalog/db_asset_library.py`) implements the `AssetLibrary`
protocol defined in `planning_pipeline.py`. It is channel-aware: the `channel_slug`
constructor parameter matches the base filename of the channel's YAML config (e.g., slug
`retro-prime` maps to `/opt/retrovue/config/channels/retro-prime.yaml`).

---

## Traffic Policy

### Policy Loading

Policy is resolved in two layers at `DatabaseAssetLibrary` instantiation time:

1. `_defaults.yaml` is loaded first as the base policy.
2. The channel-specific `<channel_slug>.yaml` is loaded and merged over the defaults.

Loading is performed by `_load_channel_traffic_policy()` using the same
`_load_yaml_with_includes` loader as the rest of RetroVue (supporting `!include` directives).
If neither file exists, `DEFAULT_TRAFFIC_POLICY` is used.

Policy is cached in `_policy` for the lifetime of the `DatabaseAssetLibrary` session.

### Policy Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `allowed_types` | list[str] | all types | Interstitial types permitted on this channel |
| `default_cooldown_seconds` | int | 3600 | Minimum seconds between re-plays of the same asset |
| `type_cooldowns` | dict[str, int] | `{}` | Per-type cooldown overrides (seconds) |
| `max_plays_per_day` | int | 0 | Max plays per asset per channel per UTC day; `0` = unlimited |

### Example Policy (defaults)

```yaml
traffic:
  allowed_types: [commercial, promo, station_id, psa, stinger, bumper, filler]
  default_cooldown_seconds: 3600
  type_cooldowns:
    commercial: 3600
    promo: 1800
  max_plays_per_day: 0    # 0 = unlimited
```

### Premium Channel Restriction

Premium channels set `allowed_types: [promo]` to prohibit commercials from appearing on
ad-free tiers:

```yaml
# showtime-cinema.yaml
traffic:
  allowed_types: [promo]
  default_cooldown_seconds: 7200
  max_plays_per_day: 3
```

Channels without a `traffic:` block inherit the full defaults.

---

## Behavior Contract Rules (B-#)

### B-1: Interstitial Selection

`get_filler_assets(max_duration_ms, count)` MUST:

1. Resolve the interstitial collection by name (`"Interstitials"` by default).
2. Query `assets` JOIN `asset_editorial` where `collection_uuid` matches, `state = 'ready'`,
   `duration_ms > 0`, and `duration_ms <= max_duration_ms`.
3. Apply the three exclusion filters (allowed type, cooldown, daily cap) in order.
4. Shuffle the surviving candidates and return up to `count` results as `FillerAsset` objects.

If no interstitial collection exists, `get_filler_assets()` returns `[]` without error.

### B-2: Allowed Type Filtering

Each candidate asset's `interstitial_type` is read from `asset_editorial.payload`.
If `interstitial_type` is absent, it defaults to `"filler"`.

An asset is excluded if its `interstitial_type` is not in `policy["allowed_types"]`.

### B-3: Cooldown Enforcement

`_get_cooled_down_uris()` queries `traffic_play_log` for all plays on `channel_slug`
within the past `max(default_cooldown_seconds, max(type_cooldowns.values()))` seconds.
For each recent play, the applicable cooldown (type-specific if present, else default)
is checked against `now - played_at`. Assets whose URI appears in any qualifying row
are excluded.

- Cooldown is keyed on `asset_uri`.
- Cooldown is channel-scoped: an asset cooled down on `retro-prime` is still available on `cheers-24-7`.
- If `default_cooldown_seconds = 0` and `type_cooldowns` is empty, no cooldown is applied.

### B-4: Daily Cap Enforcement

`_get_daily_capped_uuids()` counts plays per `asset_uuid` on `channel_slug` since
UTC midnight today. Any asset with `COUNT(*) >= max_plays_per_day` is excluded.

- Daily cap is keyed on `asset_uuid`.
- `max_plays_per_day = 0` disables cap enforcement entirely (no DB query is performed).
- The UTC day boundary is used regardless of channel timezone.

### B-5: Play Logging

`log_play(asset_uri, asset_uuid, asset_type, duration_ms, break_index, block_id, played_at)`
MUST write one row to `traffic_play_log`.

- `channel_slug` MUST be set; if the library was instantiated without a slug, `log_play()` is a no-op.
- `played_at` defaults to `datetime.now(timezone.utc)` when not supplied.
- The caller (planning or playout) is responsible for committing the session after `log_play()`.

### B-6: Protocol Compliance

`DatabaseAssetLibrary` MUST satisfy the full `AssetLibrary` protocol:

| Method | Backing store |
|--------|--------------|
| `get_filler_assets(max_duration_ms, count)` | DB query + policy filter |
| `get_duration_ms(asset_uri)` | `assets.duration_ms` by `canonical_uri` or `uri` |
| `get_markers(asset_uri)` | `markers` table ordered by `start_ms` |

---

## Data Contract Rules (D-#)

### D-1: traffic_play_log Table Schema

```sql
CREATE TABLE traffic_play_log (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    channel_slug  VARCHAR(255) NOT NULL,
    asset_uuid    UUID NOT NULL REFERENCES assets(uuid) ON DELETE CASCADE,
    asset_uri     TEXT NOT NULL,
    asset_type    VARCHAR(50) NOT NULL,
    played_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    break_index   INTEGER,
    block_id      VARCHAR(255),
    duration_ms   INTEGER NOT NULL
);

CREATE INDEX ix_traffic_play_log_channel_played
    ON traffic_play_log (channel_slug, played_at);

CREATE INDEX ix_traffic_play_log_channel_asset
    ON traffic_play_log (channel_slug, asset_uuid, played_at);
```

### D-2: Index Intent

- `ix_traffic_play_log_channel_played` — used by `_get_cooled_down_uris()` to scan recent plays for a channel within the cooldown window.
- `ix_traffic_play_log_channel_asset` — used by `_get_daily_capped_uuids()` to aggregate per-asset play counts since midnight.

### D-3: Cascade Delete

`asset_uuid` carries `ON DELETE CASCADE`. Deleting an asset from `assets` removes its play history from `traffic_play_log`.

### D-4: Channel Slug Stability

`channel_slug` MUST exactly match the YAML config filename stem (e.g., `retro-prime` not `Retro Prime`). Policy loading and log queries both use this slug as the join key. Renaming a channel's YAML file without migrating the DB breaks cooldown history.

---

## Invariants

**INV-TRAFFIC-POLICY-SOURCE-001:** Policy MUST come from YAML; it MUST NOT be stored in or read from the database.

**INV-TRAFFIC-STATE-SOURCE-001:** Play history MUST come from `traffic_play_log`; it MUST NOT be inferred from asset metadata or static config.

**INV-TRAFFIC-CHANNEL-SCOPED-001:** All cooldown and cap queries MUST be filtered by `channel_slug`. Cross-channel contamination is a correctness violation.

---

## See Also

- `catalog/db_asset_library.py` — DatabaseAssetLibrary implementation
- `runtime/planning_pipeline.py` — AssetLibrary protocol and fill_breaks()
- `docs/contracts/runtime/INV-BREAK-PAD-EXACT-001.md` — break-level pad invariant
- `docs/contracts/resources/InterstitialIngestContract.md` — how interstitials enter the catalog

---

## Late-Binding Traffic Architecture (INV-TRAFFIC-LATE-BIND-001)

As of 2026-02-18, traffic fill moves from compile time to **feed time**.

See `docs/contracts/runtime/INV-TRAFFIC-LATE-BIND-001.md` for the full invariant.

### Before (removed)

Traffic fill occurred in `DslScheduleService._expand_blocks_inner()` during
schedule compilation, hours before air. `DatabaseAssetLibrary` was created at
compile time; cooldowns were evaluated then, not at air time.

### After (current)

`DslScheduleService._compile_day()` produces blocks with **empty filler
placeholders** (`asset_uri=""`, `segment_type="filler"`). These are stored in
`compiled_program_log`.

`BlockPlanProducer._try_feed_block()` fills these placeholders ~30 minutes before
air using a fresh `DatabaseAssetLibrary` session. Cooldowns, daily caps, and type
filters are evaluated against current play history.

### Transmission Log Persistence

After fill, the filled block is written to the `transmission_log` table
(see `docs/contracts/runtime/TransmissionLogPersistenceContract.md`).
This is the authoritative record of what actually aired.

### As-Run Enrichment via transmission_log

The evidence server reads `transmission_log` on each `SEG_START` event to
enrich `.asrun` and `.asrun.jsonl` with commercial titles and segment types
(see `docs/contracts/runtime/AsRunEnrichmentContract.md`).

The in-process `SegmentLookup` singleton (`segment_lookup.py`) is removed.
