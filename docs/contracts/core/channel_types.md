# Contract: Channel Types & Break Placement

**Status:** Draft v1

## Purpose

Define the `channel_type` field as the authoritative driver of traffic break
placement behavior. The channel type determines WHERE ad/promo breaks are
placed relative to content — not the individual asset type or segment
configuration.

## Channel Type Field

Every channel YAML MUST declare a `channel_type`:

```yaml
channel_type: network    # or: movie, premium
```

This is a top-level field in the channel config, alongside `channel`,
`channel_number`, `name`, and `timezone`.

## Defined Channel Types

### `network`

Emulates ad-supported broadcast/cable television.

- **Break placement:** Mid-content (at chapter markers or computed breakpoints)
- **Ad time distribution:** Split equally across inter-act breaks
- **Traffic allowed:** All types (commercial, promo, bumper, etc.)
- **Use case:** Sitcoms, dramas, procedurals — any episodic content with act structure

```
[Act 1] → [Ad Break] → [Act 2] → [Ad Break] → [Act 3] → [Ad Break] → [Act 4]
```

### `movie`

Emulates premium movie channels (HBO, Showtime, Cinemax).

- **Break placement:** Post-content ONLY — movie plays uninterrupted
- **Ad time distribution:** Single filler block after movie ends, before next grid boundary
- **Traffic allowed:** Promos only (no commercials by convention)
- **Use case:** Feature films, specials, long-form content that should not be interrupted

```
[Full Movie] → [Promos / Trailers / Bumpers until next grid slot]
```

### Future Types (reserved, not yet implemented)

| Type | Description | Break Pattern |
|------|-------------|---------------|
| `music` | MTV-style video blocks | Between videos, top-of-hour breaks |
| `news` | Rolling news format | Hard breaks at :00 and :30 |
| `sports` | Live/replay sports | Break at period/quarter/half boundaries |

## Behavior Rules

### B-CT-1: Channel type drives break placement

The playout log expander MUST use `channel_type` to determine break placement
strategy. It MUST NOT use asset type, segment type, or per-block configuration
to make this decision.

### B-CT-2: Movie type = zero mid-content breaks

When `channel_type = movie`, `expand_program_block()` MUST produce:
1. A single content segment spanning the entire movie
2. A single filler segment for the remaining time (slot_duration - movie_duration)
3. Zero mid-content break points, regardless of chapter markers

### B-CT-3: Network type = mid-content breaks (existing behavior)

When `channel_type = network`, `expand_program_block()` uses the existing
chapter-marker / computed-breakpoint logic unchanged.

### B-CT-4: Channel type is required

Channels without a `channel_type` field MUST default to `network` for
backward compatibility.

### B-CT-5: Traffic policy remains independent

`channel_type` controls break PLACEMENT. The `traffic:` block controls break
CONTENT (what types of assets fill the breaks). These are orthogonal:

- A `network` channel with `allowed_types: [promo]` gets mid-episode breaks
  filled with promos only.
- A `movie` channel with `allowed_types: [promo]` gets a post-movie block
  filled with promos only.

## Impact on Existing Code

| Component | Change |
|-----------|--------|
| Channel YAML configs | Add `channel_type` field |
| `yaml_channel_config_provider.py` | Extract `channel_type` into schedule_config |
| `playout_log_expander.py` | Accept `channel_type` param; implement post-content strategy |
| `dsl_schedule_service.py` | Pass `channel_type` through to expander |

## See Also

- `docs/contracts/resources/TrafficManagementContract.md` — traffic policy (break content)
- `docs/contracts/core/programming_dsl.md` — DSL syntax and schedule architecture
- `docs/roadmap/` — ads & packaging roadmap
