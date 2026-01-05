# Assets Select Contract

## Purpose

Define the operator interface for asset selection commands in RetroVue. This contract ensures consistent, predictable behavior when selecting media assets through the CLI for bulk operations such as adding tags, promoting to broadcast catalog, or other asset manipulation tasks. The command can return multiple asset UUIDs for bulk operations.

## Scope

This contract applies to the `retrovue assets select` command, covering asset selection with various filtering criteria and selection modes.

## Design Principles

- **Flexibility:** Support multiple selection criteria (series, genre) and modes (random, sequential)
- **Clarity:** Command syntax must be intuitive for operators
- **Consistency:** JSON output format must be structured and predictable
- **Safety:** Clear error messages for invalid combinations and missing data

## CLI Syntax

The Retrovue CLI MUST expose asset selection using the pattern:

```
retrovue assets select [SERIES] [--series <title>] [--genre <genre>] [--mode <mode>] [--json]
```

The noun (assets) MUST come before the verb (select).

Renaming, reordering, or collapsing these verbs into flags is a breaking change and requires updating this contract.

### Asset Select

```
retrovue assets select [--uuid <uuid>]
                      [--type "TV" | "Movie"]
                      [--title <title>]
                      [--season <season-number>]
                      [--episode <episode-number>]
                      [--genre <genre>]
                      [--mode <mode>]
                      [--json]

// Usage Guidelines:
// - Selecting by UUID: Only --uuid <uuid> is required (all other selectors ignored).
// - For Movie selection: Specify --type "Movie" and --title <title> (movie title). Season/episode not allowed.
// - For TV selection: Specify --type "TV" and --title <title> (series title).
//   - To select entire series: Provide only --title (returns all episodes).
//   - To select specific episode: Provide --title, --season, and --episode (all three required).
//   - Season and episode must be provided together (cannot have one without the other).
// - Genre filtering: Can be combined with type (e.g., --type "TV" --genre "Sitcom" or --type "Movie" --genre "Horror").
// - The CLI should enforce that exactly ONE main selector group is used: either --uuid, or Movie fields, or TV fields.
// - --mode <mode> and --json can be applied to any selector.
// - Command can return multiple asset UUIDs for bulk operations.
```

## Parameters

### Asset Selector (exactly one group required)

- **UUID Selection**:

  - `--uuid <uuid>`: Target specific asset by UUID (all other selectors ignored)

- **Movie Selection**:

  - `--type "Movie"`: Specify movie type
  - `--title <title>`: Target movie by title
  - `--genre <genre>`: Optional genre filter (e.g., "Horror", "Comedy")

- **TV Selection**:
  - `--type "TV"`: Specify TV type
  - `--title <title>`: Target series by title
  - `--season <season-number>`: Optional season filter (must be provided with episode)
  - `--episode <episode-number>`: Optional episode filter (must be provided with season)
  - `--genre <genre>`: Optional genre filter (e.g., "Sitcom", "Drama")

### Selection Mode

- `--mode <mode>`: Selection algorithm
  - `random`: Randomly select from available assets
  - `sequential`: Select in sequential order (S01E01, S01E02, etc.)

### Output Options

- `--json`: Output results in JSON format

## Exit Codes

- `0`: Success - asset selected and returned
- `1`: Error (no episodes found, invalid parameters, validation failure, etc.)

The command MUST NOT partially apply changes and still exit 0.

If any validation fails or no assets match the criteria, the overall exit code MUST be non-zero.

## Safety Expectations

### Mutual Exclusivity Rules

- **Selector Groups**: Must use exactly one selector group (UUID, Movie, or TV)
- **UUID Selection**: When `--uuid` is provided, all other selectors are ignored
- **Type Requirements**: `--type` is required for Movie and TV selections
- **Movie Requirements**: `--title` is required when `--type "Movie"` is specified
- **Movie Restrictions**: `--season` and `--episode` are not allowed for Movie type
- **TV Requirements**: `--title` is required when `--type "TV"` is specified
- **TV Season/Episode Coupling**: If `--season` is provided, `--episode` must also be provided (and vice versa)
- **TV Series Selection**: Can select entire series by providing only `--title` (returns all episodes)
- **Genre Combination**: `--genre` can be combined with Movie or TV selections

### Error Conditions

- **Multiple Selector Groups**: When multiple selector groups are provided
- **Missing Type**: When Movie/TV selectors are used without `--type`
- **Missing Required Fields**: When `--title` is missing for Movie or TV
- **Movie Season/Episode Error**: When `--season` or `--episode` is provided with `--type "Movie"`
- **TV Season/Episode Mismatch**: When only `--season` or only `--episode` is provided for TV (both required if either is provided)
- **No Assets Found**: When no assets match the specified criteria
- **Invalid Genre**: When genre filtering is requested but genre doesn't exist

## JSON Output Structure

When `--json` is passed, all output MUST be valid JSON. The structure can return either a single asset or an array of assets for bulk operations:

### TV Content

```json
{
  "uuid": "123e4567-e89b-12d3-a456-426614174000",
  "id": 123,
  "title": "Episode Title",
  "series_title": "Series Name",
  "season_number": 1,
  "episode_number": 1,
  "kind": "episode",
  "genre": "Sitcom",
  "selection": {
    "mode": "random|sequential",
    "criteria": {
      "type": "TV",
      "title": "Series Name",
      "season": 1,
      "episode": 1,
      "genre": "Sitcom"
    }
  }
}
```

### Movie Content

```json
{
  "uuid": "123e4567-e89b-12d3-a456-426614174000",
  "id": 123,
  "title": "Movie Title",
  "kind": "movie",
  "genre": "Horror",
  "selection": {
    "mode": "random",
    "criteria": {
      "type": "Movie",
      "title": "Movie Title",
      "genre": "Horror"
    }
  }
}
```

### JSON Field Requirements

#### Common Fields

- `uuid`: Asset UUID (string)
- `id`: Asset database ID (integer)
- `title`: Asset title (string)
- `kind`: Asset type - "episode" for TV, "movie" for Movie (string)
- `genre`: Genre name if specified (string, optional)
- `selection.mode`: Selection mode used (string)
- `selection.criteria.type`: Content type - "TV" or "Movie" (string)

#### TV-Specific Fields

- `series_title`: Series name (string)
- `season_number`: Season number (integer)
- `episode_number`: Episode number (integer)
- `selection.criteria.title`: Series title used for selection (string)
- `selection.criteria.season`: Season number if specified (integer, optional)
- `selection.criteria.episode`: Episode number if specified (integer, optional)

#### Movie-Specific Fields

- `selection.criteria.title`: Movie title used for selection (string)

## Examples

```bash
## Asset Selection Examples

### By UUID

# Select specific asset by UUID
retrovue assets select --uuid "123e4567-e89b-12d3-a456-426614174000" --json

### By Movie

# Random movie selection
retrovue assets select --type "Movie" --title "The Matrix" --mode random --json

# Random horror movie selection
retrovue assets select --type "Movie" --genre "Horror" --mode random --json

# Specific movie with genre
retrovue assets select --type "Movie" --title "The Shining" --genre "Horror" --json

### By TV Series

# Select entire series (returns all episodes)
retrovue assets select --type "TV" --title "The Big Bang Theory" --json

# Select specific episode (season/episode required together)
retrovue assets select --type "TV" --title "The Simpsons" --season 1 --episode 1 --json

# Select all sitcom episodes (returns all episodes)
retrovue assets select --type "TV" --genre "Sitcom" --json

# Select specific series with genre (returns all episodes)
retrovue assets select --type "TV" --title "Friends" --genre "Sitcom" --json

# Specific episode
retrovue assets select --type "TV" --title "Breaking Bad" --season 1 --episode 1 --json

### Bulk Operations Examples

# Select all horror movies for bulk tagging
retrovue assets select --type "Movie" --genre "Horror" --json

# Select all sitcom episodes for catalog promotion
retrovue assets select --type "TV" --genre "Sitcom" --season 1 --episode 1 --json

# Select all episodes from a series for bulk operations
retrovue assets select --type "TV" --title "The Simpsons" --season 1 --episode 1 --json
```

## Selection Behavior

### Random Mode

- **TV Content**: Selects episodes randomly from all available episodes matching criteria
- **Movie Content**: Selects movies randomly from all available movies matching criteria
- **Genre Filtering**: When genre is specified, only selects from assets matching that genre
- Can return multiple assets for bulk operations
- Suitable for bulk asset manipulation tasks

### Sequential Mode

- **TV Content**: Selects episodes in sequential order (S01E01, S01E02, S01E03, etc.)
- **Movie Content**: Sequential mode not applicable to movies (always random)
- When no history exists, starts with S01E01 for TV content
- Can return multiple assets for bulk operations
- Handles multiple seasons correctly (S01E01 → S01E02 → S02E01 → S02E02)

## Database Side Effects

### Asset Selection

- **No Database Changes**: Selection is read-only operation
- **No State Persistence**: Selection does not modify asset or episode records
- **No History Tracking**: Sequential mode does not currently persist selection history
- **Bulk Operations**: Returns multiple asset UUIDs for bulk manipulation tasks

### Scheduler Impact

- Selected assets become candidates for bulk operations (tagging, catalog promotion, etc.)
- No direct impact on scheduler state
- Selection results can be consumed by bulk manipulation systems

## Error Conditions

- **Multiple Selector Groups**: "Cannot specify multiple selector groups (UUID, Movie, TV)"
- **Missing Type**: "Type must be specified for Movie/TV selection"
- **Missing Required Fields**: "Title is required for Movie/TV selection"
- **Movie Season/Episode Error**: "Season and episode are not allowed for Movie type"
- **TV Season/Episode Mismatch**: "Season and episode must be provided together for TV selection"
- **No Assets Found**: "No assets found matching criteria"
- **Invalid Genre**: "Genre '[genre]' not found"
- **Sequential Mode for Movies**: "Sequential mode not applicable to movies"

## Contract Test Coverage

The following test methods enforce this contract:

### Selection Command Tests

- `test_select_series_positional_and_flag_mutual_exclusivity`: Validates mutual exclusivity between positional and flag series arguments
- `test_select_series_positional_and_flag_mutual_exclusivity_human_output`: Validates mutual exclusivity error in human output mode
- `test_select_series_positional_only_works`: Confirms positional series argument works correctly
- `test_select_series_flag_only_works`: Confirms --series flag works correctly
- `test_select_no_filters_error`: Validates error when no filters are provided
- `test_select_genre_only_error`: Validates error when genre filtering is requested (not implemented)

### JSON Output Tests

- `test_select_series_random_json_single_episode`: Validates JSON output structure for single episode selection
- `test_select_series_random_json_multiple_episodes`: Validates JSON output structure for multiple episode selection
- `test_select_series_random_json_no_episodes`: Validates error handling when no episodes found
- `test_select_series_random_json_mutual_exclusivity`: Validates mutual exclusivity error in JSON mode
- `test_select_series_random_json_no_filters`: Validates no filters error in JSON mode
- `test_select_series_sequential_json_first_episode`: Validates sequential mode returns first episode
- `test_select_series_sequential_json_single_episode`: Validates sequential mode with single episode
- `test_select_series_sequential_json_multiple_seasons`: Validates sequential mode across multiple seasons

### Genre Selection Tests

- `test_select_genre_not_implemented`: Validates genre filtering returns appropriate error
- `test_select_genre_with_series_error`: Validates genre takes precedence over series (returns error)
- `test_select_genre_only_no_series`: Validates genre-only selection returns error

## Implementation Notes

- All selection operations must be read-only (no database writes)
- Title matching must be case-sensitive and exact (movie titles for Movie, series titles for TV)
- Sequential mode must handle multiple seasons correctly for TV content
- Sequential mode is not applicable to movies (always use random)
- JSON output must include all required fields with correct data types
- Error messages must be clear and actionable for operators
- Genre filtering must work with both Movie and TV content types
- UUID selection takes precedence over all other selectors

---

## Contract Lifecycle & Governance

This contract is the authoritative rulebook for `retrovue assets select`.  
Follow this lifecycle for any change:

1. **Propose & Edit Contract**

   - Any change to operator-facing behavior must be proposed by editing this contract file first.
   - The change MUST include rationale and updated contract test list entries.

2. **Update Contract Tests**

   - Update or add tests under:
     - `tests/contracts/test_assets_select_contract.py` (CLI/operator surface)
     - `tests/contracts/test_assets_select_data_contract.py` (persistence/data effects)
   - Each test MUST include a `# CONTRACT:` comment referencing the specific clause in this file it enforces.

3. **Implement**

   - Only after tests are updated should implementation changes be made.
   - Implementation must aim to make the contract tests pass.

4. **Changelog & Versioning**
   - Increment the contract version or date at the top of this file when making breaking changes.
   - Add a changelog entry below.

---

## Changelog

| Version | Date       | Summary                                             |
| ------- | ---------- | --------------------------------------------------- |
| 1.0     | 2025-01-27 | Baseline contract derived from existing test files. |

---

## Traceability Matrix (sample)

| Contract Clause               | Test File                                                    | Test Name                                                   |
| ----------------------------- | ------------------------------------------------------------ | ----------------------------------------------------------- |
| JSON output structure         | `tests/cli/test_cli_assets_select_series_random_json.py`     | `test_select_series_random_json_single_episode`             |
| Mutual exclusivity validation | `tests/cli/test_cli_assets_select_mutual_exclusivity.py`     | `test_select_series_positional_and_flag_mutual_exclusivity` |
| Sequential mode behavior      | `tests/cli/test_cli_assets_select_series_sequential_json.py` | `test_select_series_sequential_json_first_episode`          |

---

## Enforcement Rule

The contract defines required behavior. Tests are the enforcement mechanism.  
Implementation must be updated only after the contract and tests are updated.
