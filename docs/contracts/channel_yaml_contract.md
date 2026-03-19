# Channel YAML — Domain Contract

Status: Contract
Authority Level: Planning
Derived From: `LAW-IMMUTABILITY`, `LAW-DERIVATION`

---

## Overview

A channel YAML file defines a single broadcast channel. It contains three categories of data:

1. **Identifiers** — scalar values that uniquely identify the channel.
2. **Pass-through domain data** — editorial content definitions (pools, programs, schedule, traffic) consumed by the scheduling pipeline. These have no corresponding defaults.
3. **Defaults overrides** — optional dict-valued keys that shadow specific entries in `config/defaults.yaml` for this channel only.

This contract defines the structure, naming, and validation rules for channel YAML files. It complements `configuration_resolution.md`, which defines how the merge is performed.

### Authority Boundary

This contract owns:
- The schema of channel YAML files
- Which keys are identifiers, pass-through, or governed overrides
- The naming and shape requirements for each section
- The relationship between `format:` and `channel.default_program_format` / `channel.encoding`

This contract does NOT own:
- The merge algorithm (owned by `configuration_resolution.md`)
- The content of `config/defaults.yaml` (owned by the defaults audit)
- DSL schedule semantics (owned by `channel_dsl.md`)
- Traffic policy semantics (owned by `traffic_policy.md`)

---

## 1. Identifiers

Scalar top-level keys that identify and describe the channel. These are pass-through — they do not participate in defaults merging.

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `channel` | `str` | MUST | Unique channel slug (`"hbo"`, `"cheers-24-7"`). Becomes `channel_id` in resolved config (renamed to avoid collision with the governed `channel` domain). |
| `number` | `int` | MUST | External channel number (Plex GuideNumber, XMLTV id). MUST be positive. MUST be unique across all channels. |
| `name` | `str` | SHOULD | Human-readable display name. Defaults to titleized slug if omitted. |
| `channel_type` | `str` | SHOULD | Channel classification: `"network"`, `"premium"`, `"movie"`. Defaults to `scheduling.default_channel_type` from defaults.yaml if omitted. |
| `timezone` | `str` | SHOULD | IANA timezone for broadcast day computation. Defaults to `scheduling.default_timezone` from defaults.yaml if omitted. |

---

## 2. Pass-through Domain Data

Dict-valued top-level keys containing channel-specific editorial data. These are NOT governed by `defaults.yaml` — they pass through to the resolved config without validation against defaults.

| Key | Description | Governed by |
|-----|-------------|-------------|
| `format` | Output technical format (video resolution, frame rate, audio, grid minutes) | This contract §4 |
| `pools` | Content pool definitions (asset matching rules) | `channel_dsl.md` |
| `programs` | Program definitions (pool bindings, grid sizing, fill mode, presentation) | `program_definition.md` |
| `schedule` | Day-of-week schedule blocks (start times, slots, progression) | `scheduling_contract.md` |
| `traffic` | Break config, traffic inventories, traffic profiles | `traffic_policy.md` |
| `filler` | Filler asset path and duration (optional) | This contract §5 |

---

## 3. Defaults Overrides

A channel YAML MAY contain dict-valued top-level keys whose names match governed domains in `defaults.yaml`. When present, these are recursively merged into the defaults per the rules in `configuration_resolution.md`.

### Overridable Domains

| Domain | Typical per-channel overrides | Example |
|--------|------------------------------|---------|
| `channel` | `linger_seconds`, `encoding.video_bitrate_bps` | HBO keeps producer alive longer |
| `hls` | `segmenter.target_duration_ms`, `ring.capacity` | Lower-latency HLS for sports |
| `playout` | `transitions.default_fade_duration_ms` | No fades on movie channels |
| `streaming` | `buffers.client_buffer_bytes` | Higher buffer for high-bitrate channels |

### Domains That SHOULD NOT Be Overridden Per-Channel

| Domain | Reason |
|--------|--------|
| `system` | Ports, paths, database — system-wide, not per-channel |
| `integrations` | Plex/IPTV emulation — system-wide, not per-channel |
| `air` | Engine tunables — uniform across channels in a deployment |
| `scheduling` | Compiler behavior, grid geometry — uniform across channels |

The resolution system does not prevent these overrides, but channels that override system-wide domains create operational hazards (e.g., two channels with different database pool sizes).

---

## 4. Format Section

The `format:` key in channel YAML describes the technical output format for the channel. It is pass-through domain data — it has no direct equivalent in defaults.yaml. However, its values MUST be consumed by `YamlChannelConfigProvider` to construct `ProgramFormat` and `ChannelConfig` objects.

### Current Shape

```yaml
format:
  video: { width: 1280, height: 720, frame_rate: "30000/1001" }
  audio: { sample_rate: 48000, channels: 2 }
  grid_minutes: 30
```

### Relationship to Defaults

| Channel YAML path | Defaults.yaml equivalent | Notes |
|-------------------|--------------------------|-------|
| `format.video.width` | `channel.default_program_format.width` | Channel overrides default resolution |
| `format.video.height` | `channel.default_program_format.height` | Channel overrides default resolution |
| `format.video.frame_rate` | Derived from `channel.default_program_format.frame_rate_numerator/denominator` | String format vs split numerator/denominator |
| `format.audio.sample_rate` | `channel.default_program_format.sample_rate` | Direct equivalent |
| `format.audio.channels` | `channel.default_program_format.audio_channels` | Direct equivalent |
| `format.video.aspect_policy` | `channel.encoding.aspect_policy` | Not in current channel YAMLs; always from defaults |
| `format.grid_minutes` | `scheduling.grid_minutes.{template}` | Flat int vs template-keyed map |

---

## 5. Filler Section

Optional per-channel filler configuration. When omitted, defaults apply.

```yaml
filler:
  path: "/path/to/filler.mp4"
  duration_ms: 3650000
```

If the `filler:` key is absent, `YamlChannelConfigProvider` applies hardcoded defaults (`/opt/retrovue/assets/filler.mp4`, `3650000`). These defaults SHOULD be moved to `config/defaults.yaml` under `channel.filler`.

---

## 6. Shape Mismatches — Audit Findings

### HIGH severity — will cause resolution failure or ambiguity

#### H1: `channel:` key collision

| | |
|-|-|
| **File** | `hbo.yaml`, `cheers-24-7.yaml` |
| **YAML path** | `channel` (top-level) |
| **Current shape** | `channel: "hbo"` — scalar string |
| **Expected shape** | Not a governed domain key. `channel` in defaults.yaml is a dict. |
| **Impact** | The resolver has a workaround: scalar `channel` is renamed to `channel_id` in the resolved config, while the governed `channel:` dict is preserved. This works but creates a naming asymmetry: the YAML says `channel:` but the resolved config has `channel_id:`. |
| **Recommendation** | **Rename the identifier key from `channel:` to `channel_id:`** in all channel YAMLs. This eliminates the collision and the rename workaround in the resolver. The key `channel:` would then be available exclusively for governed defaults overrides. |

#### H2: `format.grid_minutes` — orphaned from scheduling domain

| | |
|-|-|
| **File** | `hbo.yaml:10`, `cheers-24-7.yaml:10` |
| **YAML path** | `format.grid_minutes` |
| **Current shape** | `format.grid_minutes: 30` — flat integer inside the format pass-through |
| **Expected shape** | Grid minutes is a scheduling concern (`scheduling.grid_minutes.{template}`), not a format concern. The `format:` section describes technical output (video/audio), not editorial grid geometry. |
| **Impact** | `YamlChannelConfigProvider` extracts `grid_minutes` from `format` and stuffs it into `schedule_config`. It cannot participate in defaults merging because it's nested under a pass-through key (`format`) instead of a governed key (`scheduling`). |
| **Recommendation** | Move `grid_minutes` to a top-level key or under a governed scheduling override. |

### MEDIUM severity — inconsistent but survivable

#### M1: `format.video.frame_rate` vs `channel.default_program_format` shape divergence

| | |
|-|-|
| **File** | `hbo.yaml:8`, `cheers-24-7.yaml:8` |
| **YAML path** | `format.video.frame_rate` |
| **Current shape** | `frame_rate: "30000/1001"` — a string `"num/den"` |
| **Expected shape** | `channel.default_program_format` in defaults.yaml uses split keys: `frame_rate_numerator: 30000`, `frame_rate_denominator: 1001` |
| **Impact** | The `ProgramFormat.from_dict()` method accepts the string format and parses it, so this works at runtime. But the two representations cannot be merged by the config resolver — they have different shapes. A channel cannot override `channel.default_program_format.frame_rate_numerator` using `format.video.frame_rate: "30000/1001"` because they live in different namespaces. |
| **Recommendation** | Standardize on one representation. The string format (`"30000/1001"`) is more ergonomic for YAML authors. The split format is more explicit for code. Pick one and use it everywhere. |

#### M2: `format.video` / `format.audio` vs `channel.default_program_format` structural divergence

| | |
|-|-|
| **File** | All channel YAMLs |
| **YAML path** | `format.video.width`, `format.audio.sample_rate`, etc. |
| **Current shape** | Nested under `format.video` / `format.audio` — two-level hierarchy |
| **Expected shape** | `channel.default_program_format` is flat: `width`, `height`, `sample_rate`, `audio_channels` |
| **Impact** | `format:` cannot be merged with `channel.default_program_format` because the nesting differs. `YamlChannelConfigProvider` manually maps between the two shapes via `ProgramFormat` construction. This mapping contains its own hardcoded defaults (e.g., `video.get("width", 1280)`). |
| **Recommendation** | Either: (a) move the format section into the governed `channel.default_program_format` path with matching shape, or (b) keep `format:` as pass-through and document that `channel.default_program_format` applies only when `format:` is absent. |

#### M3: `YamlChannelConfigProvider` has its own hardcoded defaults

| | |
|-|-|
| **File** | `yaml_channel_config_provider.py:178-183, 190-193` |
| **YAML path** | N/A (code, not YAML) |
| **Current shape** | `.get("width", 1280)`, `.get("frame_rate", "30000/1001")`, `filler_path = .get("path", "/opt/retrovue/assets/filler.mp4")` |
| **Expected shape** | All defaults should come from `config/defaults.yaml` via `resolved_config` |
| **Impact** | A third source of defaults exists outside the config system. If `config/defaults.yaml` changes `channel.default_program_format.width` to 1920, `YamlChannelConfigProvider` still falls back to 1280 for channels that omit `format.video.width`. |
| **Recommendation** | `YamlChannelConfigProvider` MUST read fallback values from `resolved_config["channel"]["default_program_format"]` and `resolved_config["channel"]` rather than using hardcoded literals. |

#### M4: `channel_type` and `timezone` — dual identity

| | |
|-|-|
| **File** | `hbo.yaml:4-5`, `cheers-24-7.yaml:4-5` |
| **YAML path** | `channel_type`, `timezone` (top-level scalars) |
| **Current shape** | Pass-through identifiers |
| **Expected shape** | These values also have defaults in `scheduling.default_channel_type` and `scheduling.default_timezone`. The current resolution treats them as pass-through, so they cannot fall back to scheduling defaults. |
| **Impact** | If a channel omits `timezone`, `YamlChannelConfigProvider` falls back to `"UTC"` (hardcoded), not to `scheduling.default_timezone` from the resolved config. |
| **Recommendation** | `YamlChannelConfigProvider` should read the fallback from resolved config. |

### LOW severity — cosmetic / naming

#### L1: `video_bitrate` not present in channel YAML but available in defaults

| | |
|-|-|
| **Files** | All channel YAMLs |
| **YAML path** | `format.video.video_bitrate` (absent) |
| **Current shape** | Not specified — comes from `ProgramFormat` default of `8_000_000` |
| **Expected shape** | Should come from `channel.encoding.video_bitrate_bps` in defaults.yaml |
| **Impact** | Channels cannot override bitrate via YAML. |
| **Recommendation** | Add `encoding:` section to format pass-through, or allow `channel.encoding.video_bitrate_bps` override in governed domain. |

#### L2: `channel_number` backward-compat alias

| | |
|-|-|
| **File** | `yaml_channel_config_provider.py:145` |
| **Current shape** | Accepts both `number` and `channel_number` |
| **Expected shape** | Single canonical key |
| **Recommendation** | Deprecate `channel_number`; use `number` exclusively. |

---

## 7. Proposed Channel YAML Structure

This section defines the canonical shape for channel YAML files after all mismatches are resolved.

### Top-Level Layout

```yaml
# --- Identifiers (pass-through, required) ---------------------------------
channel_id: hbo                        # Unique slug. MUST NOT collide with governed domain names.
number: 201                            # External channel number. Positive integer. Unique.
name: "Home Box Office"                # Display name. Optional (defaults to titleized slug).
channel_type: premium                  # "network" | "premium" | "movie". Optional (from defaults).
timezone: America/New_York             # IANA timezone. Optional (from defaults).

# --- Technical format (pass-through) --------------------------------------
format:
  video: { width: 1280, height: 720, frame_rate: "30000/1001" }
  audio: { sample_rate: 48000, channels: 2 }

# --- Filler (pass-through, optional) --------------------------------------
filler:
  path: "/opt/retrovue/assets/filler.mp4"
  duration_ms: 3650000

# --- Editorial domain data (pass-through) ---------------------------------
pools:
  movies_r:
    match: { type: movie, rating: R }

programs:
  hbo_movies_r:
    pool: movies_r
    grid_blocks_max: 5
    fill_mode: single

traffic:
  default_profile: hbo_premium
  profiles:
    hbo_premium:
      allowed_types: [trailer, teaser]

schedule:
  all_day:
    - start: "06:00"
      slots: 20
      program: hbo_movies_r
      progression: random

# --- Defaults overrides (governed, optional) --------------------------------
# Any key matching a defaults.yaml domain merges recursively.
# Only dict values are treated as overrides; scalars are identifiers.
channel:
  linger_seconds: 60
  encoding:
    video_bitrate_bps: 12000000

hls:
  segmenter:
    target_duration_ms: 4000
```

### Key Decisions

1. **`channel_id:` replaces `channel:`** — eliminates the governed-domain name collision. The resolver no longer needs the `channel_id` rename workaround.

2. **`grid_minutes` moves out of `format:`** — grid geometry is a scheduling concern. Channels that need a non-default grid override it under the `scheduling` governed domain:
   ```yaml
   scheduling:
     grid_minutes:
       premium_movie: 20
   ```

3. **`format:` remains pass-through** — its nested shape (`video.width`, `audio.channels`) does not match the flat shape in `channel.default_program_format`. Rather than force alignment, `format:` stays pass-through and `YamlChannelConfigProvider` continues to map between the two shapes. The mapping code MUST read its fallback values from `resolved_config["channel"]["default_program_format"]`.

4. **`channel_type` and `timezone` remain top-level identifiers** — but `YamlChannelConfigProvider` MUST read their fallback values from `resolved_config["scheduling"]` instead of hardcoded strings.

5. **Filler defaults move to `config/defaults.yaml`** under `channel.filler.path` and `channel.filler.duration_ms`. `YamlChannelConfigProvider` reads these from resolved config when the channel YAML omits `filler:`.

---

## 8. Validation Rules

### Required Keys

A channel YAML MUST contain:
- `channel_id` (or `channel` during migration period) — string, non-empty
- `number` — positive integer, unique across all channels

### Structural Rules

- Top-level keys that match a governed domain name (`scheduling`, `playout`, `channel`, `hls`, `streaming`, `system`, `integrations`, `air`) MUST be dicts if present. A scalar value at a governed domain key is an error (except during the `channel` → `channel_id` migration).
- Pass-through domain keys (`pools`, `programs`, `schedule`, `traffic`, `format`, `filler`) are not validated against defaults.yaml.
- Unknown top-level keys that are not identifiers, pass-through domains, or governed domains MUST be rejected.

### Type Rules

Governed overrides follow the type compatibility rules from `configuration_resolution.md` §6.2:
- `int` overrides `int`
- `int` or `float` overrides `float`
- `str` overrides `str`
- `bool` overrides `bool`

---

## Required Tests

- `pkg/core/tests/contracts/test_inv_config_resolution.py`
- `pkg/core/tests/contracts/test_channel_yaml_contract.py` (to be created)

## Enforcement Evidence
TODO
