# DSL Vocabulary — Language Contract

Status: Contract
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

---

## Purpose

This document defines the canonical vocabulary of the RetroVue Channel DSL. All DSL contracts, channel YAML files, and DSL-consuming code MUST use the terms defined here. Terms not defined here MUST NOT appear in DSL context.

This is a language contract. It defines what words mean, what words are allowed, and what words are prohibited. It does not define behavior, structure, or implementation — those belong to the contracts that consume this vocabulary.

---

## Core Concepts

### pool

A named set of candidate assets defined by a declarative query. Pools are the universal mechanism for defining asset sets. Content, presentation, traffic, and obligations all reference pools.

Pools define WHAT is available. They do not define selection strategy, ordering, rotation, or progression.

### program

A reusable editorial recipe that defines how content is assembled from a pool. Programs own Tier 0 (primary content) selection and reference a presentation definition for Tier 1 (mandatory presentation).

Programs define content assembly. They do not define progression, timing, or traffic behavior.

### presentation

A named structure defining the preroll and postroll segments that accompany a program or daypart. Presentation defines segment structure and ordering. It does not define selection outcomes.

Presentation entries reference pools. Asset selection from those pools is resolved at compile time.

### segment

A duration-bearing unit within a compiled block. Every segment has a type, an asset reference, and a duration. Segments are classified by tier:

| Tier | Name | Examples |
|---|---|---|
| 0 | Primary content | movie, episode |
| 1 | Mandatory program presentation | intro, rating card |
| 2 | Clock/daypart obligation | station ID, daypart intro, legal ID |
| 3 | Optional enrichment | coming up next, channel ident |
| 4 | Fill | promo, trailer, commercial |

Tiers 0–3 are structural. Tier 4 is fill.

### traffic

The fill layer (Tier 4) that occupies time remaining after structural segments are placed. Traffic is governed by profiles that reference pools and define rotation, cooldowns, and caps.

Traffic fills time. It does not create time, displace structural segments, or modify block structure.

### schedule

The time-first specification of what airs when. Schedule blocks bind programs to grid-aligned time slots with progression rules and optional daypart assignment.

The schedule owns timing and progression. It does not own content assembly, presentation structure, or traffic behavior.

### daypart

A named time-of-day context declared on a schedule block. Dayparts activate daypart-level presentation (Tier 2 obligations, additional preroll/postroll). A daypart is not a time range — it is a label applied to schedule blocks that fall within an editorial time window.

---

## Query Language

### select.where

The sole query mechanism in the DSL. Appears on pools (defining the candidate set), programs (narrowing a pool), and presentation entries (contextual filtering).

```yaml
select:
  where:
    <field>:
      <operator>: <value>
```

All fields are AND-combined. Multiple operators on the same field are AND-combined.

### Operators

| Operator | Meaning | Value type |
|---|---|---|
| `eq` | Exact equality | scalar |
| `in` | Value is one of set | list |
| `contains_all` | All specified values present in target | list |
| `contains_any` | At least one specified value present in target | list |
| `lte` | Less than or equal | scalar |
| `gte` | Greater than or equal | scalar |

Operators are explicit. There is no implicit matching. A field without an operator is invalid.

---

## Contextual References

Within `presentation` entries, query values MAY reference properties of the current compilation context using dotted notation.

### program.*

Properties of the primary content asset selected for the current block.

| Reference | Resolves to |
|---|---|
| `program.rating` | MPAA rating of the selected content asset |
| `program.release_year` | Release year of the selected content asset |
| `program.genre` | Primary genre of the selected content asset |

Resolved at compile time, after Tier 0 content is selected and before Tier 1–3 segments are resolved.

### block.*

Properties of the current schedule block.

| Reference | Resolves to |
|---|---|
| `block.daypart` | Daypart label declared on the schedule block |
| `block.start` | Grid-aligned start time of the block |

### channel.*

Properties of the channel definition.

| Reference | Resolves to |
|---|---|
| `channel.type` | Channel type (`network` or `premium`) |
| `channel.name` | Channel display name |

---

## Canonical Naming

The following names are authoritative. The DSL MUST use these terms exclusively.

| Canonical term | Applies to | Description |
|---|---|---|
| `pools` | Top-level section | Asset set definitions |
| `allowed_pools` | Traffic profile field | Pool names eligible for traffic fill |
| `default` | Traffic section field | Channel-level default traffic profile |
| `select` | Query entry point | Begins a declarative query |
| `where` | Query clause | Filter conditions |
| `presentation` | Top-level section; program field | Segment structure definitions; program-to-presentation binding |
| `daypart` | Schedule block field | Activates daypart-level presentation |
| `preroll` | Presentation subsection | Segments before primary content |
| `postroll` | Presentation subsection | Segments after primary content |

---

## Prohibited Language

The following terms MUST NOT appear in canonical channel YAML, DSL contracts, or DSL-consuming interfaces. Their presence indicates legacy patterns that have been superseded.

| Prohibited term | Replaced by | Reason |
|---|---|---|
| `match` | `select.where` | Implicit matching replaced by explicit operators |
| `inventories` | `pools` | Pools are universal; separate inventory concept eliminated |
| `traffic.inventories` | `pools` (top-level) | Traffic-eligible assets defined as pools, referenced by `allowed_pools` |
| `asset_type` (on inventory) | Pool query | Pool `select.where` defines eligibility; no classification field needed |
| `allowed_types` | `allowed_pools` | Profiles reference pools by name, not by type classification |
| `default_profile` | `default` | Simplified key name |
| `intro` (on program) | `presentation` | Multi-segment preroll/postroll replaces single-asset intro/outro |
| `outro` (on program) | `presentation` | Same |
| `collection` | `pool` | Legacy term for asset set |
| `episode_selector` | `select.where` on program | Legacy selector syntax |
| `movie_selector` | `select.where` on program | Legacy selector syntax |

---

## Invariant

### INV-DSL-VOCABULARY-001

All DSL contracts, channel YAML files, and DSL-facing interfaces MUST use the vocabulary defined in this document exclusively. Prohibited terms MUST NOT appear in canonical DSL artifacts. New DSL terms MUST be added to this document before use in any contract.

---

## Required Tests

- `pkg/core/tests/contracts/test_dsl_vocabulary.py`

| Test | Invariant | Scenario |
|---|---|---|
| `test_no_match_in_yaml` | INV-DSL-VOCABULARY-001 | No channel YAML under `config/channels/` contains `match:` as a pool query keyword. |
| `test_no_inventories_in_yaml` | INV-DSL-VOCABULARY-001 | No channel YAML contains `traffic.inventories`. |
| `test_no_allowed_types_in_yaml` | INV-DSL-VOCABULARY-001 | No channel YAML contains `allowed_types` in a traffic profile. |
| `test_no_default_profile_in_yaml` | INV-DSL-VOCABULARY-001 | No channel YAML contains `default_profile` (must be `default`). |

---

## Enforcement Evidence

TODO
