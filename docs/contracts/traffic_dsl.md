# Traffic DSL — Domain Contract

Status: Contract
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-ELIGIBILITY`, `LAW-DERIVATION`

---

## Overview

The Traffic DSL defines how channel configuration declaratively expresses traffic fill behavior. Traffic is Tier 4: it fills time remaining after structural segments (Tiers 0–3) are placed. Traffic behavior encompasses two concerns: how fill assets are filtered and selected (policy), and where they are placed in the block timeline (placement).

The Channel DSL expresses both concerns in YAML. The runtime traffic engine consumes the resolved configuration — it MUST NOT hardcode traffic rules, infer policy from content type, or invent placement logic.

This contract governs traffic configuration declared under the `traffic` section of a channel YAML file. The declared TrafficProfiles resolve to runtime TrafficPolicy objects defined in `traffic_policy.md`. Break placement is governed by `break_detection.md`. Fill allocation is governed by `INV-DSL-UNIFIED-FILL-001` in `channel_dsl.md`.

This contract does not define candidate evaluation rules — runtime filtering, cooldown enforcement, rotation semantics, and cap evaluation are governed exclusively by `traffic_policy.md`.

### Authority Boundary

This contract owns:
- YAML schema for `traffic.profiles`, `traffic.default`, and `traffic.break_config`
- Profile resolution order (block override → channel default)
- Break config resolution (YAML → `BreakConfig` domain object)
- TrafficProfile-to-TrafficPolicy mapping rules
- Validation of profile references and pool references at load time

This contract does NOT own:
- Asset set definitions (pools — governed by `channel_dsl.md` and `query_dsl.md`)
- Runtime candidate filtering, cooldown enforcement, rotation, or cap evaluation (`traffic_policy.md`)
- Break opportunity identification or placement (`break_detection.md`)
- Traffic fill orchestration (consumes this contract and `traffic_policy.md`)
- Fill allocation model (`INV-DSL-UNIFIED-FILL-001` in `channel_dsl.md`)

---

## Domain Objects

### TrafficProfile

A named, reusable traffic policy configuration declared in the channel DSL.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | — | Profile identifier, unique per channel. |
| `allowed_pools` | list[str] | — | Pool names eligible for traffic fill under this profile. Each name MUST reference a pool defined in the channel's `pools` section. |
| `weights` | dict[str, int] | equal | Relative selection weight per pool. Keys MUST be a subset of `allowed_pools`. |
| `rotation.strategy` | string | `weighted` | Asset rotation strategy: `weighted` (pool weights drive selection probability) or `round_robin` (cycle through pools sequentially). |
| `duration_strategy` | string | `pack` | `pack` (fill break to capacity with multiple assets) or `single` (one asset per break opportunity). |
| `default_cooldown_seconds` | int | `3600` | Minimum seconds between re-plays of the same asset. |
| `type_cooldowns_seconds` | dict[str, int] | `{}` | Per-pool cooldown overrides in seconds. Keys MUST be a subset of `allowed_pools`. |
| `max_plays_per_day` | int | `0` | Max plays per asset per channel per traffic day. `0` = unlimited. |

A TrafficProfile is the declarative form of a `TrafficPolicy` runtime object (defined in `traffic_policy.md`). Each resolved TrafficProfile is instantiated as a `TrafficPolicy`. The DSL declares the configuration; `traffic_policy.md` defines how the runtime object evaluates candidates against that configuration.

### TrafficAssignment

The binding between a schedule block (or channel default) and a TrafficProfile.

| Field | Type | Description |
|-------|------|-------------|
| `profile` | string | Reference to a named TrafficProfile. |
| `scope` | `"channel"` or `"block"` | Whether this assignment applies channel-wide or to a specific schedule block. |

---

## YAML Structure

### Traffic Profile Declaration

```yaml
traffic:
  profiles:
    hbo_premium:
      allowed_pools: [traffic_trailers, traffic_teasers]
      weights:
        traffic_trailers: 3
        traffic_teasers: 1
      rotation:
        strategy: weighted
      duration_strategy: pack
      default_cooldown_seconds: 3600
      max_plays_per_day: 0

    primetime:
      allowed_pools: [traffic_trailers]
      default_cooldown_seconds: 1800
      max_plays_per_day: 12
```

Traffic profiles reference pools by name. The referenced pools are defined in the channel's top-level `pools` section using `select.where` syntax. Traffic profiles do not define asset queries — pools do.

### Break Config Declaration

```yaml
traffic:
  break_config:
    to_break_bumper_ms: 3000
    from_break_bumper_ms: 3000
    station_id_ms: 5000
```

The `break_config` section declares the channel's break structure configuration. When present, it is resolved to a `BreakConfig` domain object (defined in `break_structure.md`). When absent, flat-fill behavior applies.

All fields are optional and default to `0` (meaning the corresponding structural slot is omitted):

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `to_break_bumper_ms` | int | `0` | Duration of the to-break bumper slot. |
| `from_break_bumper_ms` | int | `0` | Duration of the from-break bumper slot. |
| `station_id_ms` | int | `0` | Duration of the station ID slot. |

### Channel-Level Default

```yaml
traffic:
  default: hbo_premium
```

The `default` field names the TrafficProfile applied to all schedule blocks that do not specify an override. Every channel that declares a `traffic` section MUST declare a `default`.

### Schedule Block Override

```yaml
schedule:
  thursday:
    - start: "20:00"
      slots: 4
      program: cheers_30
      progression: sequential
      traffic_profile: primetime
```

A schedule block MAY include a `traffic_profile` field to override the channel default for that block. The referenced profile MUST exist in `traffic.profiles`.

---

## Resolution Rules

### Profile Resolution Order

When resolving traffic policy for a schedule block:

1. If the block declares `traffic_profile`, use that profile.
2. Otherwise, use `traffic.default`.

There are exactly two levels. There is no program-level traffic configuration. Programs are content assembly recipes — they do not carry traffic policy. Traffic policy is an editorial scheduling concern, not a content concern.

### Pool Resolution

Traffic profiles reference pools by name. At fill time, each referenced pool is resolved against the asset catalog to produce a candidate set. Pool resolution uses the same `select.where` query mechanism as content and presentation pools.

### Profile-to-Policy Mapping

Each TrafficProfile in the DSL maps 1:1 to a `TrafficPolicy` domain object at runtime. The DSL is the declaration; the runtime object is the instantiation.

When `allowed_pools` is omitted from a profile, no pools are eligible. An empty `allowed_pools` is equivalent to no traffic fill.

---

## Invariants

### INV-TRAFFIC-DSL-DEFAULT-REQUIRED-001 — Channel must declare default traffic profile

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-ELIGIBILITY`

**Guarantee:** Every channel configuration that declares a `traffic` section MUST include a `traffic.default` that references a named profile in `traffic.profiles`. A channel with traffic profiles but no default is invalid.

**Violation:** A channel YAML with `traffic.profiles` but no `traffic.default`; a `traffic.default` that references a profile name not present in `traffic.profiles`.

---

### INV-TRAFFIC-DSL-POOL-REF-VALID-001 — Traffic pool references must resolve

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`, `LAW-ELIGIBILITY`

**Guarantee:** Every pool name in a traffic profile's `allowed_pools` MUST reference a pool defined in the channel's top-level `pools` section. Every pool name in `weights` or `type_cooldowns_seconds` MUST be a member of that profile's `allowed_pools`. Dangling references MUST be rejected at configuration load time.

**Violation:** A profile with `allowed_pools: [nonexistent_pool]` when no pool named `nonexistent_pool` exists; a `weights` key that is not in `allowed_pools`.

---

### INV-TRAFFIC-DSL-PROFILE-REF-VALID-001 — Traffic profile references must resolve

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`, `LAW-CONTENT-AUTHORITY`

**Guarantee:** Every `traffic_profile` reference on a schedule block MUST name a profile that exists in `traffic.profiles`. Every `traffic.default` reference MUST name a profile that exists in `traffic.profiles`. Dangling references MUST be rejected at configuration load time.

**Violation:** A schedule block with `traffic_profile: primetime` when no profile named `primetime` exists in `traffic.profiles`; a load-time pass that silently ignores an unresolvable reference.

---

### INV-TRAFFIC-DSL-NO-PROGRAM-POLICY-001 — Programs must not carry traffic policy

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

**Guarantee:** Program definitions MUST NOT include traffic policy fields (`allowed_pools`, `cooldown`, `max_plays_per_day`, `traffic_profile`). Traffic policy is bound to schedule blocks or the channel default. Programs define content assembly only.

**Violation:** A program definition in the DSL that includes any traffic policy field; a runtime path that reads traffic configuration from a program object.

---

### INV-TRAFFIC-DSL-PLACEMENT-FROM-BREAKS-001 — Traffic placement uses break opportunities

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

**Guarantee:** The DSL MUST NOT declare break positions, break counts, or break timing. Break opportunities are determined at compile time by break detection. The DSL controls what fills breaks (via profiles) and what assets are available (via pools), never where breaks occur. Break opportunities are advisory inputs to traffic allocation, not guaranteed insertion points.

**Violation:** A channel YAML field that specifies break positions, break intervals, or number of breaks per program.

---

### INV-TRAFFIC-DSL-BREAK-CONFIG-001 — Break config resolves to BreakConfig or None

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

**Guarantee:** When `traffic.break_config` is present in the channel YAML, resolution MUST produce a `BreakConfig` instance with field values matching the YAML declaration. When `traffic.break_config` is absent, resolution MUST produce `None`. When `traffic.break_config` is present but empty (all fields omitted), resolution MUST produce a `BreakConfig` with all fields defaulting to `0`.

**Violation:** A channel YAML with `traffic.break_config.to_break_bumper_ms: 3000` that produces a `BreakConfig` with `to_break_bumper_ms != 3000`; a channel YAML without `traffic.break_config` that produces a non-None `BreakConfig`.

---

## Pipeline Integration

```
Channel YAML
     │
     ├── pools (top-level)      ──→  Asset catalog queries (planning time)
     │                                    │
     │                                    ▼
     │                              Pool candidate sets
     │                                    │
     ├── traffic.profiles       ──→  TrafficPolicy instantiation
     │                                    │
     ├── traffic.default                  │
     │        │                           │
     │        ▼                           │
     │   Schedule block resolution        │
     │   (block.traffic_profile           │
     │    or traffic.default)             │
     │        │                           │
     │        ▼                           │
     │   Resolved TrafficPolicy    ◄──────┘
     │        │
     ├── traffic.break_config ──→  BreakConfig instantiation
     │        │                           │
     │        ▼                           ▼
     │   Break Detection (advisory BreakPlan)
     │        │
     │        ▼
     │   Traffic Fill
     │   (policy + pool candidates
     │    + advisory break plan
     │    + break config)
     │        │
     │        ▼
     │   Filled break segments
```

---

## Complete Channel Example

```yaml
channel: cheers-24-7
name: "Cheers 24/7"
number: 101
channel_type: network
timezone: America/New_York

format:
  video: { width: 968, height: 720, frame_rate: "30000/1001" }
  audio: { sample_rate: 48000, channels: 2 }
  grid_minutes: 30

pools:
  cheers:
    select:
      where:
        type:
          eq: episode
        series_title:
          eq: Cheers

  traffic_promos:
    select:
      where:
        type:
          eq: promo
        tags:
          contains_all: [nbc, cheers]

  traffic_bumpers:
    select:
      where:
        type:
          eq: bumper
        tags:
          contains_all: [cheers]

programs:
  cheers_30:
    pool: cheers
    grid_blocks: 1
    fill_mode: single

traffic:
  break_config:
    to_break_bumper_ms: 3000
    from_break_bumper_ms: 3000
    station_id_ms: 5000

  profiles:
    default:
      allowed_pools: [traffic_promos]
      default_cooldown_seconds: 3600
      max_plays_per_day: 8

  default: default

schedule:
  all_day:
    - start: "06:00"
      slots: 48
      program: cheers_30
      progression: sequential
```

---

## Required Tests

- `server/tests/contracts/test_traffic_dsl.py`

| Test | Invariant | Scenario |
|---|---|---|
| `test_default_profile_required` | INV-TRAFFIC-DSL-DEFAULT-REQUIRED-001 | Channel with `traffic.profiles` but no `traffic.default` is rejected. |
| `test_default_profile_resolves` | INV-TRAFFIC-DSL-DEFAULT-REQUIRED-001 | `traffic.default` references existing profile. |
| `test_pool_ref_valid` | INV-TRAFFIC-DSL-POOL-REF-VALID-001 | Profile `allowed_pools` entry referencing nonexistent pool is rejected. |
| `test_weights_subset_of_allowed` | INV-TRAFFIC-DSL-POOL-REF-VALID-001 | `weights` key not in `allowed_pools` is rejected. |
| `test_profile_ref_valid` | INV-TRAFFIC-DSL-PROFILE-REF-VALID-001 | Schedule block `traffic_profile` referencing nonexistent profile is rejected. |
| `test_no_program_policy` | INV-TRAFFIC-DSL-NO-PROGRAM-POLICY-001 | Program with traffic policy fields is rejected. |
| `test_no_declared_breaks` | INV-TRAFFIC-DSL-PLACEMENT-FROM-BREAKS-001 | Channel YAML with break position fields is rejected. |
| `test_break_config_present` | INV-TRAFFIC-DSL-BREAK-CONFIG-001 | `traffic.break_config` produces matching `BreakConfig`. |
| `test_break_config_absent` | INV-TRAFFIC-DSL-BREAK-CONFIG-001 | Missing `traffic.break_config` produces `None`. |
| `test_break_config_empty` | INV-TRAFFIC-DSL-BREAK-CONFIG-001 | Empty `traffic.break_config` produces `BreakConfig(0, 0, 0)`. |

---

## Enforcement Evidence

TODO
