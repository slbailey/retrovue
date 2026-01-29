_Related: [Architecture](../architecture/ArchitectureOverview.md) • [Asset](Asset.md) • [SchedulePlan](SchedulePlan.md) • [Program](Program.md) • [VirtualAsset](VirtualAsset.md) • [Scheduling](Scheduling.md)_

# Domain — ContentPolicyRule

**⚠️ FUTURE FEATURE — NOT MVP-CRITICAL**

This document describes a planned feature that is not part of the initial MVP release. This feature may be implemented in a future version of RetroVue and is aligned with the long-term roadmap.

## Purpose

ContentPolicyRule is a placeholder for future infrastructure around **content filtering, eligibility rules, and smart selection**. It will enable operators to define reusable rules that specify content selection criteria, allowing the system to intelligently select assets based on metadata, ratings, duration, genre, and other attributes.

**Example:** A ContentPolicyRule might define "pick a G-rated 90s cartoon with runtime < 30m" — a reusable rule that can be applied to Programs placed in Zones. Programs can reference ContentPolicyRule to automatically select content based on the rule criteria.

**Critical Note:** ContentPolicyRule is **not yet implemented** but is aligned with the long-term roadmap for RetroVue's content selection and scheduling capabilities.

## Core Model / Scope

ContentPolicyRule will enable:

- **Content filtering**: Define criteria to filter assets from the catalog (e.g., rating, genre, decade, duration)
- **Eligibility rules**: Specify what content is eligible for specific grid blocks, channels, or programming contexts
- **Smart selection**: Automatically select assets that match specified criteria (e.g., "pick a G-rated 90s cartoon with runtime < 30m")
- **Reusable rules**: Define once, use many times across different schedule plans and assignments
- **Complex criteria**: Combine multiple filters and constraints (rating + genre + duration + freshness, etc.)
- **Rule composition**: Build complex selection logic from simpler rule components

**Key Points:**

- ContentPolicyRule is a placeholder for future content filtering and smart selection infrastructure
- Will enable reusable rules for content eligibility and selection
- Supports complex criteria combining multiple attributes (rating, genre, duration, decade, etc.)
- Not yet implemented but aligned with long-term roadmap
- Will integrate with [Program](Program.md) entries inside Patterns and [VirtualAsset](VirtualAsset.md) for content selection

## Contract / Interface

ContentPolicyRule will define:

- **Rule identity**: Unique identifier for the rule
- **Rule name**: Human-readable name for the rule (e.g., "G-Rated 90s Cartoons Under 30m")
- **Filter criteria**: JSON or structured criteria specifying:
  - Rating constraints (e.g., G, PG, TV-PG)
  - Genre filters (e.g., cartoon, comedy, drama)
  - Duration constraints (e.g., runtime < 30 minutes, duration between 20-45 minutes)
  - Decade/era filters (e.g., 1990s, 2000s)
  - Series or collection filters
  - Freshness requirements (e.g., not aired in last 7 days)
  - Other metadata-based filters
- **Selection logic**: How to select from matching assets (e.g., random, sequential, least-recently-used, highest-rated)
- **Reusability**: Can be referenced across multiple schedule plans and assignments

**Example Rule Definition:**

```json
{
  "name": "G-Rated 90s Cartoons Under 30m",
  "criteria": {
    "rating": "G",
    "genre": ["cartoon", "animation"],
    "decade": "1990s",
    "duration_max_minutes": 30,
    "freshness_days": 7
  },
  "selection_logic": "random",
  "avoid_repeats": true
}
```

## Execution Model

ContentPolicyRule will be used during content selection:

1. **Rule Definition**: Operators create ContentPolicyRule records that define filtering and selection criteria
2. **Rule Reference**: Rules are referenced in [Program](Program.md) asset chains or [VirtualAsset](VirtualAsset.md) definitions
3. **Rule Evaluation**: During playlist generation, rules are evaluated against the asset catalog to find matching assets
4. **Asset Selection**: The system selects assets from the matching set based on the rule's selection logic
5. **Schedule Integration**: Selected assets are included in [ScheduleDay](ScheduleDay.md) and [PlaylogEvent](PlaylogEvent.md) records

**Integration Points:**

- **Programs in Zones**: Rules can be referenced in Programs placed in Zones to automatically select content (e.g., Program references a rule for "G-rated 90s cartoons < 30m")
- **VirtualAsset**: Rules can be used within VirtualAsset definitions for dynamic content selection
- **Asset Catalog**: Rules evaluate against asset metadata to find eligible content

## Relationship to Programs in Zones

ContentPolicyRule will integrate with [Program](Program.md) entries placed in Zones to enable smart content selection:

- Programs can reference ContentPolicyRule in their asset chains instead of specific assets or series
- Rules are evaluated during playlist generation to select eligible assets based on the rule criteria
- Selected assets are resolved to concrete Asset UUIDs in the Playlist

**Example Usage:**
A Program placed in a Zone references a ContentPolicyRule:

```json
{
  "content_type": "rule",
  "content_ref": "g-rated-90s-cartoons-under-30m"
}
```

Note: Programs do not have `start_time`/`duration` — that's determined by Zones and Schedule context.

## Relationship to VirtualAsset

ContentPolicyRule will integrate with [VirtualAsset](VirtualAsset.md) to enable rule-based content selection within virtual asset containers:

- VirtualAssets can use ContentPolicyRule for dynamic asset selection
- Rules provide the logic for selecting assets within rule-based VirtualAssets
- Example: A VirtualAsset might define "intro + 2 assets selected by rule X" where rule X is a ContentPolicyRule

## Examples

### Example 1: G-Rated 90s Cartoons Under 30m

**ContentPolicyRule Definition:**

- Name: `g-rated-90s-cartoons-under-30m`
- Criteria:
  - Rating: G
  - Genre: cartoon, animation
  - Decade: 1990s
  - Duration: < 30 minutes
  - Avoid content aired in last 7 days
- Selection logic: Random from matching set

**Usage in Program placed in Zone:**
Program references a ContentPolicyRule for "G-rated 90s cartoons < 30m":

```json
{
  "content_type": "rule",
  "content_ref": "g-rated-90s-cartoons-under-30m"
}
```

**Evaluation Result:**

- During ScheduleDay generation, system evaluates rule against asset catalog
- Finds matching assets (e.g., SpongeBob S01E05, Rugrats S02E12, etc.)
- Randomly selects one asset that matches all criteria
- Resolves to concrete Asset UUID in ScheduleDay

### Example 2: Prime-Time Drama Movies

**ContentPolicyRule Definition:**

- Name: `prime-time-drama-movies`
- Criteria:
  - Genre: drama
  - Duration: 90-150 minutes
  - Rating: PG-13 or R
  - Avoid content aired in last 30 days
  - Prefer content with "classic" tag
- Selection logic: Least-recently-used from matching set

**Usage in VirtualAsset:**
A VirtualAsset might use this rule to select the movie component:

- Intro (fixed) → Movie (selected by rule) → Outro (fixed)

## Benefits

ContentPolicyRule will provide several benefits:

1. **Smart Selection**: Automatically select content based on complex criteria without manual asset selection
2. **Reusability**: Define once, use many times across different plans and grid blocks
3. **Consistency**: Ensure consistent content selection patterns across programming
4. **Flexibility**: Support complex filtering and selection logic
5. **Maintainability**: Update rule definitions to affect all references
6. **Efficiency**: Reduce manual content selection work for operators

## Implementation Considerations

**Future Implementation Notes:**

- ContentPolicyRule will require a persistence model (table or JSON storage)
- Rule evaluation engine will need access to asset catalog and metadata
- Rule language/format must support complex criteria combinations
- Performance considerations for rule evaluation against large asset catalogs
- Integration with Programs in Patterns and VirtualAsset systems
- Validation to ensure rules can be evaluated and produce valid results

## Out of Scope (MVP)

ContentPolicyRule is not part of the initial MVP release. The following are deferred:

- ContentPolicyRule persistence and management
- Rule definition language and format
- Rule evaluation engine
- Integration with Programs in Patterns
- Integration with VirtualAsset
- ContentPolicyRule CLI commands and operator workflows
- Rule validation and testing tools

## See Also

- [Asset](Asset.md) - Atomic unit of broadcastable content (what rules select from)
- [SchedulePlan](SchedulePlan.md) - Top-level operator-created plans that define channel programming
- [Program](Program.md) - Catalog entities in Patterns (can reference rules)
- [VirtualAsset](VirtualAsset.md) - Container for multiple assets (can use rules for selection)
- [ScheduleDay](ScheduleDay.md) - Resolved schedules (rules evaluated here)
- [Scheduling](Scheduling.md) - High-level scheduling system

**Note:** ContentPolicyRule is a placeholder for future infrastructure around content filtering, eligibility rules, and smart selection (e.g., pick a G-rated 90s cartoon with runtime < 30m). It is not yet implemented but is aligned with the long-term roadmap for RetroVue's content selection and scheduling capabilities.
