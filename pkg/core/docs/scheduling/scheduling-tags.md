### Scheduling Tags for RetroVue (v0.1)

Last updated: 2025-11-02

Scheduling tags answer “when can we use this asset” for playout and programming. These are
operational classifications used by the scheduler and playlog builder, distinct from editorial
metadata in `metadata-taxonomy.md`.

Operational vs editorial
- Editorial fields describe what the asset is (title, synopsis, genres, credits, etc.).
- Scheduling tags classify how the asset may be used operationally (e.g., daypart fit, ad availability).
- Scheduling tags can be derived from editorial metadata and can be overridden by operations policy.

---

### Enums

These enumerations are used by the scheduler and may be persisted on the `Asset` or computed.

content_class
- Values: `cartoon`, `sitcom`, `live_action_kids`, `movie`, `promo`, `bumper`, `ad`
- Purpose: high-level operational class to drive block composition, compliance, and ad rules.

daypart_profile
- Values: `weekday_morning`, `after_school`, `prime`, `late_night`, `overnight`
- Purpose: coarse scheduling availability profile used by the scheduler to filter candidate assets.

ad_avail_model
- Values: `none`, `kids_30`, `standard_30`, `movie_longform`
- Purpose: ad/avails policy for the asset’s playout context.
  - `none`: no ad breaks expected (e.g., bumpers, promos, some movies if configured).
  - `kids_30`: kids-compliant 30s breaks only (cartoons/children’s content).
  - `standard_30`: standard 30s breaks (most general programming).
  - `movie_longform`: longform intervals (e.g., 2–3 breaks for movies).

Optional operational tags
- `network_brand` (string): a brand/channel label to include or exclude for themed/guide channels.
- `channel_style` (string): operator-defined style tags (e.g., `guide`, `music`, `retro_blocks`).

Persistence notes
- Tags may be stored on `Asset` (e.g., columns `content_class`, `daypart_profile`, `ad_avail_model`) or
  materialized in a `scheduling_tags` JSONB field. They are operational; default derivations can be
  recomputed, and manual overrides may be applied via ops UI or sidecar.

---

### Derivation from existing metadata

These are recommended heuristics. Exact policies are configurable per deployment.

Inputs
- `asset_type`, `genres`, `subgenres`, `themes`, `tone`, `content_rating`, `decade`, `bump_type`,
  `runtime_seconds`, promos/ads `air_window_*`.

Heuristic rules (examples)
- content_class
  - If `asset_type == "bumper"` → `content_class = bumper`.
  - If `asset_type == "promo"` → `content_class = promo`.
  - If `asset_type == "ad"` → `content_class = ad`.
  - Else if `genres` contains `animation` or `cartoon` → `content_class = cartoon`.
  - Else if `genres` contains `sitcom` or `comedy` and `runtime_seconds` ~ 1200–1500 → `sitcom`.
  - Else if `asset_type == "movie"` → `movie`.
  - Else if `genres` contains `family` and `tone` in {`light`,`whimsical`} → `live_action_kids`.

- daypart_profile
  - If `content_class in {cartoon, live_action_kids}` → `weekday_morning` or `after_school`.
  - Else if `content_rating.code` in {`TV-MA`, `R`} → `late_night`.
  - Else if `decade in {1950s, 1960s}` and `tone` is `light` → prefer `overnight` classic blocks.
  - Else → `prime`.

- ad_avail_model
  - If `content_class in {bumper, promo}` → `none`.
  - If `content_class == cartoon` → `kids_30`.
  - If `asset_type == "movie"` and `runtime_seconds >= 5400` → `movie_longform`.
  - Else → `standard_30`.

Overrides
- Operations can override any derived tag via ops UI or sidecar (see below). Overrides are recorded
  with provenance and take precedence over heuristic derivations.

---

### Sidecar overrides (operational)

Sidecars may set scheduling tags and mark them authoritative using `_meta.authoritative_fields`.
See `docs/metadata/sidecar-spec.md`.

Example excerpt
```json
{
  "content_class": "cartoon",
  "daypart_profile": "weekday_morning",
  "ad_avail_model": "kids_30",
  "network_brand": "RETRO-KIDS",
  "_meta": { "authoritative_fields": ["content_class","daypart_profile","ad_avail_model"] }
}
```

Resolution
- Authoritative operational tags rank as Manual/Sidecar(authoritative) in the global strategy and
  will override derived values.

---

### Examples

1) Episode (1992, animated, tagged cartoon)
- Metadata: `asset_type=episode`, `genres=["cartoon","comedy"]`, `decade="1990s"`, `runtime_seconds=1440`.
- Derived: `content_class=cartoon`, `daypart_profile=after_school`, `ad_avail_model=kids_30`.

2) Movie (1986, drama)
- Metadata: `asset_type=movie`, `genres=["drama"]`, `runtime_seconds=5400`.
- Derived: `content_class=movie`, `daypart_profile=prime`, `ad_avail_model=movie_longform`.

3) Promo (season launch)
- Metadata: `asset_type=promo`, `air_window_start=1989-09-01`, `air_window_end=1989-10-01`.
- Derived: `content_class=promo`, `daypart_profile=prime` (policy), `ad_avail_model=none`.

---

### Usage in scheduling

- The scheduler requires `content_class`, `daypart_profile`, and `ad_avail_model` to select eligible
  assets for a block and to enforce ad/spacer rules.
- The playlog builder uses these tags to materialize ad breaks and ensure compliance for themed
  blocks (e.g., `weekday_morning` kids programming).
- Tags connect the editorial metadata to the four-layer scheduling model by defining operational
  constraints and availability windows.



