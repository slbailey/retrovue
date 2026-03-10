# Traffic DSL — Domain Contract

Status: Contract
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-ELIGIBILITY`, `LAW-DERIVATION`

---

## Overview

The Traffic DSL defines how channel configuration declaratively expresses traffic behavior. Traffic behavior encompasses three distinct concerns: what interstitial assets exist (inventory), how those assets are filtered and selected (policy), and where they are placed in the program timeline (placement).

The Channel DSL MUST express all three concerns in YAML. The runtime traffic engine consumes the resolved configuration — it MUST NOT hardcode traffic rules, infer policy from content type, or invent placement logic.

This contract governs traffic configuration declared in the Channel DSL. The declared TrafficProfiles resolve to runtime TrafficPolicy objects defined in `traffic_policy.md`. Break placement is not defined here and is governed by `break_detection.md`.

This contract does not define candidate evaluation rules — runtime filtering, cooldown enforcement, rotation semantics, and cap evaluation are governed exclusively by `traffic_policy.md`. The three contracts are complementary and MUST NOT overlap in authority.

### Authority Boundary

This contract owns:
- YAML schema for `traffic.inventories`, `traffic.profiles`, `traffic.default_profile`, and `traffic.break_config`
- Profile resolution order (block override → channel default)
- Break config resolution (YAML → `BreakConfig` domain object)
- Inventory resolution timing (planning-time only)
- TrafficProfile-to-TrafficPolicy mapping rules
- Validation of profile references and inventory types at load time

This contract does NOT own:
- Runtime candidate filtering, cooldown enforcement, rotation, or cap evaluation (`traffic_policy.md`)
- Break opportunity identification or placement (`break_detection.md`)
- Traffic fill orchestration (`traffic_manager` — consumes both contracts)

---

## Domain Objects

### TrafficInventory

A named set of interstitial assets available to a channel for break fill.

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Inventory identifier, unique per channel. |
| `match` | dict | Asset query filter (same schema as pool `match`). |
| `asset_type` | string | Interstitial classification: `"commercial"`, `"promo"`, `"trailer"`, `"station_id"`, `"psa"`, `"stinger"`, `"bumper"`, `"filler"`. |

TrafficInventory is the traffic analogue of a content pool. It defines which assets are candidates for traffic fill. It does not define selection rules — that is the policy's concern.

### TrafficProfile

A named, reusable traffic policy configuration declared in the channel DSL.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | — | Profile identifier, unique per channel. |
| `allowed_types` | list[str] | union of `asset_type` values from channel inventories | Interstitial types permitted under this profile. |
| `default_cooldown_seconds` | int | `3_600` | Minimum seconds between re-plays of the same asset. |
| `type_cooldowns_seconds` | dict[str, int] | `{}` | Per-type cooldown overrides in seconds. |
| `max_plays_per_day` | int | `0` | Max plays per asset per channel per traffic day. `0` = unlimited. |

A TrafficProfile is the declarative form of a `TrafficPolicy` runtime object (defined in `traffic_policy.md`). Each resolved TrafficProfile is instantiated as a `TrafficPolicy` with identical field names and semantics. The DSL declares the configuration; `traffic_policy.md` defines how the runtime object evaluates candidates against that configuration.

### TrafficAssignment

The binding between a schedule block (or channel default) and a TrafficProfile.

| Field | Type | Description |
|-------|------|-------------|
| `profile` | string | Reference to a named TrafficProfile. |
| `scope` | `"channel"` or `"block"` | Whether this assignment applies channel-wide or to a specific schedule block. |

---

## YAML Structure

### Traffic Inventory Declaration

```yaml
traffic:
  inventories:
    promos:
      match:
        type: promo
        tags: [network]
      asset_type: promo

    station_ids:
      match:
        type: station_id
      asset_type: station_id

    bumpers:
      match:
        type: bumper
        tags: [cheers]
      asset_type: bumper
```

Each inventory declares a query filter and an interstitial type classification. The `asset_type` field MUST be one of the types recognized by `TrafficPolicy.allowed_types`.

### Traffic Profile Declaration

```yaml
traffic:
  profiles:
    default:
      allowed_types: [promo, station_id, bumper]
      default_cooldown_seconds: 3600
      max_plays_per_day: 8

    primetime:
      allowed_types: [promo, station_id]
      default_cooldown_seconds: 1800
      type_cooldowns_seconds:
        station_id: 900
      max_plays_per_day: 12
```

### Break Config Declaration

```yaml
traffic:
  break_config:
    to_break_bumper_ms: 3000
    from_break_bumper_ms: 3000
    station_id_ms: 5000
```

The `break_config` section declares the channel's break structure configuration. When present, it is resolved to a `BreakConfig` domain object (defined in `break_structure.md`) and passed to the traffic manager for structured break expansion. When absent, the traffic manager uses legacy flat-fill behavior.

All fields are optional and default to `0` (meaning the corresponding structural slot is omitted):

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `to_break_bumper_ms` | int | `0` | Duration of the to-break bumper slot. |
| `from_break_bumper_ms` | int | `0` | Duration of the from-break bumper slot. |
| `station_id_ms` | int | `0` | Duration of the station ID slot. |

### Channel-Level Default

```yaml
traffic:
  default_profile: default
```

The `default_profile` field names the TrafficProfile applied to all schedule blocks that do not specify an override. Every channel MUST declare a `default_profile`.

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

When the runtime resolves traffic policy for a schedule block:

1. If the block declares `traffic_profile`, use that profile.
2. Otherwise, use `traffic.default_profile`.

There are exactly two levels. There is no program-level traffic configuration. Programs are content assembly recipes — they do not carry traffic policy. Traffic policy is an editorial scheduling concern, not a content concern.

### Inventory Resolution

At channel load time, all declared inventories are resolved against the asset catalog. The resolved asset lists are passed to the traffic manager as the candidate pool. Inventory resolution is a planning-time operation — it MUST NOT occur during playout.

### Profile-to-Policy Mapping

Each TrafficProfile in the DSL maps 1:1 to a `TrafficPolicy` domain object at runtime. Field names and semantics are identical. The DSL is the declaration; the runtime object is the instantiation.

When `allowed_types` is omitted from a profile, the resolved `TrafficPolicy` receives the union of all `asset_type` values declared across the channel's `traffic.inventories`. This DSL-level default takes precedence over the structural default defined in `traffic_policy.md`.

---

## Invariants

### INV-TRAFFIC-DSL-DEFAULT-REQUIRED-001 — Channel must declare default traffic profile

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-ELIGIBILITY`

**Guarantee:** Every channel configuration that declares a `traffic` section MUST include a `default_profile` that references a named profile in `traffic.profiles`. A channel with traffic inventories but no default profile is invalid.

**Violation:** A channel YAML with `traffic.inventories` but no `traffic.default_profile`; a `default_profile` that references a profile name not present in `traffic.profiles`.

---

### INV-TRAFFIC-DSL-INVENTORY-TYPE-001 — Inventory asset_type must be a recognized type

Status: Invariant
Authority Level: Planning
Derived From: `LAW-ELIGIBILITY`

**Guarantee:** Every `traffic.inventories` entry MUST declare an `asset_type` whose value is one of the recognized interstitial types: `"commercial"`, `"promo"`, `"trailer"`, `"station_id"`, `"psa"`, `"stinger"`, `"bumper"`, `"filler"`. Unrecognized types MUST be rejected at configuration load time.

**Violation:** An inventory entry with `asset_type: "unknown"` that is accepted without error.

---

### INV-TRAFFIC-DSL-PROFILE-REF-VALID-001 — Traffic profile references must resolve

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`, `LAW-CONTENT-AUTHORITY`

**Guarantee:** Every `traffic_profile` reference on a schedule block MUST name a profile that exists in `traffic.profiles`. Every `default_profile` reference MUST name a profile that exists in `traffic.profiles`. Dangling references MUST be rejected at configuration load time.

**Violation:** A schedule block with `traffic_profile: primetime` when no profile named `primetime` exists in `traffic.profiles`; a load-time pass that silently ignores an unresolvable reference.

---

### INV-TRAFFIC-DSL-NO-PROGRAM-POLICY-001 — Programs must not carry traffic policy

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

**Guarantee:** Program definitions MUST NOT include traffic policy fields (`allowed_types`, `cooldown`, `max_plays_per_day`, `traffic_profile`). Traffic policy is bound to schedule blocks or the channel default. Programs define content assembly only.

**Violation:** A program definition in the DSL that includes any traffic policy field; a runtime path that reads traffic configuration from a program object.

---

### INV-TRAFFIC-DSL-PLACEMENT-FROM-BREAKS-001 — Traffic placement must come from break detection

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

**Guarantee:** The DSL MUST NOT declare break positions, break counts, or break timing. Traffic placement is determined exclusively by break detection at assembly time. The DSL controls what fills breaks (via profiles) and what assets are available (via inventories), never where breaks occur.

**Violation:** A channel YAML field that specifies break positions, break intervals, or number of breaks per program; a runtime path that reads break placement from configuration instead of from a `BreakPlan`.

---

### INV-TRAFFIC-DSL-BREAK-CONFIG-001 — Break config resolves to BreakConfig or None

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

**Guarantee:** When `traffic.break_config` is present in the channel YAML, `resolve_break_config()` MUST return a `BreakConfig` instance with field values matching the YAML declaration. When `traffic.break_config` is absent, `resolve_break_config()` MUST return `None`. When `traffic.break_config` is present but empty (all fields omitted), `resolve_break_config()` MUST return a `BreakConfig` with all fields defaulting to `0`.

**Violation:** A channel YAML with `traffic.break_config.to_break_bumper_ms: 3000` that produces a `BreakConfig` with `to_break_bumper_ms != 3000`; a channel YAML without `traffic.break_config` that produces a non-None `BreakConfig`; a channel YAML with an empty `traffic.break_config` that returns `None` instead of `BreakConfig(0, 0, 0)`.

---

### INV-TRAFFIC-DSL-INVENTORY-PLANNING-ONLY-001 — Inventory resolution is a planning-time operation

Status: Invariant
Authority Level: Planning
Derived From: `LAW-ELIGIBILITY`, `LAW-RUNTIME-AUTHORITY`

**Guarantee:** Traffic inventories MUST be resolved against the asset catalog at planning time (channel load or schedule compilation). Inventory resolution MUST NOT occur during playout block execution. The resolved candidate list is passed to the traffic manager as a materialized set.

**Violation:** An inventory `match` query that executes during `on_block_started` or within the playout callback path; a traffic manager that queries the asset catalog directly instead of consuming a pre-resolved candidate list.

---

## Pipeline Integration

```
Channel YAML
     │
     ├── traffic.inventories  ──→  Asset catalog query (planning time)
     │                                    │
     │                                    ▼
     │                              Resolved candidate lists
     │                                    │
     ├── traffic.profiles     ──→  TrafficPolicy instantiation
     │                                    │
     ├── traffic.default_profile          │
     │        │                           │
     │        ▼                           │
     │   Schedule block resolution        │
     │   (block.traffic_profile           │
     │    or default_profile)             │
     │        │                           │
     │        ▼                           │
     │   Resolved TrafficPolicy    ◄──────┘
     │        │
     ├── traffic.break_config ──→  BreakConfig instantiation
     │        │                           │
     │        ▼                           ▼
     │   Break Detection (BreakPlan)
     │        │
     │        ▼
     │   Traffic Fill
     │   (policy + candidates + break plan
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
channel_type: network

format:
  grid_minutes: 30

pools:
  cheers:
    match:
      type: episode
      series_title: Cheers

programs:
  cheers_30:
    pool: cheers
    grid_blocks: 1
    fill_mode: single
    bleed: false

traffic:
  break_config:
    to_break_bumper_ms: 3000
    from_break_bumper_ms: 3000
    station_id_ms: 5000

  inventories:
    promos:
      match:
        type: promo
        tags: [nbc, cheers]
      asset_type: promo

    station_ids:
      match:
        type: station_id
        tags: [nbc]
      asset_type: station_id

    bumpers:
      match:
        type: bumper
        tags: [cheers]
      asset_type: bumper

  profiles:
    default:
      allowed_types: [promo]
      default_cooldown_seconds: 3600
      max_plays_per_day: 8

  default_profile: default

schedule:
  all_day:
    - start: "06:00"
      slots: 48
      program: cheers_30
      progression: sequential
```

---

## Required Tests

- `pkg/core/tests/contracts/test_traffic_dsl.py`

---

## Enforcement Evidence

TODO
